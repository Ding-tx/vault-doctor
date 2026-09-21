"""M2-B 快照测试：创建、清单、回滚。"""
from pathlib import Path

import pytest

from vault_doctor.policy.snapshot import (
    SnapshotError,
    create_snapshot,
    list_snapshots,
    rollback,
)


def test_create_and_list(tmp_path: Path):
    (tmp_path / "a.md").write_text("AAA", encoding="utf-8")
    (tmp_path / "sub" / "b.md").parent.mkdir()
    (tmp_path / "sub" / "b.md").write_text("BBB", encoding="utf-8")

    snap = create_snapshot(tmp_path, ["a.md", "sub/b.md", "a.md"])  # 去重
    assert snap.files == ["a.md", "sub/b.md"]
    assert (snap.dir / "a.md").is_file()
    assert (snap.dir / "sub" / "b.md").is_file()
    assert (snap.dir / "manifest.json").is_file()
    assert list_snapshots(tmp_path) == [snap.session_id]


def test_rollback_restores_originals(tmp_path: Path):
    (tmp_path / "a.md").write_text("原内容", encoding="utf-8")
    snap = create_snapshot(tmp_path, ["a.md"])
    (tmp_path / "a.md").write_text("被修复改过的内容", encoding="utf-8")

    restored = rollback(tmp_path, snap.session_id)
    assert restored == ["a.md"]
    assert (tmp_path / "a.md").read_text(encoding="utf-8") == "原内容"


def test_rollback_rejects_bad_or_unknown_session(tmp_path: Path):
    with pytest.raises(SnapshotError):
        rollback(tmp_path, "../evil")
    with pytest.raises(SnapshotError):
        rollback(tmp_path, "20260921-000000-abc123")
