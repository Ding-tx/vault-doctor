"""B5 验收：CLI scan 的输出格式、退出码与过滤。"""
import json
from pathlib import Path

from vault_doctor.cli.__main__ import main
from tests.fixtures import build_vault


def test_scan_table_and_exit_code(tmp_path: Path, capsys):
    build_vault(tmp_path)
    code = main(["scan", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 1  # fixtures 含 error 级断链
    assert "断链" in out
    assert "读书/书单.md" in out
    assert "共 17 条" in out


def test_scan_json(tmp_path: Path, capsys):
    build_vault(tmp_path)
    assert main(["scan", str(tmp_path), "--format", "json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["notes"] == 26 and data["assets"] == 4
    assert len(data["violations"]) == 17
    assert {v["rule_id"] for v in data["violations"]} == {
        "link/broken",
        "link/near-miss",
        "note/orphan",
        "asset/unreferenced",
    }


def test_scan_rules_filter(tmp_path: Path, capsys):
    build_vault(tmp_path)
    code = main(["scan", str(tmp_path), "--rules", "note/orphan", "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 0  # 只跑 warn 级规则，无 error → 退出码 0
    assert len(data["violations"]) == 4
    assert all(v["rule_id"] == "note/orphan" for v in data["violations"])


def test_scan_missing_dir_returns_2(tmp_path: Path):
    assert main(["scan", str(tmp_path / "不存在")]) == 2


def test_scan_clean_vault_exit_zero(tmp_path: Path, capsys):
    (tmp_path / "a.md").write_text("# a\n[[b]]\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# b\n[[a]]\n", encoding="utf-8")
    assert main(["scan", str(tmp_path)]) == 0
    assert "未发现违规" in capsys.readouterr().out


def test_rules_command(capsys):
    assert main(["rules"]) == 0
    out = capsys.readouterr().out
    assert "link/broken" in out
    assert "内置" in out


def test_snapshots_and_rollback_cli(tmp_path, capsys):
    from vault_doctor.policy.snapshot import create_snapshot

    (tmp_path / "a.md").write_text("原", encoding="utf-8")
    snap = create_snapshot(tmp_path, ["a.md"])
    (tmp_path / "a.md").write_text("改", encoding="utf-8")

    assert main(["snapshots", str(tmp_path)]) == 0
    assert snap.session_id in capsys.readouterr().out

    assert main(["rollback", snap.session_id, str(tmp_path)]) == 0
    assert (tmp_path / "a.md").read_text(encoding="utf-8") == "原"


def test_rollback_unknown_session_returns_2(tmp_path, capsys):
    assert main(["rollback", "20990101-000000-ffffff", str(tmp_path)]) == 2
    assert "未找到快照" in capsys.readouterr().err
