"""snapshots / rollback 子命令：查看与回滚修复快照。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

from vault_doctor.policy.snapshot import SnapshotError, list_snapshots, rollback


def cmd_snapshots(args: argparse.Namespace) -> int:
    console = Console()
    vault = Path(args.vault)
    if not vault.is_dir():
        print(f"错误：路径不存在或不是目录：{vault}", file=sys.stderr)
        return 2
    sessions = list_snapshots(vault)
    if not sessions:
        console.print("暂无快照")
        return 0
    console.print(f"[bold]vault-doctor[/bold] · {len(sessions)} 个快照（新→旧）")
    for sid in reversed(sessions):
        console.print(f"  {sid}    回滚：vault-doctor rollback {sid} \"{vault}\"")
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
