"""文本补丁模型（M2-A）：一切修复的唯一表示与唯一写路径基础。

设计依据 DESIGN.md 4.3：
- 修复 = 文本补丁（start/end 字符偏移 + 替换文本），不做 AST 重写
- 补丁自带前置条件 expected_old：应用前校验原文一致，防止上下文过期写坏文件
- 同文件区间重叠即冲突，整文件跳过——宁可不动，不可写错
- 应用按 (start, end) 降序，避免偏移位移；写入 newline="" 保持原换行符
- apply_to_text（M2-B 起）：闸门预览与应用共用同一套校验/应用逻辑
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, model_validator


class PatchError(RuntimeError):
    """补丁校验失败（越界 / 前置条件不符）。"""


class Patch(BaseModel):
    file: str
    start: int
    end: int
    replacement: str
    expected_old: str = ""
    rule_id: str = ""
    rationale: str = ""

    @model_validator(mode="after")
    def _check_range(self) -> "Patch":
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"非法区间 [{self.start}, {self.end})")
        return self


@dataclass
class FileApply:
    file: str
    ok: bool
    applied: int = 0
    error: str | None = None


@dataclass
class ApplyResult:
    files: list[FileApply] = field(default_factory=list)
    conflicts: list[tuple[Patch, Patch]] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return all(f.ok for f in self.files)


def detect_conflicts(patches: list[Patch]) -> list[tuple[Patch, Patch]]:
    """同文件区间重叠（start < other.end and other.start < end）即冲突；
    相邻不重叠与同点零长插入不算冲突（应用顺序确定：(start, end) 降序）。"""
    by_file: dict[str, list[Patch]] = {}
    for p in patches:
        by_file.setdefault(p.file, []).append(p)
    conflicts: list[tuple[Patch, Patch]] = []
    for group in by_file.values():
        ordered = sorted(group, key=lambda p: (p.start, p.end))
        for i, a in enumerate(ordered):
            for b in ordered[i + 1 :]:
                if a.start < b.end and b.start < a.end:
                    conflicts.append((a, b))
    return conflicts


def apply_to_text(text: str, patches: list[Patch]) -> str:
    """校验并把同一文件的补丁应用到文本，返回新文本；校验失败抛 PatchError。

    校验全部在原文坐标上完成后才应用；应用按 (start, end) 降序。
    调用方负责先用 detect_conflicts 排除重叠。"""
    for p in patches:
        if p.end > len(text):
            raise PatchError(f"区间越界：[{p.start}, {p.end}) 超出文件长度 {len(text)}")
        if p.expected_old and text[p.start : p.end] != p.expected_old:
            raise PatchError(
                f"前置条件不符：期望 {p.expected_old!r}，实际 {text[p.start : p.end]!r}"
            )
    for p in sorted(patches, key=lambda p: (p.start, p.end), reverse=True):
        text = text[: p.start] + p.replacement + text[p.end :]
    return text


def apply_patches(vault: Path, patches: list[Patch], write: bool = True) -> ApplyResult:
    """把补丁应用到库文件。任何校验失败都跳过对应文件，绝不写半对的内容。"""
    result = ApplyResult(conflicts=detect_conflicts(patches))
    conflicted_files = {a.file for a, _ in result.conflicts} | {b.file for _, b in result.conflicts}
    by_file: dict[str, list[Patch]] = {}
    for p in patches:
        by_file.setdefault(p.file, []).append(p)

    for relpath, group in sorted(by_file.items()):
        if relpath in conflicted_files:
            result.files.append(FileApply(relpath, ok=False, error="存在重叠补丁，整文件跳过"))
            continue
        path = vault / relpath
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            new_text = apply_to_text(text, group)
        except OSError as exc:
            result.files.append(FileApply(relpath, ok=False, error=f"读取失败：{exc}"))
            continue
        except PatchError as exc:
            result.files.append(FileApply(relpath, ok=False, error=str(exc)))
            continue

        if write:
            try:
                path.write_text(new_text, encoding="utf-8", newline="")
            except OSError as exc:
                result.files.append(FileApply(relpath, ok=False, error=f"写入失败：{exc}"))
                continue
        result.files.append(FileApply(relpath, ok=True, applied=len(group)))
    return result
