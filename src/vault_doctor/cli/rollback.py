"""snapshots / rollback 子命令：查看与回滚修复快照。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

from vault_doctor.policy.snapshot import SnapshotError, list_snapshots_detail, rollback


def cmd_snapshots(args: argparse.Namespace) -> int:
    console = Console()
    vault = Path(args.vault)
    if not vault.is_dir():
        print(f"错误：路径不存在或不是目录：{vault}", file=sys.stderr)
        return 2
    detail = list_snapshots_detail(vault)
    if not detail:
        console.print("暂无快照")
        return 0
    console.print(f"[bold]vault-doctor[/bold] · {len(detail)} 个快照（新→旧）")
    for snap in reversed(detail):
        files = snap["files"]
        preview = "、".join(files[:3]) + (f" 等 {len(files)} 个文件" if len(files) > 3 else "")
        console.print(
            f"  [cyan]{snap['session_id']}[/cyan]  {snap['created_at']}\n"
            f"      改动文件：{preview or '（无）'}\n"
            f"      回滚：vault-doctor rollback {snap['session_id']} \"{vault}\""
        )
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    console = Console()
    vault = Path(args.vault)
    if not vault.is_dir():
        print(f"错误：路径不存在或不是目录：{vault}", file=sys.stderr)
        return 2
    try:
        restored = rollback(vault, args.session_id)
    except SnapshotError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    console.print(f"[green]已回滚 {len(restored)} 个文件[/green]（快照 {args.session_id} 保留，可审计）")
    for relpath in restored:
        console.print(f"  {relpath}")
    return 0
