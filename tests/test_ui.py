"""UI 层测试：HTTP API、修复起草/应用闭环（假客户端）、错误路径。"""
import http.client
import json
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from vault_doctor.config import ConfigError, LLMConfig
from vault_doctor.ui import server as ui
from tests.fixtures import build_vault
from tests.test_fixer import DispatchClient


def _get(port: int, path: str) -> tuple[int, str]:
    """SSRF 防线：只连本机回环——主机是字面量，端口来自本地测试服务器，路径为静态字符串。"""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8")
    finally:
        conn.close()


@contextmanager
def _served(vault_dir: Path):
    build_vault(vault_dir)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ui.Handler)
    httpd.default_vault = str(vault_dir)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[1]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_scan_and_index(tmp_path: Path):
    with _served(tmp_path) as port:
        status, body = _get(port, "/api/scan")
        assert status == 200
        data = json.loads(body)
        assert data["notes"] == 26
        assert len(data["violations"]) == 17

        status, html = _get(port, "/")
        assert status == 200
        assert "vault-doctor" in html
        assert str(tmp_path) in html  # {{VAULT}} 占位被注入默认库路径


def test_http_rules_catalog(tmp_path: Path):
    """规则目录：中文短名 + 严重度 + 一句话说明（UI 图例与筛选器的数据源）。"""
    with _served(tmp_path) as port:
        status, body = _get(port, "/api/rules")
        assert status == 200
        rules = json.loads(body)
        assert rules["link/broken"]["label"] == "断链"
        assert rules["link/broken"]["severity"] == "error"
        assert rules["link/broken"]["description"]
        assert rules["link/near-miss"]["label"] == "疑似改名"


def test_http_snapshots_detail(tmp_path: Path):
    """快照列表带创建时间与文件清单——不再是盲盒 session id。"""
    from vault_doctor.policy.snapshot import create_snapshot

    with _served(tmp_path) as port:
        snap = create_snapshot(tmp_path, ["计算机/学习计划.md"])
        status, body = _get(port, "/api/snapshots")
        assert status == 200
        data = json.loads(body)
        assert data["snapshots"][0]["session_id"] == snap.session_id  # 新→旧
        assert data["snapshots"][0]["created_at"]
        assert "计算机/学习计划.md" in data["snapshots"][0]["files"]


def test_fix_draft_apply_flow_with_fake_client(tmp_path: Path, monkeypatch):
    build_vault(tmp_path)
    monkeypatch.setattr(ui, "make_client", lambda cfg: DispatchClient())
    monkeypatch.setattr(ui, "load_llm_config", lambda path=None: LLMConfig(api_key="sk-test"))

    draft = ui._fix_draft(tmp_path)
    assert draft["draft_id"]
    assert len(draft["files"]) == 3
    assert any("[[算法导论]]" in f["diff"] for f in draft["files"])

    # 起草载荷自带"为什么改"与"预览即验证"（用户不需要懂规则 id 也能决策）
    study = next(f for f in draft["files"] if f["file"] == "计算机/学习计划.md")
    assert study["violations"][0]["target"] == "算法导论2"
    assert study["violations"][0]["candidates"][0]["path"] == "计算机/算法导论.md"
    assert study["after_check"]["ok"] is True
    assert "算法导论2" in study["after_check"]["fixed"]
    assert study["after_check"]["regression"] == []

    report = ui._fix_apply(draft["draft_id"], [f["file"] for f in draft["files"]])
    assert len(report["applied_files"]) == 3
    assert report["cleared_files"] and not report["remaining_files"]
    assert "[[算法导论]]" in (tmp_path / "计算机" / "学习计划.md").read_text(encoding="utf-8")

    # 起草会话一次性：应用后失效
    with pytest.raises(ui.ApiError):
        ui._fix_apply(draft["draft_id"], ["计算机/学习计划.md"])


def test_fix_apply_unknown_draft_raises_404():
    with pytest.raises(ui.ApiError, match="起草会话"):
        ui._fix_apply("不存在的id", ["a.md"])


def test_why_without_config_raises(tmp_path: Path, monkeypatch):
    build_vault(tmp_path)
    monkeypatch.delenv("VAULT_DOCTOR_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # cwd 无 config.local.toml
    with pytest.raises(ConfigError):
        ui._why(tmp_path, "link/near-miss", "计算机/学习计划.md", 3)
