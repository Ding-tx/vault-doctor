"""vault-doctor 索引器：把 markdown 库的元数据、全文与链接图索引进 SQLite。

设计依据 DESIGN.md 6.2 / 10：
- 单文件 SQLite：files 笔记元数据 + assets 非笔记资产 + FTS5 全文
  （trigram 分词，支持中文子串检索，规避 FTS5 默认分词器对中文失效）+ links 链接图
- 增量更新：以 (mtime, size) 指纹判断变更；链接重解析只发生在变化的文件上
- 两遍式：先索引全部文件得到完整已知路径集，再统一解析链接，
  避免文件遍历顺序影响解析结果
- 全链路 UTF-8：坏字节以 U+FFFD 替换而不是让索引崩溃
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from engine.graph import LinkResolver, extract_links

SCHEMA_VERSION = "2"

SKIP_DIRS = {"node_modules", "__pycache__", "venv", "dist", "build"}

# 附件后缀白名单："资产"指图片等附件；源码/缓存等非附件文件不属于知识库概念
# （2026-09-20 真实库首跑教训：曾把 .py/.pyc 误报为未引用资产）
ASSET_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico",
    ".pdf", ".mp3", ".wav", ".mp4", ".mov", ".webm",
    ".docx", ".xlsx", ".pptx", ".zip", ".7z", ".rar",
}

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
CREATE TABLE IF NOT EXISTS assets(
    path TEXT PRIMARY KEY,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS content USING fts5(path UNINDEXED, body, tokenize='trigram');
CREATE TABLE IF NOT EXISTS links(
    source TEXT NOT NULL,
    target_raw TEXT NOT NULL,
    line INTEGER NOT NULL,
    kind TEXT,
    target_resolved TEXT,
    PRIMARY KEY(source, target_raw, line)
);
CREATE INDEX IF NOT EXISTS idx_links_source ON links(source);
CREATE INDEX IF NOT EXISTS idx_links_target ON links(target_resolved);
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


def iter_vault_files(vault: Path):
    """产出库内可见文件：.md 为笔记、附件白名单后缀为资产，其余（源码/缓存等）不可见。"""
    for dirpath, dirnames, filenames in os.walk(vault):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
        for name in filenames:
            if name.startswith("."):
                continue
            suffix = Path(name).suffix.lower()
            if suffix == ".md" or suffix in ASSET_SUFFIXES:
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
        existing_notes = {
            row[0]: (row[1], row[2])
            for row in conn.execute("SELECT path, mtime, size FROM files")
        }
        existing_assets = {
            row[0]: (row[1], row[2])
            for row in conn.execute("SELECT path, mtime, size FROM assets")
        }
        seen_notes: set[str] = set()
        seen_assets: set[str] = set()
        changed: dict[str, str] = {}

        for filepath in iter_vault_files(vault):
            relpath = filepath.relative_to(vault).as_posix()
            st = filepath.stat()
            fingerprint = (st.st_mtime, st.st_size)
            is_note = filepath.suffix.lower() == ".md"

            if is_note:
                seen_notes.add(relpath)
                existing = existing_notes
            else:
                seen_assets.add(relpath)
                existing = existing_assets

            if relpath in existing and existing[relpath] == fingerprint:
                if is_note:
                    stats.unchanged += 1
                continue

            if is_note:
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
                changed[relpath] = text
                if relpath not in existing_notes:
                    stats.added += 1
                else:
                    stats.updated += 1
            else:
                conn.execute(
                    "INSERT INTO assets(path, mtime, size) VALUES(?,?,?) "
                    "ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime, size=excluded.size",
                    (relpath, st.st_mtime, st.st_size),
                )

        for relpath in set(existing_notes) - seen_notes:
            conn.execute("DELETE FROM files WHERE path = ?", (relpath,))
            conn.execute("DELETE FROM content WHERE path = ?", (relpath,))
            conn.execute("DELETE FROM links WHERE source = ?", (relpath,))
            stats.removed += 1
        for relpath in set(existing_assets) - seen_assets:
            conn.execute("DELETE FROM assets WHERE path = ?", (relpath,))

        # 第二遍：已知路径集完整后统一解析并写入变化文件的链接
        known = [row[0] for row in conn.execute("SELECT path FROM files")]
        known += [row[0] for row in conn.execute("SELECT path FROM assets")]
        resolver = LinkResolver(known)
        for source, text in changed.items():
            conn.execute("DELETE FROM links WHERE source = ?", (source,))
            conn.executemany(
                "INSERT OR REPLACE INTO links(source, target_raw, line, kind, target_resolved) "
                "VALUES(?,?,?,?,?)",
                [
                    (source, link.target_raw, link.line, link.kind, resolver.resolve(source, link))
                    for link in extract_links(text)
                ],
            )

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
