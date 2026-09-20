"""B2 链接图测试：语法解析、解析目标、图谱查询、near-miss、更新刷新。"""
from pathlib import Path

from engine.graph import extract_links, links_of, near_miss, who_links_to
from engine.indexer import connect, default_db_path, index_vault


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_extract_links_syntaxes():
    text = (
        "# 标题\n"
        "[[普通链]]\n"
        "[[带别名|显示名]]\n"
        "[[带标题#章节]]\n"
        "![[嵌入图]]\n"
        "[md相对](./b.md)\n"
        "[md锚点](../c.md#sec)\n"
        "![](img/pic.png)\n"
        "[外链](https://example.com/page)\n"
        "[纯锚点](#本节)\n"
        "`[[代码里的链]]`\n"
        "```\n[[围栏里的链]]\n```\n"
    )
    links = extract_links(text)
    got = {(l.target_raw, l.kind) for l in links}
    assert ("普通链", "wikilink") in got
    assert ("带别名", "wikilink") in got
    assert ("带标题", "wikilink") in got
    assert ("嵌入图", "wikilink-embed") in got
    assert ("./b.md", "md") in got
    assert ("../c.md", "md") in got
    assert ("img/pic.png", "md-embed") in got
    # 外链、纯锚点、代码块与行内代码中的链接一律不收
    assert all("example.com" not in t for t, _ in got)
    assert all(t not in {"代码里的链", "围栏里的链"} for t, _ in got)
    # 行号保真：普通链在第 2 行
    assert any(l.target_raw == "普通链" and l.line == 2 for l in links)


def test_resolution_backlinks_and_near_miss(tmp_path: Path):
    _write(tmp_path / "数学" / "线性代数.md", "# 线\n[[高等数学]]\n[[线性代数2]]\n[同目录](./笔记.md)\n![](图.png)\n")
    _write(tmp_path / "数学" / "高等数学.md", "# 高\n")
    _write(tmp_path / "数学" / "笔记.md", "# 笔\n")
    _write(tmp_path / "数学" / "图.png", "png")
    index_vault(tmp_path)

    conn = connect(default_db_path(tmp_path))

    # 中文文件名的 wikilink 按文件名解析成功
    assert who_links_to(conn, "数学/高等数学.md") == [("数学/线性代数.md", 2, "wikilink")]
    # md 相对路径与资产（图.png）解析成功；断链 target_resolved 为 NULL
    resolved = {row[0]: row[1] for row in links_of(conn, "数学/线性代数.md")}
    assert resolved["./笔记.md"] == "数学/笔记.md"
    assert resolved["图.png"] == "数学/图.png"
    assert resolved["线性代数2"] is None
    # near-miss：断链目标与现有文件名距离 1
    assert near_miss(conn, "线性代数2") == [("数学/线性代数.md", 1)]


def test_parent_relative_and_case_insensitive(tmp_path: Path):
    _write(tmp_path / "Math.md", "# m\n[[deep]]\n")
    _write(tmp_path / "notes" / "sub" / "子笔记.md", "# 子\n[上级](../Deep.md)\n")
    _write(tmp_path / "notes" / "Deep.md", "# d\n")
    index_vault(tmp_path)

    conn = connect(default_db_path(tmp_path))
    # 大小写不敏感：[[deep]] 命中 Math 同 stem 的 Deep（取唯一 stem 匹配）
    resolved1 = {row[0]: row[1] for row in links_of(conn, "Math.md")}
    assert resolved1["deep"] == "notes/Deep.md"
    # ../ 相对路径从 notes/sub 回溯到 notes/
    resolved2 = {row[0]: row[1] for row in links_of(conn, "notes/sub/子笔记.md")}
    assert resolved2["../Deep.md"] == "notes/Deep.md"


def test_links_refresh_on_update(tmp_path: Path):
    _write(tmp_path / "a.md", "# a\n[[旧目标]]\n")
    _write(tmp_path / "旧目标.md", "# o\n")
    _write(tmp_path / "新目标.md", "# n\n")
    index_vault(tmp_path)

    _write(tmp_path / "a.md", "# a\n[[新目标]]\n")
    index_vault(tmp_path)

    conn = connect(default_db_path(tmp_path))
    targets = [row[0] for row in links_of(conn, "a.md")]
    assert targets == ["新目标"]
    assert who_links_to(conn, "旧目标.md") == []
    assert who_links_to(conn, "新目标.md") == [("a.md", 2, "wikilink")]
