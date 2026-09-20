"""vault-doctor 索引器：把 markdown 库的元数据与全文索引进 SQLite。

设计依据 DESIGN.md 6.2 / 10：
- 单文件 SQLite：files 元数据 + FTS5 全文（trigram 分词，支持中文子串检索，
  规避 FTS5 默认 unicode61 对无空格语言失效的问题）+ links 表（B2 写入）
- 增量更新：以 (mtime, size) 指纹判断变更，二次索引只碰变化过的文件
- 全链路 UTF-8：坏字节以 U+FFFD 替换而不是让索引崩溃
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = "1"

# 非点号前缀的忽略目录（点号开头的隐藏目录一律跳过）
SKIP_DIRS = {"node_modules"}

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)
_TITLE_RE = re.compile(r"^#[ \t]+(.+?)\s*$", re.MULTILINE)

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    title TEXT,
    frontmatter TEXT,
    indexed_at REAL NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS content USING fts5(path UNINDEXED, body, tokenize='trigram');
CREATE TABLE IF NOT EXISTS links(
    source TEXT NOT NULL,
    target_raw TEXT NOT NULL,
    line INTEGER NOT NULL,
    kind TEXT,
    PRIMARY KEY(source, target_raw, line)
);
CREATE INDEX IF NOT EXISTS idx_links_source ON links(source);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


@dataclass
class IndexStats:
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    elapsed: float = 0.0


def default_db_path(vault: Path) -> Path:
    return vault / ".vaultdoctor" / "index.db"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def iter_markdown_files(vault: Path):
    for dirpath, dirnames, filenames in os.walk(vault):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
        for name in filenames:
            if name.lower().endswith(".md"):
                yield Path(dirpath) / name


def extract_frontmatter(text: str) -> str | None:
    m = _FRONTMATTER_RE.match(text)
    return m.group(1).strip() if m else None


def extract_title(text: str, relpath: str) -> str:
    m = _TITLE_RE.search(text)
    return m.group(1).strip() if m else Path(relpath).stem


def index_vault(vault: Path, db_path: Path | None = None) -> IndexStats:
    vault = vault.resolve()
    db_path = (db_path or default_db_path(vault)).resolve()
    stats = IndexStats()
    start = time.perf_counter()

    conn = connect(db_path)
    try:
        existing = {
            row[0]: (row[1], row[2])
            for row in conn.execute("SELECT path, mtime, size FROM files")
        }
        seen: set[str] = set()

        for filepath in iter_markdown_files(vault):
            relpath = filepath.relative_to(vault).as_posix()
            seen.add(relpath)
            st = filepath.stat()
            fingerprint = (st.st_mtime, st.st_size)

            if relpath not in existing:
                action = "add"
            elif existing[relpath] != fingerprint:
                action = "update"
            else:
                stats.unchanged += 1
                continue

            text = filepath.read_text(encoding="utf-8", errors="replace")
            conn.execute("DELETE FROM files WHERE path = ?", (relpath,))
            conn.execute(
                """INSERT INTO files(path, mtime, size, title, frontmatter, indexed_at)
                   VALUES(?,?,?,?,?,?)""",
                (
                    relpath,
                    st.st_mtime,
                    st.st_size,
                    extract_title(text, relpath),
                    extract_frontmatter(text),
                    time.time(),
                ),
            )
            conn.execute("DELETE FROM content WHERE path = ?", (relpath,))
            conn.execute("INSERT INTO content(path, body) VALUES(?,?)", (relpath, text))

            if action == "add":
                stats.added += 1
            else:
                stats.updated += 1

        for relpath in set(existing) - seen:
            conn.execute("DELETE FROM files WHERE path = ?", (relpath,))
            conn.execute("DELETE FROM content WHERE path = ?", (relpath,))
            conn.execute("DELETE FROM links WHERE source = ?", (relpath,))
            stats.removed += 1

        conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (SCHEMA_VERSION,),
        )
        conn.commit()
    finally:
        conn.close()

    stats.elapsed = time.perf_counter() - start
    return stats
