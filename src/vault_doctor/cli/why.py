"""why 子命令：选一条违规，调一次 LLM，把它翻译成人话——agent 内核的第一次点火。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.markup import escape

from vault_doctor.config import ConfigError, load_llm_config
from vault_doctor.engine.graph import who_links_to
from vault_doctor.engine.indexer import connect, default_db_path, index_vault
from vault_doctor.engine.rules import run_rules
from vault_doctor.engine.rules.base import RuleContext, Violation
from vault_doctor.llm.client import LLMClient, LLMError

SYSTEM_PROMPT = (
    "你是 vault-doctor（markdown 知识库体检工具）的违规解释器。"
    "根据用户给出的上下文，用不超过 150 字的中文解释：1) 这条违规是什么；"
    "2) 最可能的成因；3) 建议的处理方式。信息不足就明说，不要编造。"
    "你只做解释，绝不建议由工具直接改动用户文件。"
)


def _excerpt(vault: Path, relpath: str, line: int | None, context: int = 5) -> str:
    try:
        text = (vault / relpath).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return f"（无法读取 {relpath}）"
    lines = text.splitlines()
    if line is None:
        window, start = lines[:10], 1
    else:
        start = max(1, line - context)
        window = lines[start - 1 : line + context]
    return "\n".join(f"{start + i:>4} | {text}" for i, text in enumerate(window))


def build_user_prompt(vault: Path, v: Violation, conn) -> str:
    parts = [
        f"违规：[{v.severity}] {v.rule_id}",
        f"位置：{v.file}" + (f":{v.line}" if v.line else ""),
        f"说明：{v.message}",
    ]
    if v.detail.get("candidates"):
        cands = ", ".join(f"{p}（距离 {d}）" for p, d in v.detail["candidates"][:3])
        parts.append(f"改名候选：{cands}")
    backlinks = who_links_to(conn, v.file)
    if backlinks:
        parts.append("反向链接：" + ", ".join(f"{s}:{ln}" for s, ln, _kind in backlinks[:5]))
    parts.append(f"文件节选（{v.file}）：\n{_excerpt(vault, v.file, v.line)}")
    return "\n".join(parts)


def explain(vault: Path, v: Violation, client) -> tuple[str, dict]:
    conn = connect(default_db_path(vault))
    try:
        user_prompt = build_user_prompt(vault, v, conn)
    finally:
        conn.close()
    return client.chat(SYSTEM_PROMPT, user_prompt)


def cmd_why(args: argparse.Namespace) -> int:
    console = Console()
    vault = Path(args.vault)
    if not vault.is_dir():
        print(f"错误：路径不存在或不是目录：{vault}", file=sys.stderr)
        return 2

    index_vault(vault)
    conn = connect(default_db_path(vault))
    try:
        rule_ids = [args.rule] if args.rule else None
        try:
            violations = run_rules(RuleContext(conn), rule_ids)
        except KeyError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2
    finally:
        conn.close()

    if not violations:
        console.print("[green]未发现违规，无需解释[/green]")
        return 0

    idx = args.index if args.index is not None else 1
    if not 1 <= idx <= len(violations):
        print(f"错误：--index 超出范围（1..{len(violations)}）", file=sys.stderr)
        return 2
    v = violations[idx - 1]

    location = f"{v.file}:{v.line}" if v.line else v.file
    console.print(
        f"[bold]vault-doctor why[/bold] · 第 {idx}/{len(violations)} 条 · "
        f"{escape(v.rule_id)} · {escape(location)}"
    )

    try:
        cfg = load_llm_config(Path(args.config) if args.config else None)
        client = LLMClient(cfg)
    except (ConfigError, LLMError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    import vault_doctor
    from vault_doctor.kernel.transcript import Transcript, new_session_id
    from vault_doctor.ledger.budget import BudgetExceeded, TokenLedger

    transcript = Transcript(vault / ".vaultdoctor" / "transcripts" / f"{new_session_id()}.jsonl")
    ledger = TokenLedger(max_total_tokens=cfg.max_session_tokens, transcript=transcript)
    transcript.append(
        {"type": "session_start", "command": "why", "vault": str(vault),
         "version": vault_doctor.__version__}
    )

    try:
        answer, usage = explain(vault, v, client)
        ledger.record(usage, purpose="explain", file=v.file, line=v.line)
    except LLMError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except BudgetExceeded as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    finally:
        client.close()

    console.print(answer)
    if usage:
        console.print(
            f"[dim]模型 {cfg.model} · tokens: "
            f"{usage.get('prompt_tokens', '?')} 输入 + {usage.get('completion_tokens', '?')} 输出[/dim]"
        )
    console.print(f"[dim]会话转录：{transcript.path}[/dim]")
    transcript.append({"type": "session_end", "ok": True})
    return 0
