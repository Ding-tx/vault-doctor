"""B1 索引器冒烟测试：首次索引、增量、更新/删除、隐藏目录忽略、中文检索。"""
from pathlib import Path

from engine.indexer import connect, default_db_path, index_vault


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_vault(root: Path) -> None:
    _write(root / "a.md", "# A 标题\n\nhello world\n")
    _write(root / "notes" / "中文笔记.md", "---\ntitle: 测试\n---\n# 壳标题\n正文内容在这里\n")
    _write(root / ".obsidian" / "app.json", "{}")  # 隐藏目录，应被忽略
    _write(root / "notes" / "draft.md", "没有一级标题的草稿\n")


def test_first_index_adds_and_skips_hidden(tmp_path: Path):
    _make_vault(tmp_path)
    stats = index_vault(tmp_path)
    assert (stats.added, stats.updated, stats.removed) == (3, 0, 0)

    conn = connect(default_db_path(tmp_path))
    rows = dict(conn.execute("SELECT path, title FROM files").fetchall())
    assert set(rows) == {"a.md", "notes/中文笔记.md", "notes/draft.md"}
    assert rows["a.md"] == "A 标题"
    # 无一级标题时回退为文件名
    assert rows["notes/draft.md"] == "draft"


def test_frontmatter_and_chinese_fts(tmp_path: Path):
    _make_vault(tmp_path)
    index_vault(tmp_path)

    conn = connect(default_db_path(tmp_path))
    fm = conn.execute(
        "SELECT frontmatter FROM files WHERE path = 'notes/中文笔记.md'"
    ).fetchone()[0]
    assert fm == "title: 测试"

    # trigram 分词下中文子串检索可用（这是 FTS5 默认分词器做不到的）
    hits = conn.execute(
        "SELECT path FROM content WHERE content MATCH ?", ("正文内容",)
    ).fetchall()
    assert hits == [("notes/中文笔记.md",)]


def test_second_run_is_incremental(tmp_path: Path):
    _make_vault(tmp_path)
    index_vault(tmp_path)
    stats = index_vault(tmp_path)
    assert (stats.added, stats.updated, stats.unchanged, stats.removed) == (0, 0, 3, 0)


def test_update_and_removal(tmp_path: Path):
    _make_vault(tmp_path)
    index_vault(tmp_path)

    _write(tmp_path / "a.md", "# 改过的标题\n全新正文内容 here\n")
    (tmp_path / "notes" / "draft.md").unlink()

    stats = index_vault(tmp_path)
    assert (stats.added, stats.updated, stats.removed) == (0, 1, 1)

    conn = connect(default_db_path(tmp_path))
    paths = {row[0] for row in conn.execute("SELECT path FROM files")}
    assert paths == {"a.md", "notes/中文笔记.md"}
    title = conn.execute("SELECT title FROM files WHERE path = 'a.md'").fetchone()[0]
    assert title == "改过的标题"
    stale = conn.execute(
        "SELECT path FROM content WHERE path = 'notes/draft.md'"
    ).fetchall()
    assert stale == []
