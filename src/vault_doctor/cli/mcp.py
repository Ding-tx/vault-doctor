"""mcp 子命令：以 MCP server 运行（stdio，只读图谱工具）。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def cmd_mcp(args: argparse.Namespace) -> int:
    vault = Path(args.vault)
    if not vault.is_dir():
        print(f"错误：路径不存在或不是目录：{vault}", file=sys.stderr)
        return 2
    try:
        from vault_doctor.mcp.server import serve
    except ImportError:
        print(
            "未安装 MCP 依赖。安装：pip install \"vault-doctor[mcp]\"（或 pip install mcp）",
            file=sys.stderr,
        )
        return 2
    serve(vault)  # 阻塞在 stdio 循环
    return 0
