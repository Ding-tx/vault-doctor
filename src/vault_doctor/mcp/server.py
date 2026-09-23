"""MCP server（DESIGN 6.5）：把只读图谱工具暴露给 Claude Code / Cursor 等 agent。

分层：tools.py 是纯引擎函数（无 mcp 依赖，直接可测）；本模块懒加载 mcp SDK
（可选依赖 vault-doctor[mcp]）。stdio 传输，只读工具，不暴露任何写路径——
外层 harness 自有权限系统，写操作默认禁用。

SDK 版本兼容：1.x 是 FastMCP，2.x 改名为 MCPServer（导入路径与类名都变了，
@tool 装饰器与 run(transport="stdio") 保持一致）——两条路径都支持。
"""
from __future__ import annotations

from pathlib import Path

from vault_doctor.mcp import tools as T

_INSTRUCTIONS = (
    "vault-doctor：markdown 知识库的只读图谱工具。可用工具：scan_vault 全库体检"
    "（断链/疑似改名/孤儿笔记/未引用附件）；outgoing_links / backlinks 查看链接关系；"
    "near_miss_candidates 找改名候选；search_notes 全文检索（支持中文）。"
    "本 server 只读，不提供修改文件的工具。"
)


def _server_class():
    try:
        from mcp.server.fastmcp import FastMCP  # SDK 1.x

        return FastMCP
    except ImportError:
        from mcp.server.mcpserver import MCPServer  # SDK 2.x：FastMCP 改名

        return MCPServer


def build_server(vault: Path):
    """构造 MCP server（注入 vault 路径，工具闭包持有）。--check 自检与测试共用。"""
    cls = _server_class()
    try:
        mcp = cls("vault-doctor", instructions=_INSTRUCTIONS)
    except TypeError:
        mcp = cls("vault-doctor")  # 构造签名变化时的兜底

    @mcp.tool()
    def scan_vault(rule_id: str = "") -> dict:
        """全库体检：返回笔记数、附件数与违规清单（断链/疑似改名/孤儿笔记/未引用附件）。
        rule_id 可选过滤，如 "link/broken"。"""
        return T.scan_vault(vault, rule_id or None)

    @mcp.tool()
    def outgoing_links(path: str) -> list[dict]:
        """某笔记的全部出链。target_resolved 为 null 即断链。path 为库内相对路径，如 "数学/复习.md"。"""
        return T.outgoing_links(vault, path)

    @mcp.tool()
    def backlinks(path: str) -> list[dict]:
        """反向链接：谁链接到某文件（笔记或附件路径）。"""
        return T.backlinks(vault, path)

    @mcp.tool()
    def near_miss_candidates(target: str) -> list[dict]:
        """断链目标的改名候选（文件名编辑距离 ≤ 2 的现有文件），按距离升序。"""
        return T.near_miss_candidates(vault, target)

    @mcp.tool()
    def search_notes(query: str, limit: int = 10) -> list[dict]:
        """全文检索笔记（支持中文子串），返回路径、标题与片段。query 至少 3 个字符。"""
        return T.search_notes(vault, query, limit)

    return mcp


def serve(vault: Path) -> None:
    """启动 stdio MCP server（阻塞，供 MCP 客户端拉起）。"""
    build_server(vault).run(transport="stdio")
