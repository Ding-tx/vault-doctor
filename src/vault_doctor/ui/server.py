"""本地 Web UI 服务（v0.4）：stdlib HTTP 服务器 + JSON API，零新增依赖。

安全设计：
- 仅绑定 127.0.0.1，外部网络不可达
- JSON POST 天然抵御跨站表单（浏览器表单发不出 application/json，
  fetch 跨域会因无 CORS 头被拦）
- 写操作保留闸门语义：/api/fix/apply 只应用前端显式勾选批准的文件，
  落盘前照常快照，rollback 随时可回滚；全程事件流留痕
"""
from __future__ import annotations

import difflib
import json
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from vault_doctor import __version__
from vault_doctor.agent.drafter import draft_file_patches, merge_usage
from vault_doctor.cli.why import SYSTEM_PROMPT as WHY_PROMPT
from vault_doctor.cli.why import build_user_prompt
from vault_doctor.config import ConfigError, LLMConfig, load_llm_config, write_llm_config
from vault_doctor.engine.graph import LinkResolver, extract_links
from vault_doctor.engine.indexer import connect, default_db_path, index_vault
from vault_doctor.engine.patches import apply_patches, apply_to_text
from vault_doctor.engine.rules import REGISTRY, run_rules
from vault_doctor.engine.rules.base import RuleContext
from vault_doctor.kernel.transcript import Transcript, new_session_id
from vault_doctor.ledger.budget import BudgetExceeded, TokenLedger
from vault_doctor.llm.client import LLMClient, LLMError, assert_safe_url
from vault_doctor.policy.snapshot import SnapshotError, create_snapshot, list_snapshots_detail, rollback

UI_RULE = "link/near-miss"

# 起草会话状态：draft_id → {vault, patches, usage, created}。单用户本机工具，
# 内存字典足够；起草后未应用的自然过期（下次启动清空）。
_DRAFTS: dict[str, dict] = {}
_DRAFTS_LOCK = threading.Lock()


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def make_client(cfg):
    """测试注入点：替换此函数即可让 UI 全链路走假客户端。
    返回对象需提供 LLMClient 同款接口：chat(system, user) -> (str, dict) 与 close()。"""
    return LLMClient(cfg)


# ---- 模型设置（UI 填 key）：状态打码、保存落 config.local.toml、真调一次测连通 ----

def _config_status() -> dict:
    """当前配置状态；api_key 只出打码形式，完整密钥永不过 API。"""
    try:
        cfg = load_llm_config(None)
    except ConfigError:
        return {"configured": False}
    key = cfg.api_key
    masked = (key[:3] + "***" + key[-4:]) if len(key) > 8 else "***"
    return {"configured": True, "base_url": cfg.base_url, "model": cfg.model, "api_key_masked": masked}


def _cfg_from_body(body: dict) -> LLMConfig:
    base_url = str(body.get("base_url") or "").strip()
    model = str(body.get("model") or "").strip()
    api_key = str(body.get("api_key") or "").strip()
    if not (base_url and model):
        raise ApiError("base_url 与 model 不能为空")
    if not api_key:
        # key 留空 = 只改地址/模型，沿用已保存的密钥
        try:
            api_key = load_llm_config(None).api_key
        except ConfigError:
            raise ApiError("api_key 为空，且本地没有已保存的密钥")
    assert_safe_url(base_url)  # SSRF 防线与正式调用同一条（LLMError → 400）
    return LLMConfig(base_url=base_url, api_key=api_key, model=model)


def _config_save(body: dict) -> dict:
    cfg = _cfg_from_body(body)
    path = Path("config.local.toml").resolve()
    write_llm_config(path, cfg)
    return {"saved": True, "path": str(path)}


def _config_test(body: dict) -> dict:
    cfg = _cfg_from_body(body)
    client = make_client(cfg)
    try:
        content, usage = client.chat("你是连通性测试。无论收到什么，只回复两个字符：OK", "ping")
    finally:
        client.close()
    return {"ok": True, "reply": (content or "").strip()[:40], "usage": usage}


def _resolve_vault(raw) -> Path:
    vault = Path(raw)
    if not vault.is_dir():
        raise ApiError(f"路径不存在或不是目录：{vault}")
    return vault.resolve()


def _scan(vault: Path) -> dict:
    stats = index_vault(vault)
    conn = connect(default_db_path(vault))
    try:
        notes = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        assets = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        violations = run_rules(RuleContext(conn))
    finally:
        conn.close()
    return {
        "notes": notes,
        "assets": assets,
        "elapsed": round(stats.elapsed, 2),
        "violations": [v.model_dump() for v in violations],
    }


