"""M2-C 起草器测试：locate_edit、草稿解析、起草与失败重试。"""
from pathlib import Path

import pytest

from vault_doctor.agent.drafter import (
    DraftError,
    draft_file_patches,
    locate_edit,
    parse_draft,
)
from vault_doctor.engine.rules.base import Violation


class ScriptedClient:
    """按脚本顺序返回回复；记录每次调用的 (system, user)。"""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, user: str):
        self.calls.append((system, user))
        if not self.responses:
            raise AssertionError("意外的额外调用")
        return self.responses.pop(0), {"prompt_tokens": 100, "completion_tokens": 10}


def test_locate_unique():
    text = "AAA [[目标]] BBB"
    start, end = locate_edit(text, "[[目标]]")
    assert text[start:end] == "[[目标]]"


def test_locate_multiple_with_line_hint():
    text = "同词\n同词\n别的"
    start, end = locate_edit(text, "同词", line_hint=2)
    assert text[:start].count("\n") == 1  # 第二行的那个


def test_locate_multiple_without_hint_raises():
    with pytest.raises(DraftError, match="出现 2 次"):
        locate_edit("同词 同词", "同词")


def test_locate_not_found_raises():
    with pytest.raises(DraftError, match="未在文件中找到"):
        locate_edit("AAA", "ZZZ")


def test_parse_draft_with_fences():
    content = '```json\n{"patches": [{"line": 3, "old_text": "[[x]]", "new_text": "[[y]]"}]}\n```'
    edits = parse_draft(content)
    assert edits[0].old_text == "[[x]]" and edits[0].line == 3


def test_parse_draft_invalid():
    with pytest.raises(DraftError, match="JSON"):
        parse_draft("我觉得应该这样改……")


def test_draft_file_patches_happy(tmp_path: Path):
    (tmp_path / "note.md").write_text("# 计划\n\n- [[算法导论2]]\n", encoding="utf-8")
    v = Violation(
        rule_id="link/near-miss", severity="warn", file="note.md", line=3,
        message="疑似改名", detail={"target_raw": "算法导论2", "candidates": [("计算机/算法导论.md", 1)]},
    )
    client = ScriptedClient([
        '{"patches": [{"line": 3, "old_text": "[[算法导论2]]", "new_text": "[[算法导论]]", "reason": "命中改名候选"}]}'
    ])

    patches, usage = draft_file_patches(client, tmp_path, "note.md", [v], "link/near-miss")

    assert len(patches) == 1
    p = patches[0]
    text = (tmp_path / "note.md").read_text(encoding="utf-8")
    assert text[p.start : p.end] == "[[算法导论2]]"  # 偏移准确
    assert p.expected_old == "[[算法导论2]]"
    assert p.replacement == "[[算法导论]]"
    assert "改名候选" in p.rationale
    assert usage == {"prompt_tokens": 100, "completion_tokens": 10}


def test_draft_retries_with_feedback(tmp_path: Path):
    (tmp_path / "note.md").write_text("# 计划\n\n- [[算法导数]]\n", encoding="utf-8")
    v = Violation(
        rule_id="link/near-miss", severity="warn", file="note.md", line=3,
        message="疑似改名", detail={"target_raw": "算法导数", "candidates": [("计算机/算法导论.md", 1)]},
    )
    client = ScriptedClient([
        '{"patches": [{"line": 3, "old_text": "[[不存在的文本]]", "new_text": "[[x]]"}]}',  # 定位失败
        '{"patches": [{"line": 3, "old_text": "[[算法导数]]", "new_text": "[[算法导论]]"}]}',
    ])

    patches, usage = draft_file_patches(client, tmp_path, "note.md", [v], "link/near-miss")

    assert len(client.calls) == 2
    assert "未在文件中找到" in client.calls[1][1]  # 失败原因回填进了第二次提示
    assert len(patches) == 1 and patches[0].replacement == "[[算法导论]]"
    assert usage["prompt_tokens"] == 200  # 两次调用累计
