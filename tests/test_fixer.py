"""M2-C 修复编排器测试：端到端闭环、闸门拒绝、不支持的规则、无违规。"""
import io
from pathlib import Path

import pytest
from rich.console import Console

from vault_doctor.agent.fixer import run_fix
from tests.fixtures import build_vault


class DispatchClient:
    """按用户提示里出现的违规目标分发固定回复，模拟真实起草行为。"""

    def __init__(self):
        self.calls: list[str] = []
        self.responses = {
            "算法导论2": '{"patches": [{"line": 3, "old_text": "[[算法导论2]]", "new_text": "[[算法导论]]"}]}',
            "概率论笔记": '{"patches": [{"line": 3, "old_text": "[[概率论笔记]]", "new_text": "[[概率论]]"}]}',
            "2026-09-17": '{"patches": [{"line": 2, "old_text": "[[daily/2026-09-17]]", "new_text": "[[daily/2026-09-18]]"}]}',
        }

    def chat(self, system: str, user: str):
        self.calls.append(user)
        for key, resp in self.responses.items():
            if key in user:
                return resp, {"prompt_tokens": 100, "completion_tokens": 10}
        raise AssertionError(f"无法分发：{user[:80]}")


def _muted_console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False)


def test_run_fix_end_to_end(tmp_path: Path):
    build_vault(tmp_path)
    client = DispatchClient()

    report = run_fix(tmp_path, client, assume_yes=True, console=_muted_console())

    assert report.before == 3
    assert report.cleared == 3 and report.remaining == 0
    assert report.snapshot_id is not None
    assert sorted(report.applied_files) == ["daily/2026-09-18.md", "计算机/学习计划.md", "数学/复习.md"]
    assert (tmp_path / "计算机" / "学习计划.md").read_text(encoding="utf-8") == (
        "# 学习计划\n\n- [[算法导论]]\n- [[算法导论]]\n"
    )
    assert report.usage["prompt_tokens"] == 300  # 3 次起草调用累计


def test_run_fix_gate_rejected_keeps_files(tmp_path: Path):
    build_vault(tmp_path)
    client = DispatchClient()
    answers = iter(["n", "n", "n"])

    report = run_fix(
        tmp_path, client, assume_yes=False,
        input_fn=lambda prompt="": next(answers), console=_muted_console(),
    )

    assert report.before == 3 and report.remaining == 3 and report.cleared == 0
    assert report.snapshot_id is None
    assert "[[算法导论2]]" in (tmp_path / "计算机" / "学习计划.md").read_text(encoding="utf-8")


def test_run_fix_unsupported_rule(tmp_path: Path):
    build_vault(tmp_path)
    with pytest.raises(ValueError, match="仅支持"):
        run_fix(tmp_path, DispatchClient(), rule="note/orphan")


def test_run_fix_no_violations_never_calls_llm(tmp_path: Path):
    (tmp_path / "a.md").write_text("# a\n[[b]]\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# b\n[[a]]\n", encoding="utf-8")

    class Boom:
        def chat(self, *_):
            raise AssertionError("无违规时不应调用 LLM")

    report = run_fix(tmp_path, Boom(), console=_muted_console())
    assert report.before == 0 and report.files_attempted == 0