def _rules_payload() -> dict:
    """规则目录（含中文短名）：UI 的规则筛选器与"这是什么"图例从这里取。"""
    return {
        rid: {
            "label": rule.display_label,
            "severity": rule.severity,
            "description": rule.description,
        }
        for rid, rule in REGISTRY.items()
    }


def _after_check(resolver: LinkResolver, relpath: str, before: str, after: str) -> dict:
    """预览即验证：起草阶段就把修改后文本全量重解析，把"复扫断言"前置到预览。

    still_broken 可能含与本次无关的既有断链；regression 为空即"修改没有引入新断链"。
    """

    def _broken(text: str) -> set[str]:
        return {
            link.target_raw
            for link in extract_links(text)
            if resolver.resolve(relpath, link) is None
        }

    b_before, b_after = _broken(before), _broken(after)
    return {
        "ok": not (b_after - b_before),
        "fixed": sorted(b_before - b_after),
        "still_broken": sorted(b_after),
        "regression": sorted(b_after - b_before),
    }


def _why(vault: Path, rule_id: str, file: str, line: int | None) -> str:
    index_vault(vault)  # API 自洽：不假设调用方先扫过描
    conn = connect(default_db_path(vault))
    try:
        violations = run_rules(RuleContext(conn), [rule_id] if rule_id else None)
        candidates = [
            v for v in violations
            if v.file == file and (line is None or v.line == line)
        ]
        if not candidates:
            raise ApiError("未找到对应的违规（库可能已更新，请重新扫描）", 404)
        prompt = build_user_prompt(vault, candidates[0], conn)
    finally:
        conn.close()

    cfg = load_llm_config(None)
    client = make_client(cfg)
    try:
        content, _usage = client.chat(WHY_PROMPT, prompt)
    finally:
        client.close()
    return content


def _fix_draft(vault: Path, limit: int = 5) -> dict:
    index_vault(vault)  # API 自洽：不假设调用方先扫过描
    conn = connect(default_db_path(vault))
    try:
        violations = run_rules(RuleContext(conn), [UI_RULE])
        known = [row[0] for row in conn.execute("SELECT path FROM files")]
        known += [row[0] for row in conn.execute("SELECT path FROM assets")]
        known += [row[0] for row in conn.execute("SELECT path FROM others")]
        known += [row[0] for row in conn.execute("SELECT path FROM dirs")]
    finally:
        conn.close()
    resolver = LinkResolver(known)
    if not violations:
        return {"draft_id": None, "files": [], "usage": {}}

    by_file: dict[str, list] = {}
    for v in violations:
        by_file.setdefault(v.file, []).append(v)

    cfg = load_llm_config(None)
    client = make_client(cfg)
    transcript = Transcript(vault / ".vaultdoctor" / "transcripts" / f"{new_session_id()}.jsonl")
    ledger = TokenLedger(max_total_tokens=cfg.max_session_tokens, transcript=transcript)
    transcript.append({"type": "session_start", "command": "ui-fix", "vault": str(vault),
                       "version": __version__})

    files_payload: list[dict] = []
    all_patches = []
    usage: dict = {}
    try:
        for relpath, group in sorted(by_file.items())[:limit]:
            patches, u = draft_file_patches(client, vault, relpath, group, UI_RULE, ledger=ledger)
            merge_usage(usage, u)
            if not patches:
                continue
            before = (vault / relpath).read_text(encoding="utf-8", errors="replace")
            after = apply_to_text(before, patches)
            diff = "".join(difflib.unified_diff(
                before.splitlines(keepends=True), after.splitlines(keepends=True),
                fromfile=f"a/{relpath}", tofile=f"b/{relpath}",
            ))
            files_payload.append({
                "file": relpath,
                "count": len(patches),
                "rationale": patches[0].rationale,
                "violations": [
                    {
                        "line": v.line,
                        "target": v.detail.get("target_raw", ""),
                        "candidates": [
                            {"path": p, "distance": d}
                            for p, d in (v.detail.get("candidates") or [])[:3]
                        ],
                    }
                    for v in group
                ],
                "after_check": _after_check(resolver, relpath, before, after),
                "diff": diff,
            })
            all_patches.extend(patches)
    finally:
        client.close()

    draft_id = uuid.uuid4().hex[:10]
    with _DRAFTS_LOCK:
        _DRAFTS[draft_id] = {
            "vault": str(vault), "patches": all_patches,
            "usage": usage, "created": time.time(), "transcript": transcript,
        }
    return {"draft_id": draft_id, "files": files_payload, "usage": usage}


