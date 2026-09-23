"""闸门测试：y/n/a/q、assume_yes、前置条件失败、快照集成。"""
import io
from pathlib import Path

from rich.console import Console

from vault_doctor.engine.patches import Patch
from vault_doctor.policy.gates import apply_with_gate
from vault_doctor.policy.snapshot import rollback


def _setup(tmp_path: Path, name: str = "a.md", text: str = "AAA BBB"):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _patch(file: str = "a.md", start: int = 0, end: int = 3, replacement: str = "X", **kw):
    return Patch(file=file, start=start, end=end, replacement=replacement, rule_id="test", **kw)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _inputs(*answers: str):
    queue = list(answers)
    calls = []

    def fake_input(prompt: str = "") -> str:
        calls.append(prompt)
        if not queue:
            raise EOFError
        return queue.pop(0)

    fake_input.calls = calls
    return fake_input


def test_gate_yes_applies_and_snapshots(tmp_path: Path):
    _setup(tmp_path)
    outcome = apply_with_gate(tmp_path, [_patch()], input_fn=_inputs("y"))
    assert _read(tmp_path / "a.md") == "X BBB"
    assert outcome.snapshot is not None
    assert outcome.applied_files == ["a.md"]


def test_gate_no_skips_without_snapshot(tmp_path: Path):
    _setup(tmp_path)
    outcome = apply_with_gate(tmp_path, [_patch()], input_fn=_inputs("n"))
    assert _read(tmp_path / "a.md") == "AAA BBB"
    assert outcome.snapshot is None
    assert outcome.skipped and not outcome.approved


def test_gate_q_cancels_everything(tmp_path: Path):
    _setup(tmp_path, "a.md", "AAA")
    _setup(tmp_path, "b.md", "BBB")
    patches = [_patch("a.md"), _patch("b.md", 0, 3, "Y")]
    outcome = apply_with_gate(tmp_path, patches, input_fn=_inputs("y", "q"))
    # q 取消一切，包括已按过 y 的文件
    assert _read(tmp_path / "a.md") == "AAA"
    assert _read(tmp_path / "b.md") == "BBB"
    assert outcome.snapshot is None and not outcome.approved


def test_gate_a_applies_rest_without_asking(tmp_path: Path):
    _setup(tmp_path, "a.md", "AAA")
    _setup(tmp_path, "b.md", "BBB")
    patches = [_patch("a.md"), _patch("b.md", 0, 3, "Y")]
    input_fn = _inputs("a")
    outcome = apply_with_gate(tmp_path, patches, input_fn=input_fn)
    assert _read(tmp_path / "a.md") == "X"
    assert _read(tmp_path / "b.md") == "Y"
    assert len(input_fn.calls) == 1  # 第二个文件不再询问


def test_gate_assume_yes_never_prompts(tmp_path: Path):
    _setup(tmp_path)

    def boom(prompt: str = "") -> str:
        raise AssertionError("assume_yes 不应弹出任何提示")

    outcome = apply_with_gate(tmp_path, [_patch()], assume_yes=True, input_fn=boom)
    assert _read(tmp_path / "a.md") == "X BBB"


def test_gate_invalid_answer_reasks(tmp_path: Path):
    _setup(tmp_path)
    input_fn = _inputs("x", "", "y")
    apply_with_gate(tmp_path, [_patch()], input_fn=input_fn)
    assert len(input_fn.calls) == 3
    assert _read(tmp_path / "a.md") == "X BBB"


def test_gate_precondition_failure_skips_file_but_continues(tmp_path: Path):
    _setup(tmp_path, "a.md", "AAA")   # 补丁期望 ZZZ → 失败
    _setup(tmp_path, "b.md", "BBB")
    bad = _patch("a.md", expected_old="ZZZ")
    good = _patch("b.md", 0, 3, "Y")
    outcome = apply_with_gate(tmp_path, [bad, good], input_fn=_inputs("y"))
    assert _read(tmp_path / "a.md") == "AAA"
    assert _read(tmp_path / "b.md") == "Y"
    assert outcome.applied_files == ["b.md"]


def test_gate_apply_then_rollback_roundtrip(tmp_path: Path):
    _setup(tmp_path)
    console = Console(file=io.StringIO(), force_terminal=False)  # 静音输出
    outcome = apply_with_gate(tmp_path, [_patch()], input_fn=_inputs("y"), console=console)
    assert _read(tmp_path / "a.md") == "X BBB"
    restored = rollback(tmp_path, outcome.snapshot.session_id)
    assert restored == ["a.md"]
    assert _read(tmp_path / "a.md") == "AAA BBB"


def test_gate_on_decision_callback(tmp_path: Path):
    _setup(tmp_path, "a.md", "AAA")
    _setup(tmp_path, "b.md", "BBB")
    decisions: list[tuple[str, str]] = []

    apply_with_gate(
        tmp_path,
        [_patch("a.md"), _patch("b.md", 0, 3, "Y")],
        input_fn=_inputs("a"),
        console=Console(file=io.StringIO(), force_terminal=False),
        on_decision=lambda f, d: decisions.append((f, d)),
    )
    # a 键触发本文件 + 之后全部 auto
    assert decisions == [("a.md", "a"), ("b.md", "auto")]
