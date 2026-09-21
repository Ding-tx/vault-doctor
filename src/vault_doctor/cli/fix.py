"""fix 子命令（M2-C）：起草 → 闸门 → 应用 → 复扫验证。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.markup import escape

from vault_doctor.agent.fixer import SUPPORTED_RULES, run_fix
from vault_doctor.config import ConfigError, load_llm_config
from vault_doctor.llm.client import LLMClient, LLMError


def cmd_fix(args: argparse.Namespace) -> int:
    console = Console()
    vault = Path(args.vault)
    if not vault.is_dir():
        print(f"错误：路径不存在或不是目录：{vault}", file=sys.stderr)
        return 2
    if args.rule not in SUPPORTED_RULES:
        print(f"错误：M2-C 仅支持 {sorted(SUPPORTED_RULES)}", file=sys.stderr)
        return 2

    try:
        cfg = load_llm_config(Path(args.config) if args.config else None)
        client = LLMClient(cfg)
    except (ConfigError, LLMError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    try:
        report = run_fix(
            vault,
            client,
            rule=args.rule,
            limit=args.limit,
            assume_yes=args.yes,
            console=console,
        )
    except LLMError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    finally:
        client.close()

    if report.before == 0:
        console.print("[green]没有可修复的违规[/green]")
        return 0

    console.print(
        f"\n[bold]vault-doctor fix[/bold] · 处理 {report.files_attempted} 个文件 · "
        f"起草 {report.patches_drafted} 补丁 · 应用 {len(report.applied_files)} 文件"
    )
    if report.snapshot_id:
        console.print(f"快照 [bold]{report.snapshot_id}[/bold]（回滚：vault-doctor rollback {report.snapshot_id} \"{vault}\"）")
    console.print(
        f"违规：{report.before} → 残留 {report.remaining}（清除 {report.cleared}）"
    )
    for file, target in report.remaining_pairs:
        console.print(f"  [yellow]残留[/yellow] {escape(file)} · {escape(target)}")
    if report.usage:
        console.print(
            f"[dim]tokens: {report.usage.get('prompt_tokens', '?')} 输入 + "
            f"{report.usage.get('completion_tokens', '?')} 输出[/dim]"
        )
    return 0
