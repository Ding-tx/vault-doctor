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
        from vault_doctor.mcp.server import build_server
    except ImportError as exc:
        print(f'加载 server 模块失败：{exc}', file=sys.stderr)
        return 2
    try:
        srv = build_server(vault)
    except ImportError as exc:
        # mcp SDK 未安装（可选依赖）；附原始错误便于区分"没装"与"装错版本"
        print(
            f'未安装 MCP SDK（{exc}）。安装：pip install "vault-doctor[mcp]"',
            file=sys.stderr,
        )
        return 2

    if args.check:  # 自检：不动 MCP 客户端，直接列工具
        import asyncio

        tools = asyncio.run(srv.list_tools())
        print(f"✓ MCP server 自检通过：{len(tools)} 个工具就绪（{'、'.join(t.name for t in tools)}）")
        return 0

    srv.run(transport="stdio")  # 阻塞在 stdio 循环
    return 0
