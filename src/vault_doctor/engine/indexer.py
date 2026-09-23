"""vault-doctor 索引器：把 markdown 库的元数据、全文与链接图索引进 SQLite。

设计依据 DESIGN.md 6.2 / 10：
- 单文件 SQLite：files 笔记 + assets 附件 + others 普通文件 + dirs 目录
  + FTS5 全文（trigram 分词，支持中文子串检索）+ links 链接图
- 两级可见性（2026-09-21 真实库校准）：
  * 解析器看得见一切——notes/assets/others/dirs 全部进 LinkResolver 已知集合，
    否则指向 LICENSE、bin/ 等普通文件的链接会被误报断链
  * 规则各管各的——note/orphan 只看笔记，asset/unreferenced 只看附件
- .vaultdoctorignore：每行一个 fnmatch 模式（# 注释），匹配路径前缀即整棵跳过，
  用于把供应商代码等"非笔记子树"划出扫描范围
- 增量更新：以 (mtime, size) 指纹判断变更；链接重解析只发生在变化的文件上
- 全链路 UTF-8：坏字节以 U+FFFD 替换而不是让索引崩溃
"""
from __future__ import annotations

import fnmatch
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from vault_doctor.engine.graph import LinkResolver, RawLink, extract_links

SCHEMA_VERSION = "3"

# 链接解析逻辑版本：变化时即使文件未变也全量重解析（增量索引的引擎版本盲区）。
# v3（2026-09-23）：新增"已知路径集合变化 → 未变文件链接定向复检"（见下方愈合逻辑），
# 存量索引靠本次版本升级一次性全量重解析自愈。
LINKS_VERSION = "3"

SKIP_DIRS = {"node_modules", "__pycache__", "venv", "dist", "build"}

# 附件后缀白名单："资产"指图片等附件；其余非 md 文件进 others 表（可解析、不进规则）
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
CREATE TABLE IF NOT EXISTS others(
    path TEXT PRIMARY KEY,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS dirs(path TEXT PRIMARY KEY);
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


def load_ignore_patterns(vault: Path) -> list[str]:
    """读取 <vault>/.vaultdoctorignore：每行一个 fnmatch 模式，# 为注释。"""
    ignore_file = vault / ".vaultdoctorignore"
    if not ignore_file.is_file():
        return []
    lines = ignore_file.read_text(encoding="utf-8", errors="replace").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def _is_ignored(relpath: str, patterns: list[str]) -> bool:
    """relpath 的任一级前缀命中任一模式即忽略（模式作用于整棵子树）。"""
    if not patterns:
        return False
    parts = relpath.split("/")
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    return any(
        fnmatch.fnmatch(prefix, pattern.rstrip("/"))
        for prefix in prefixes
        for pattern in patterns
    )


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
    patterns = load_ignore_patterns(vault)

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
        existing_others = {
            row[0]: (row[1], row[2])
            for row in conn.execute("SELECT path, mtime, size FROM others")
        }
        existing_dirs = {row[0] for row in conn.execute("SELECT path FROM dirs")}
        seen_notes: set[str] = set()
        seen_assets: set[str] = set()
        seen_others: set[str] = set()
        all_dirs: list[str] = []
        changed: dict[str, str] = {}

        for dirpath, dirnames, filenames in os.walk(vault):
            rel_dir = Path(dirpath).relative_to(vault).as_posix()

            kept: list[str] = []
            for d in dirnames:
                if d.startswith(".") or d in SKIP_DIRS:
                    continue
                rel = f"{rel_dir}/{d}" if rel_dir != "." else d
                if _is_ignored(rel, patterns):
                    continue
                kept.append(d)
                all_dirs.append(rel)
            dirnames[:] = kept

            for name in filenames:
                if name.startswith("."):
                    continue
                relpath = f"{rel_dir}/{name}" if rel_dir != "." else name
                if _is_ignored(relpath, patterns):
                    continue

                filepath = Path(dirpath) / name
                st = filepath.stat()
                fingerprint = (st.st_mtime, st.st_size)
                suffix = filepath.suffix.lower()

                if suffix == ".md":
                    seen_notes.add(relpath)
                    if relpath in existing_notes and existing_notes[relpath] == fingerprint:
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
                    changed[relpath] = text
                    if relpath not in existing_notes:
                        stats.added += 1
                    else:
                        stats.updated += 1
                elif suffix in ASSET_SUFFIXES:
                    seen_assets.add(relpath)
                    if relpath in existing_assets and existing_assets[relpath] == fingerprint:
                        continue
                    conn.execute(
                        "INSERT INTO assets(path, mtime, size) VALUES(?,?,?) "
                        "ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime, size=excluded.size",
                        (relpath, st.st_mtime, st.st_size),
                    )
                else:
                    seen_others.add(relpath)
                    if relpath in existing_others and existing_others[relpath] == fingerprint:
                        continue
                    conn.execute(
                        "INSERT INTO others(path, mtime, size) VALUES(?,?,?) "
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
        for relpath in set(existing_others) - seen_others:
            conn.execute("DELETE FROM others WHERE path = ?", (relpath,))

        # 引擎版本盲区（2026-09-21 真实库教训）：指纹只看文件 mtime，解析逻辑
        # 变化时 links 表仍是旧结果——同一目标 link/broken 说找不到、near-miss（现场
        # 计算）却说是它。版本号不一致 → 全量重解析（文本从 FTS 表取，不重读盘）
        row = conn.execute("SELECT value FROM meta WHERE key = 'links_version'").fetchone()
        if row is None or row[0] != LINKS_VERSION:
            changed.update(dict(conn.execute("SELECT path, body FROM content")))

        # 目录表整表刷新（无指纹语义，量小无所谓）
        conn.execute("DELETE FROM dirs")
        conn.executemany("INSERT OR REPLACE INTO dirs(path) VALUES(?)", [(d,) for d in all_dirs])

        # 第二遍：已知路径集完整后统一解析并写入变化文件的链接
        known = [row[0] for row in conn.execute("SELECT path FROM files")]
        known += [row[0] for row in conn.execute("SELECT path FROM assets")]
        known += [row[0] for row in conn.execute("SELECT path FROM others")]
        known += [row[0] for row in conn.execute("SELECT path FROM dirs")]
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

        # 链接愈合与失效（2026-09-23 真实库教训，校准记录 #7）：
        # 增量索引只复查"自己变过的文件"——若目标文件在链接落盘之后才出现（或被删除），
        # 未变文件的链接解析结果就永久停留在过期状态：断链不愈合、删链不断裂。
        # 已知路径集合有变时，对 links 表做一次定向复检，只翻转发生变化的行。
        known_before = (
            set(existing_notes) | set(existing_assets) | set(existing_others) | existing_dirs
        )
        known_after = seen_notes | seen_assets | seen_others | set(all_dirs)
        if known_before != known_after:
            for source, target_raw, kind in conn.execute(
                "SELECT DISTINCT source, target_raw, kind FROM links "
                "WHERE target_resolved IS NULL"
            ).fetchall():
                healed = resolver.resolve(source, RawLink(target_raw, 0, kind))
                if healed:
                    conn.execute(
                        "UPDATE links SET target_resolved = ? WHERE source = ? AND target_raw = ?",
                        (healed, source, target_raw),
                    )
            for gone in known_before - known_after:
                conn.execute(
                    "UPDATE links SET target_resolved = NULL WHERE target_resolved = ?",
                    (gone,),
                )

        conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (SCHEMA_VERSION,),
        )
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('links_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (LINKS_VERSION,),
        )
        conn.commit()
    finally:
        conn.close()

    stats.elapsed = time.perf_counter() - start
    return stats
