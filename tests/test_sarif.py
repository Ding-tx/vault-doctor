"""M1 SARIF 输出验收：结构、等级映射、路径与行号、CLI --output 落盘。"""
import json
from pathlib import Path

from vault_doctor.cli import sarif
from vault_doctor.cli.__main__ import main
from vault_doctor.engine.indexer import connect, default_db_path, index_vault
from vault_doctor.engine.rules import run_rules
from vault_doctor.engine.rules.base import RuleContext
from tests.fixtures import build_vault


def _violations(tmp_path: Path) -> list:
    build_vault(tmp_path)
    index_vault(tmp_path)
    return run_rules(RuleContext(connect(default_db_path(tmp_path))))


def test_sarif_structure(tmp_path: Path):
    doc = sarif.to_sarif(_violations(tmp_path))
    assert doc["version"] == "2.1.0"
    run = doc["runs"][0]
    assert run["tool"]["driver"]["name"] == "vault-doctor"
    assert run["tool"]["driver"]["version"] == "0.1.0"
    assert len(run["results"]) == 17
    assert {r["level"] for r in run["results"]} == {"error", "warning"}

    broken = next(r for r in run["results"] if r["ruleId"] == "link/broken")
    location = broken["locations"][0]["physicalLocation"]
    assert location["artifactLocation"]["uri"].startswith("读书/书单.md")
    assert location["artifactLocation"]["uriBaseId"] == "%SRCROOT%"
    assert location["region"]["startLine"] == 3

    # 用到的规则在 driver.rules 里有描述（GitHub 摄取要求）
    described = {r["id"] for r in run["tool"]["driver"]["rules"]}
    assert {"link/broken", "note/orphan"} <= described
    assert set(described) == {v["ruleId"] for v in run["results"]}


def test_scan_sarif_and_output(tmp_path: Path, capsys):
    build_vault(tmp_path)
    out = tmp_path / "report.sarif"
    code = main(["scan", str(tmp_path), "--format", "sarif", "-o", str(out)])
    assert code == 1
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert len(doc["runs"][0]["results"]) == 17
    # 写文件时 stdout 不应混入表格内容
    assert "断链" not in capsys.readouterr().out
