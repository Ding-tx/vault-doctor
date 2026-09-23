"""MCP 只读图谱工具的纯引擎实现。

分层：本模块不 import mcp——纯函数、直接可测；mcp/server.py 懒加载 mcp SDK
把这里的函数包装成 MCP 工具。所有工具只读，唯一"写"是增量索引落到
.vaultdoctor/index.db（不碰任何笔记文件）。
"""
from __future__ import annotations

from pathlib import Path

from vault_doctor.engine.graph import links_of, near_miss, who_links_to
from vault_doctor.engine.indexer import connect, default_db_path, index_vault
from vault_doctor.engine.rules import run_rules
from vault_doctor.engine.rules.base import RuleContext


def _require_vault(vault) -> Path:
    v = Path(vault)
    if not v.is_dir():
        raise ValueError(f"路径不存在或不是目录：{v}")
    return v.resolve()


def scan_vault(vault, rule_id: str | None = None, limit: int = 0) -> dict:
    """全库体检（增量索引后跑规则）。返回 {notes, assets, elapsed, violation_count, violations}。

    rule_id 可选过滤，如 "link/broken"。大库建议先 limit=20 概览——violations
    只带前 N 条，violation_count 始终是全量数（limit<=0 不截断）。"""
    v = _require_vault(vault)
    stats = index_vault(v)
    conn = connect(default_db_path(v))
    try:
        notes = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        assets = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        violations = run_rules(RuleContext(conn), [rule_id] if rule_id else None)
    finally:
        conn.close()
    violations = [x.model_dump() for x in violations]
    total = len(violations)
    if limit > 0:
        violations = violations[:limit]
    return {
        "notes": notes,
        "assets": assets,
        "elapsed": round(stats.elapsed, 2),
        "violation_count": total,
        "violations": violations,
        "truncated": len(violations) < total,
    }


def outgoing_links(vault, path: str) -> list[dict]:
    """某笔记的全部出链：[{target_raw, target_resolved, line, kind}]。

    target_resolved 为 None 即断链（指向不存在的文件）。path 是库内相对路径
    （POSIX 风格，如 "数学/复习.md"）。"""
    v = _require_vault(vault)
    index_vault(v)
    conn = connect(default_db_path(v))
    try:
        rows = links_of(conn, path)
    finally:
        conn.close()
    return [
        {"target_raw": r[0], "target_resolved": r[1], "line": r[2], "kind": r[3]}
        for r in rows
    ]


def backlinks(vault, path: str) -> list[dict]:
    """谁链接到某文件（反向链接）：[{source, line, kind}]，按来源排序。"""
    v = _require_vault(vault)
    index_vault(v)
    conn = connect(default_db_path(v))
    try:
        rows = who_links_to(conn, path)
    finally:
        conn.close()
    return [{"source": r[0], "line": r[1], "kind": r[2]} for r in rows]


def near_miss_candidates(vault, target: str) -> list[dict]:
    """断链目标的改名候选：[{path, distance}]，按距离升序。

    distance 是文件名编辑距离（≤2 才算候选）。target 传链接原文，如
    "概率论笔记"。"""
    v = _require_vault(vault)
    index_vault(v)
    conn = connect(default_db_path(v))
    try:
        rows = near_miss(conn, target)
    finally:
        conn.close()
    return [{"path": p, "distance": d} for p, d in rows]


def search_notes(vault, query: str, limit: int = 10) -> list[dict]:
    """全文检索（FTS5 trigram，支持中文子串）：[{path, title, snippet}]。

    query 至少 3 个字符（trigram 分词下限），否则返回空。"""
    v = _require_vault(vault)
    query = query.strip()
    if len(query) < 3:
        return []
    index_vault(v)
    # 引号包裹防止用户输入被解释成 FTS 查询语法；参数绑定防注入
    match = '"' + query.replace('"', '""') + '"'
    conn = connect(default_db_path(v))
    try:
        rows = conn.execute(
            "SELECT content.path, files.title, content.body FROM content "
            "JOIN files ON files.path = content.path "
            "WHERE content MATCH ? LIMIT ?",
            (match, max(1, min(limit, 50))),
        ).fetchall()
    finally:
        conn.close()
    results = []
    for path, title, body in rows:
        at = body.find(query)
        lo = max(0, at - 30) if at >= 0 else 0
        results.append({"path": path, "title": title, "snippet": body[lo : lo + 120]})
    return results
