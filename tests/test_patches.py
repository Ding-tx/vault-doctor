"""文本补丁模型测试：应用、多补丁、冲突、前置条件、越界、dry-run。"""
from pathlib import Path

import pytest
from pydantic import ValidationError

from vault_doctor.engine.patches import Patch, apply_patches, detect_conflicts


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _read(tmp_path: Path, name: str) -> str:
    return (tmp_path / name).read_text(encoding="utf-8")


def test_patch_rejects_bad_range():
    with pytest.raises(ValidationError):
        Patch(file="a.md", start=5, end=3, replacement="x")


def test_apply_single_patch(tmp_path: Path):
    _write(tmp_path, "a.md", "看 [[旧目标]] 的笔记")
    text = _read(tmp_path, "a.md")
    start = text.index("[[旧目标]]")
    p = Patch(
        file="a.md",
        start=start,
        end=start + len("[[旧目标]]"),
        replacement="[[新目标]]",
        expected_old="[[旧目标]]",
        rule_id="link/near-miss",
    )
    result = apply_patches(tmp_path, [p])
    assert result.all_ok
    assert _read(tmp_path, "a.md") == "看 [[新目标]] 的笔记"


def test_apply_multiple_non_overlapping(tmp_path: Path):
    _write(tmp_path, "a.md", "AAA BBB CCC")
    patches = [
        Patch(file="a.md", start=0, end=3, replacement="X"),
        Patch(file="a.md", start=8, end=11, replacement="Z"),
    ]
    result = apply_patches(tmp_path, patches)
    assert result.all_ok
    assert _read(tmp_path, "a.md") == "X BBB Z"


def test_conflicting_patches_skip_whole_file(tmp_path: Path):
    _write(tmp_path, "a.md", "AAA BBB CCC")
    patches = [
        Patch(file="a.md", start=0, end=5, replacement="X"),
        Patch(file="a.md", start=3, end=8, replacement="Y"),
    ]
    assert len(detect_conflicts(patches)) == 1
    result = apply_patches(tmp_path, patches)
    assert not result.files[0].ok
    assert "重叠" in result.files[0].error
    assert _read(tmp_path, "a.md") == "AAA BBB CCC"  # 冲突时原文不动


def test_precondition_mismatch_aborts(tmp_path: Path):
    _write(tmp_path, "a.md", "AAA")
    p = Patch(file="a.md", start=0, end=3, replacement="X", expected_old="ZZZ")
    result = apply_patches(tmp_path, [p])
    assert not result.files[0].ok
    assert "前置条件" in result.files[0].error
    assert _read(tmp_path, "a.md") == "AAA"


def test_out_of_bounds_aborts(tmp_path: Path):
    _write(tmp_path, "a.md", "AAA")
    p = Patch(file="a.md", start=2, end=99, replacement="X")
    result = apply_patches(tmp_path, [p])
    assert not result.files[0].ok
    assert "越界" in result.files[0].error
    assert _read(tmp_path, "a.md") == "AAA"


def test_multi_file_and_end_insertion(tmp_path: Path):
    _write(tmp_path, "a.md", "AAA")
    _write(tmp_path, "sub/b.md", "BBB")
    patches = [
        Patch(file="a.md", start=3, end=3, replacement="-尾部插入"),
        Patch(file="sub/b.md", start=0, end=3, replacement="Y"),
    ]
    result = apply_patches(tmp_path, patches)
    assert result.all_ok and len(result.files) == 2
    assert _read(tmp_path, "a.md") == "AAA-尾部插入"
    assert _read(tmp_path, "sub/b.md") == "Y"


def test_dry_run_does_not_write(tmp_path: Path):
    _write(tmp_path, "a.md", "AAA")
    p = Patch(file="a.md", start=0, end=3, replacement="X")
    result = apply_patches(tmp_path, [p], write=False)
    assert result.all_ok
    assert _read(tmp_path, "a.md") == "AAA"
