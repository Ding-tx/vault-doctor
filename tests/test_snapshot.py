"""M2-B 快照测试：创建、清单、回滚。"""
from pathlib import Path

import pytest

from vault_doctor.policy.snapshot import (
    SnapshotError,
    create_snapshot,
    list_snapshots,
    list_snapshots_detail,
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


def test_list_snapshots_detail(tmp_path: Path):
    """详情回答用户三问：什么时候建的、改了哪些文件、同一文件是否有多份快照。"""
    (tmp_path / "a.md").write_text("v1", encoding="utf-8")
    (tmp_path / "b.md").write_text("b", encoding="utf-8")
    s1 = create_snapshot(tmp_path, ["a.md"])
    (tmp_path / "a.md").write_text("v2", encoding="utf-8")
    s2 = create_snapshot(tmp_path, ["a.md", "b.md"])

    detail = list_snapshots_detail(tmp_path)
    # 同秒创建的两份快照 id 排序不区分先后（回滚按显式 id，顺序仅影响展示），
    # 因此按 id 对内容断言，不假定创建顺序 == id 排序
    by_sid = {d["session_id"]: d for d in detail}
    assert set(by_sid) == {s1.session_id, s2.session_id}
    assert by_sid[s1.session_id]["files"] == ["a.md"]
    assert by_sid[s2.session_id]["files"] == ["a.md", "b.md"]
    assert all(d["created_at"] for d in detail)
    # 同一文件 a.md 出现在两份快照中——回滚目标可据此区分
    assert sum("a.md" in d["files"] for d in detail) == 2


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
