"""链接图：解析笔记里的链接语法并解析目标，提供图谱查询与 near-miss 建议。

设计依据 DESIGN.md 4.2 / 10：
- 载体两类：[[wikilink]]（含 |别名、#标题、#^块引用、!嵌入）与 [md](path)
  ——"三种语法"指 wikilink、md 相对路径、以 / 开头的库根路径
- 大小写：默认不敏感（Windows 本地文件系统语义），CI 可配置敏感
- 代码块与行内代码中的链接不解析；外部 URL 与纯锚点链接不属于库内链接
"""
from __future__ import annotations

import posixpath
import re
import sqlite3
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote

FENCE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
WIKILINK_RE = re.compile(r"(!?)\[\[([^\[\]]+?)\]\]")
MDLINK_RE = re.compile(r"(!?)\[([^\[\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_EXTERNAL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")


@dataclass
class RawLink:
    target_raw: str
    line: int
    kind: str  # wikilink | wikilink-embed | md | md-embed


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _strip_code(text: str) -> str:
    # 围栏替换为等量换行，保住行号；行内代码不含换行，直接删除
    text = FENCE_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    return INLINE_CODE_RE.sub("", text)


def _clean_wikilink_target(raw: str) -> tuple[str, bool]:
    """去掉 |别名 与 #锚点；返回 (目标主体, 是否纯锚点链接)。"""
    target = raw.split("|", 1)[0].strip()
    if "#" in target:
        head = target.split("#", 1)[0].strip()
        return head, not head
    return target, False


def extract_links(text: str) -> list[RawLink]:
    links: list[RawLink] = []
    text = _strip_code(text)

    for m in WIKILINK_RE.finditer(text):
        embed = m.group(1) == "!"
        target, anchor_only = _clean_wikilink_target(m.group(2))
        if anchor_only or not target:
            continue
        kind = "wikilink-embed" if embed else "wikilink"
        links.append(RawLink(target, _line_of(text, m.start()), kind))

    for m in MDLINK_RE.finditer(text):
        embed = m.group(1) == "!"
        target = unquote(m.group(3).strip())
        if not target or target.startswith("#") or _EXTERNAL_RE.match(target):
            continue
        target = target.split("#", 1)[0]
        if not target:
            continue
        kind = "md-embed" if embed else "md"
        links.append(RawLink(target, _line_of(text, m.start()), kind))

    return links


class LinkResolver:
    """把链接原文解析为库内 POSIX 相对路径；解析不到返回 None（即断链）。

    重名冲突时取首个匹配（M0 策略：确定性优先，报告歧义留给后续规则）。
    """

    def __init__(self, known_paths: list[str], case_sensitive: bool = False):
        self._norm = str if case_sensitive else str.lower
        self._exact: dict[str, str] = {}
        self._by_stem: dict[str, list[str]] = {}
        for p in known_paths:
            self._exact[self._norm(p)] = p
            self._by_stem.setdefault(self._norm(PurePosixPath(p).stem), []).append(p)

    def resolve(self, source: str, link: RawLink) -> str | None:
        # 真实库教训（2026-09-21）：Windows 笔记常见 .\images\1.png 反斜杠路径与
        # bin/ 目录尾斜杠写法；先归一，target_raw 原样保留用于报告展示
        raw = link.target_raw.replace("\\", "/")
        rooted = raw.startswith("/")
        target = raw.rstrip("/")
        if not target:
            return None
        if link.kind.startswith("wikilink"):
            for cand in (target, target + ".md"):
                hit = self._exact.get(self._norm(cand))
                if hit:
                    return hit
            for suffix in (target, target + ".md"):
                hits = [
                    p for p in self._exact.values()
                    if self._norm(p).endswith("/" + self._norm(suffix))
                ]
                if hits:
                    return hits[0]
            return self._stem_hit(PurePosixPath(target).stem)

        # md 链接：以 / 开头视为库根路径，否则相对源文件目录解析
        if rooted:
            key = "/" + self._norm(target.lstrip("/"))
            hits = [p for p in self._exact.values() if self._norm(p).endswith(key)]
            return hits[0] if hits else None
        base = posixpath.dirname(source)
        cand = posixpath.normpath(posixpath.join(base, target)) if base else posixpath.normpath(target)
        for c in (cand, cand + ".md"):
            hit = self._exact.get(self._norm(c))
            if hit:
                return hit
        return self._stem_hit(PurePosixPath(cand).stem)

    def _stem_hit(self, stem: str) -> str | None:
        hits = self._by_stem.get(self._norm(stem))
        return hits[0] if hits else None


def links_of(conn: sqlite3.Connection, source: str) -> list[tuple]:
    """某笔记的全部出链：(target_raw, target_resolved, line, kind)。"""
    return conn.execute(
        "SELECT target_raw, target_resolved, line, kind FROM links "
        "WHERE source = ? ORDER BY line",
        (source,),
    ).fetchall()


def who_links_to(conn: sqlite3.Connection, path: str) -> list[tuple]:
    """某笔记/资产的全部入链（反向链接）：(source, line, kind)。"""
    return conn.execute(
        "SELECT source, line, kind FROM links "
        "WHERE target_resolved = ? ORDER BY source, line",
        (path,),
    ).fetchall()


def _osa_distance(a: str, b: str, cap: int) -> int | None:
    """带截断的 Damerau-Levenshtein（OSA）距离；超过 cap 返回 None。"""
    a, b = a.lower(), b.lower()
    la, lb = len(a), len(b)
    if abs(la - lb) > cap:
        return None
    prev2: list[int] | None = None
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)  # type: ignore[index]
        if min(cur) > cap:
            return None
        prev2, prev = prev, cur
    return prev[lb] if prev[lb] <= cap else None


def near_miss(conn: sqlite3.Connection, target_raw: str, max_distance: int = 2) -> list[tuple[str, int]]:
    """断链目标的改名候选：与现有文件名编辑距离 ≤ max_distance 的文件，按距离升序。

    两道过滤（真实库教训 2026-09-21）：
    - 比例过滤：距离达到较长名字一半以上视为巧合噪声（nqa.jpg → a.jpg，d=2/名长 3）
    - 扩展名匹配：带后缀的目标只建议同后缀候选（.jpg 断链不再建议 .py 文件）；
      无后缀目标（多为笔记名）只建议 .md 或无后缀文件
    """
    normalized = target_raw.replace("\\", "/")
    stem = PurePosixPath(normalized).stem
    suffix = PurePosixPath(normalized).suffix.lower()
    results: list[tuple[str, int]] = []
    for (path,) in conn.execute(
        "SELECT path FROM files UNION SELECT path FROM assets UNION SELECT path FROM others"
    ):
        candidate = PurePosixPath(path)
        if suffix:
            if candidate.suffix.lower() != suffix:
                continue
        elif candidate.suffix.lower() not in ("", ".md"):
            continue
        d = _osa_distance(stem, candidate.stem, max_distance)
        if d is not None and d < 0.5 * max(len(stem), len(candidate.stem)):
            results.append((path, d))
    return sorted(results, key=lambda t: (t[1], t[0]))
