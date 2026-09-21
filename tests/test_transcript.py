"""M2-D 事件流测试：append/read 往返、坏行跳过、会话 id。"""
from pathlib import Path

from vault_doctor.kernel.transcript import Transcript, new_session_id


def test_append_read_roundtrip(tmp_path: Path):
    t = Transcript(tmp_path / "sessions" / "s1.jsonl")
    t.append({"type": "session_start", "command": "fix", "文件": "中文值"})
    t.append({"type": "session_end", "ok": True, "ts": "2026-09-21T00:00:00"})

    events = t.read()
    assert [e["type"] for e in events] == ["session_start", "session_end"]
    assert events[0]["文件"] == "中文值"      # 中文不转义，可读
    assert "ts" in events[0]                  # 自动补时间戳
    assert events[1]["ts"] == "2026-09-21T00:00:00"  # 已有则不覆盖


def test_malformed_lines_skipped(tmp_path: Path):
    p = tmp_path / "s.jsonl"
    p.write_text(
        '{"type": "a"}\n不是JSON\n\n{"type": "b"}\n', encoding="utf-8"
    )
    t = Transcript(p)
    events = t.read()
    assert [e["type"] for e in events] == ["a", "b"]
    assert t.skipped_lines == 1


def test_session_ids_unique_and_shaped():
    ids = {new_session_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(len(sid.split("-")) == 3 for sid in ids)
