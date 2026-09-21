"""fix/ui 子命令之外的 UI 启动入口。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def cmd_ui(args: argparse.Namespace) -> int:
    vault = Path(args.vault)
    if not vault.is_dir():
        print(f"错误：路径不存在或不是目录：{vault}", file=sys.stderr)
        return 2
    from vault_doctor.ui.server import serve

    serve(vault.resolve(), port=args.port, open_browser=not args.no_open)
    return 0
