"""MCP stdio 全链路冒烟测试：用官方 SDK 客户端拉起 vault-doctor mcp server。

比 `vault-doctor mcp --check` 更强：--check 只构造 server 对象，本脚本走完
真实客户端的完整协议（spawn → initialize 握手 → list_tools → call_tool）。
脚本通过 = 任何合规 MCP 客户端都能连上；脚本失败 = server 端还有问题。

用法（vault_doctor 环境）：
  python scripts/mcp_smoke.py <vault路径> [vault-doctor可执行文件路径]

  python scripts/mcp_smoke.py E:\\Typora_projects
  python scripts/mcp_smoke.py E:\\Typora_projects E:\\study\\Anaconda2024\\envs\\vault_doctor\\Scripts\\vault-doctor.exe
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


async def main() -> int:
    vault = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    exe = sys.argv[2] if len(sys.argv) > 2 else "vault-doctor"
    if not vault.is_dir():
        print(f"错误：路径不存在：{vault}")
        return 2

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=exe, args=["mcp", str(vault)])
    print(f"连接：{exe} mcp {vault} …")
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"✓ 握手成功：server = {init.serverInfo.name}")

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"✓ 列出 {len(names)} 个工具：{'、'.join(names)}")

            result = await session.call_tool("scan_vault", {"rule_id": "link/near-miss"})
            text = getattr(result.content[0], "text", "") if result.content else ""
            data = json.loads(text)
            print(f"✓ 调用 scan_vault(link/near-miss)：{data['notes']} 篇笔记，"
                  f"{len(data['violations'])} 条疑似改名违规")
            print("\n全链路通过——server 侧无问题；若 GUI 客户端仍连不上，问题在客户端配置。")
            return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001 冒烟脚本要把错误打出来给人看
        print(f"✗ 失败：{type(exc).__name__}: {exc}")
        sys.exit(1)
