"""B4 验收：四条核心规则的输出与 fixtures 基准真值一一对应。"""
from pathlib import Path

from engine.indexer import connect, default_db_path, index_vault
from engine.rules import BUILTIN_RULES, run_rules
from engine.rules.base import RuleContext
from tests.fixtures import (
    EXPECTED_BROKEN,
    EXPECTED_ORPHANS,
    EXPECTED_UNREFERENCED_ASSETS,
    build_vault,
)


def _violations(tmp_path: Path) -> list:
    build_vault(tmp_path)
    index_vault(tmp_path)
    ctx = RuleContext(connect(default_db_path(tmp_path)))
    return run_rules(ctx)


def test_registry_meta():
    assert set(BUILTIN_RULES) == {"link/broken", "link/near-miss", "note/orphan", "asset/unreferenced"}
    assert all(not rule.autofixable for rule in BUILTIN_RULES.values())
    assert BUILTIN_RULES["link/broken"].severity == "error"
    assert all(BUILTIN_RULES[rid].severity == "warn" for rid in ("link/near-miss", "note/orphan", "asset/unreferenced"))


def test_rules_match_ground_truth(tmp_path: Path):
    violations = _violations(tmp_path)
    by_rule: dict[str, list] = {}
    for v in violations:
        by_rule.setdefault(v.rule_id, []).append(v)

    # 断链：与基准一一对应，无误报漏报
    broken = {(v.file, v.detail["target_raw"]) for v in by_rule["link/broken"]}
    assert broken == EXPECTED_BROKEN

    # near-miss：恰好是断链中带候选的子集（3 例）
    near_miss_targets = {v.detail["target_raw"] for v in by_rule["link/near-miss"]}
    assert near_miss_targets == {"算法导论2", "概率论笔记", "daily/2026-09-17"}
    assert near_miss_targets <= {target for _, target in EXPECTED_BROKEN}

    # 孤儿与未引用资产：精确匹配
    assert {v.file for v in by_rule["note/orphan"]} == EXPECTED_ORPHANS
    assert {v.file for v in by_rule["asset/unreferenced"]} == EXPECTED_UNREFERENCED_ASSETS

    # 总量：7 断链 + 3 near-miss + 4 孤儿 + 3 未引用资产
    assert len(violations) == 17


def test_violation_fields(tmp_path: Path):
    violations = _violations(tmp_path)

    # 行号抽检：书单.md 的 [[不存在的书]] 在第 3 行
    hit = [
        v for v in violations
        if v.rule_id == "link/broken"
        and v.file == "读书/书单.md"
        and v.detail["target_raw"] == "不存在的书"
    ]
    assert hit and hit[0].line == 3

    # 每条违规都带可读 message；Violation 可 JSON 序列化（B5 --format json 依赖）
    assert all(v.message for v in violations)
    as_json = violations[0].model_dump()
    assert {"rule_id", "severity", "file", "message"} <= set(as_json)