def _fix_apply(draft_id: str, approved_files: list[str]) -> dict:
    with _DRAFTS_LOCK:
        draft = _DRAFTS.get(draft_id)
    if draft is None:
        raise ApiError("起草会话不存在或已过期，请重新起草", 404)
    vault = _resolve_vault(draft["vault"])
    approved = set(approved_files)
    patches = [p for p in draft["patches"] if p.file in approved]
    if not patches:
        raise ApiError("没有已批准的文件")

    snapshot = create_snapshot(vault, sorted({p.file for p in patches}))
    result = apply_patches(vault, patches, write=True)

    transcript: Transcript = draft["transcript"]
    transcript.append({"type": "gate_decision", "decision": "ui-approved",
                       "files": sorted(approved)})
    transcript.append({"type": "applied", "files": [f.file for f in result.files if f.ok],
                       "snapshot": snapshot.session_id})

    # 复扫验证：只认我们修的那条链接（文件里其他无关断链不算我们的残留）
    index_vault(vault)
    conn = connect(default_db_path(vault))
    try:
        after = run_rules(RuleContext(conn), ["link/broken"])
    finally:
        conn.close()

    def _still_broken(p) -> bool:
        return any(
            v.file == p.file and v.detail.get("target_raw", "") in p.expected_old
            for v in after
        )

    remaining_files = sorted({p.file for p in patches if _still_broken(p)})
    cleared_files = sorted({p.file for p in patches} - set(remaining_files))
    report = {
        "applied_files": [f.file for f in result.files if f.ok],
        "failed": [{"file": f.file, "error": f.error} for f in result.files if not f.ok],
        "snapshot_id": snapshot.session_id,
        "cleared_files": cleared_files,
        "remaining_files": remaining_files,
        "usage": draft["usage"],
    }
    transcript.append({"type": "verify", "cleared": len(cleared_files),
                       "remaining": remaining_files})
    transcript.append({"type": "session_end",
                       "ok": not remaining_files and not report["failed"]})
    with _DRAFTS_LOCK:
        _DRAFTS.pop(draft_id, None)
    return report


class Handler(BaseHTTPRequestHandler):
    server_version = "vault-doctor-ui"

    def log_message(self, *args):  # 静音默认访问日志
        pass

    # ---- helpers ----
    def _send_json(self, obj, status: int = 200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ApiError("请求体为空")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError(f"请求体不是合法 JSON：{exc}")

    def _vault(self, raw=None) -> Path:
        return _resolve_vault(raw or getattr(self.server, "default_vault", "."))

    def _guard(self, fn):
        try:
            self._send_json(fn())
        except (ApiError, ConfigError, LLMError, SnapshotError, BudgetExceeded) as exc:
            status = getattr(exc, "status", 400)
            self._send_json({"error": str(exc)}, status)
        except OSError as exc:
            self._send_json({"error": str(exc)}, 500)

    # ---- routes ----
    def do_GET(self):
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            page = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")
            self._send_html(page.replace("{{VAULT}}", getattr(self.server, "default_vault", ".")))
            return
        if parsed.path == "/api/scan":
            qs = parse_qs(parsed.query)
            self._guard(lambda: _scan(self._vault(qs.get("vault", [None])[0])))
            return
        if parsed.path == "/api/rules":
            self._guard(_rules_payload)
            return
        if parsed.path == "/api/config":
            self._guard(_config_status)
            return
        if parsed.path == "/api/snapshots":
            qs = parse_qs(parsed.query)
            self._guard(lambda: {"snapshots": list(reversed(list_snapshots_detail(self._vault(qs.get("vault", [None])[0]))))})
            return
        self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        from urllib.parse import urlparse

        path = urlparse(self.path).path
        try:
            body = self._read_json()
        except ApiError as exc:
            self._send_json({"error": str(exc)}, exc.status)
            return

        if path == "/api/config":
            self._guard(lambda: _config_save(body))
            return
        if path == "/api/config/test":
            self._guard(lambda: _config_test(body))
            return
        if path == "/api/why":
            def run():
                vault = self._vault(body.get("vault"))
                return {"answer": _why(vault, body.get("rule_id", ""), body.get("file", ""), body.get("line"))}
            self._guard(run)
            return
        if path == "/api/fix/draft":
            def run():
                vault = self._vault(body.get("vault"))
                return _fix_draft(vault, int(body.get("limit", 5)))
            self._guard(run)
            return
        if path == "/api/fix/apply":
            self._guard(lambda: _fix_apply(body.get("draft_id", ""), body.get("approved", [])))
            return
        if path == "/api/rollback":
            def run():
                vault = self._vault(body.get("vault"))
                return {"restored": rollback(vault, body.get("session_id", ""))}
            self._guard(run)
            return
        self._send_json({"error": "not found"}, 404)


def serve(vault: Path, port: int = 8765, open_browser: bool = True) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.default_vault = str(vault)  # type: ignore[attr-defined]
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"vault-doctor {__version__} UI → {url}（Ctrl+C 退出）")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
    finally:
        httpd.server_close()
