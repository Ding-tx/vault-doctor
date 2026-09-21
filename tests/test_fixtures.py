"""B3 验收：fixtures 病态库的引擎级基准真值（B4 规则将复用同一期望）。"""
from pathlib import Path

from vault_doctor.engine.graph import links_of, near_miss, who_links_to
from vault_doctor.engine.indexer import connect, default_db_path, index_vault
from tests.fixtures import (
    ASSETS,
    NOTES,
    EXPECTED_BROKEN,
    EXPECTED_ORPHANS,
    EXPECTED_UNREFERENCED_ASSETS,
    build_vault,
)


def _all_notes(conn) -> list[str]:
    return [row[0] for row in conn.execute("SELECT path FROM files")]


def test_fixture_vault_ground_truth(tmp_path: Path):
    build_vault(tmp_path)
    stats = index_vault(tmp_path)
    conn = connect(default_db_path(tmp_path))

    # 规模与资产清点
    assert stats.added == len(NOTES) == 26
    assert {row[0] for row in conn.execute("SELECT path FROM assets")} == set(ASSETS)

    # 断链集合精确匹配；代码块/行内代码中的"链接"不得混入
    broken = set()
    for note in _all_notes(conn):
        for target_raw, resolved, _line, _kind in links_of(conn, note):
            if resolved is None:
                broken.add((note, target_raw))
    assert broken == EXPECTED_BROKEN

    # near-miss 三层断言：距离 1、距离 2、日期打错的三候选
    # （17→18、17→19 各差一次替换 d=1；17→20 差两次替换 d=2）
    assert near_miss(conn, "算法导论2")[0] == ("计算机/算法导论.md", 1)
    assert ("数学/概率论.md", 2) in near_miss(conn, "概率论笔记")
    assert near_miss(conn, "daily/2026-09-17") == [
        ("daily/2026-09-18.md", 1),
        ("daily/2026-09-19.md", 1),
        ("daily/2026-09-20.md", 2),
    ]

    # 孤儿：无入链且无出链
    orphans = {
        note for note in _all_notes(conn)
        if not links_of(conn, note) and not who_links_to(conn, note)
    }
    assert orphans == EXPECTED_ORPHANS

    # 资产引用：期望的未引用集合 + 控制组（diagram.png 被引用）
    unreferenced = {
        path
        for (path,) in conn.execute("SELECT path FROM assets")
        if not who_links_to(conn, path)
    }
    assert unreferenced == EXPECTED_UNREFERENCED_ASSETS
    assert who_links_to(conn, "assets/diagram.png") != []

    # 控制组：健康链接确实解析成功（抽查明文 md 与 wikilink）
    resolved_map = {row[0]: row[1] for row in links_of(conn, "项目/周报-0920.md")}
    assert resolved_map["../计算机/算法导论.md"] == "计算机/算法导论.md"
    assert who_links_to(conn, "index.md")[0][0] == "README.md"
