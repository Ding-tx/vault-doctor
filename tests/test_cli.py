"""B5 验收：CLI scan 的输出格式、退出码与过滤。"""
import json
from pathlib import Path

from cli.__main__ import main
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
