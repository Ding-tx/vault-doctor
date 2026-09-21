"""修复起草器（M2-C）：LLM 提议"改什么"，代码决定"改哪里"。

ACI 切分理由：模型不擅长数字符偏移，但擅长判断"把 [[X]] 改成 [[Y]]"。
LLM 输出 JSON 草稿（line/old_text/new_text/reason），本地 locate_edit 把
old_text 定位为字符区间并写入 expected_old 前置条件——应用阶段再次校验。
定位失败/解析失败将原因回填给模型重试（≤ max_retries）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, ValidationError

from vault_doctor.engine.patches import Patch
from vault_doctor.engine.rules.base import Violation
from vault_doctor.llm.client import LLMError

DRAFT_SYSTEM_PROMPT = (
    "你是 vault-doctor（markdown 知识库体检工具）的修复起草器。"
    "给你一个 markdown 文件的内容和其中要修复的断链违规（附改名候选），"
    "起草最小修复补丁。只输出 JSON，不要输出其他文字，格式：\n"
    '{"patches": [{"line": <行号>, "old_text": "<原文中要替换的精确文本>", '
    '"new_text": "<替换后的文本>", "reason": "<一句话理由>"}]}\n'
    "规则：old_text 必须逐字复制原文；只替换链接目标本身（如 [[算法导论2]] → "
    "[[算法导论]]），不动行文；某条违规确实不该修时给出 reason 并把 old_text 留空；"
    "不修改与违规无关的任何内容。"
)


class DraftError(RuntimeError):
    pass


class DraftedEdit(BaseModel):
    line: int | None = None
    old_text: str = ""
    new_text: str = ""
    reason: str = ""


def _strip_fences(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_draft(content: str) -> list[DraftedEdit]:
    text = _strip_fences(content)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DraftError(f"输出不是合法 JSON：{exc}；原文片段：{text[:200]!r}") from exc
    raw = data.get("patches") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raise DraftError('输出缺少 "patches" 数组')
    edits: list[DraftedEdit] = []
    for item in raw:
        try:
            edits.append(DraftedEdit.model_validate(item))
        except ValidationError as exc:
            raise DraftError(f"补丁草稿字段非法：{exc}") from exc
    return edits


def _line_start_offset(text: str, line: int) -> int:
    lines = text.splitlines(keepends=True)
    return sum(len(l) for l in lines[: line - 1])


def locate_edit(text: str, old_text: str, line_hint: int | None = None) -> tuple[int, int]:
    """把 old_text 定位成 (start, end)。唯一出现直接定位；多次出现用行号消歧。"""
    if not old_text:
        raise DraftError("old_text 为空")
    occurrences = [m.start() for m in re.finditer(re.escape(old_text), text)]
    if not occurrences:
        raise DraftError(f"old_text 未在文件中找到：{old_text!r}")
    if len(occurrences) == 1:
        start = occurrences[0]
        return start, start + len(old_text)
    if line_hint is not None and line_hint >= 1:
        ls = _line_start_offset(text, line_hint)
        le = text.find("\n", ls)
        le = len(text) if le == -1 else le
        in_line = [o for o in occurrences if ls <= o < le]
        if len(in_line) == 1:
            return in_line[0], in_line[0] + len(old_text)
        raise DraftError(
            f"old_text 出现 {len(occurrences)} 次，在行 {line_hint} 内出现 {len(in_line)} 次，无法定位"
        )
    raise DraftError(f"old_text 出现 {len(occurrences)} 次，且未给行号，无法定位")


def _numbered_excerpt(text: str, lines_of_interest: list[int], window: int = 20, cap: int = 500) -> str:
    lines = text.splitlines()
    if len(lines) <= cap:
        return "\n".join(f"{i + 1:>4} | {l}" for i, l in enumerate(lines))
    chunks: list[str] = []
    covered: set[int] = set()
    for ln in sorted(lines_of_interest):
        if ln in covered:
            continue
        lo, hi = max(1, ln - window), min(len(lines), ln + window)
        chunks.append("\n".join(f"{i + 1:>4} | {lines[i]}" for i in range(lo - 1, hi)))
        covered.update(range(lo, hi + 1))
    return "\n……\n".join(chunks)


def build_draft_user_prompt(relpath: str, text: str, violations: list[Violation], feedback: str = "") -> str:
    parts = [f"文件：{relpath}（带行号）", _numbered_excerpt(text, [v.line for v in violations if v.line])]
    parts.append("要修复的违规：")
    for v in violations:
        cands = ", ".join(p for p, _d in (v.detail.get("candidates") or [])[:3])
        parts.append(f"- 行 {v.line}：{v.detail.get('target_raw')}（候选：{cands or '无'}）")
    if feedback:
        parts.append(f"上一轮草稿的问题，请修正：\n{feedback}")
    return "\n".join(parts)


def merge_usage(acc: dict, usage: dict) -> None:
    for key, value in usage.items():
        if isinstance(value, (int, float)):
            acc[key] = acc.get(key, 0) + value


def draft_file_patches(
    client,
    vault: Path,
    relpath: str,
    violations: list[Violation],
    rule_id: str,
    max_retries: int = 2,
    ledger=None,
) -> tuple[list[Patch], dict]:
    """对一个文件起草补丁：解析/定位失败回填重试（≤ max_retries）。返回 (补丁, 累计 usage)。

    传入 ledger 时，每次模型调用都记账（purpose=draft）——预算熔断在这里生效。"""
    feedback = ""
    usage_total: dict = {}
    text = (vault / relpath).read_text(encoding="utf-8", errors="replace")

    for _attempt in range(max_retries + 1):
        user_prompt = build_draft_user_prompt(relpath, text, violations, feedback)
        try:
            content, usage = client.chat(DRAFT_SYSTEM_PROMPT, user_prompt)
        except LLMError:
            raise
        if ledger is not None:
            ledger.record(usage, purpose="draft", file=relpath, attempt=_attempt + 1)
        merge_usage(usage_total, usage)

        try:
            edits = parse_draft(content)
        except DraftError as exc:
            feedback = str(exc)
            continue

        patches: list[Patch] = []
        errors: list[str] = []
        for e in edits:
            if not e.old_text:
                continue  # 模型判断该条不修
            try:
                start, end = locate_edit(text, e.old_text, e.line)
            except DraftError as exc:
                errors.append(str(exc))
                continue
            patches.append(
                Patch(
                    file=relpath,
                    start=start,
                    end=end,
                    replacement=e.new_text,
                    expected_old=e.old_text,
                    rule_id=rule_id,
                    rationale=e.reason or f"替换 {e.old_text} → {e.new_text}",
                )
            )
        if not errors:
            return patches, usage_total
        feedback = "以下草稿定位失败，请逐字复制原文后重试：\n" + "\n".join(errors)

    return [], usage_total
