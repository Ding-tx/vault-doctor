"""规则注册表：内置四条 P0 规则，注册制扩展（新规则加模块 + 加进 ALL）。

确定性输出：run_rules 按注册顺序产出，规则内部按 (file, line) 排序，
同一次扫描同一索引必然得到完全相同的结果——这是"复扫即断言"的前提。
"""
from __future__ import annotations

from engine.rules import asset_unreferenced, link_broken, link_near_miss, note_orphan
from engine.rules.base import Rule, RuleContext, Violation

ALL_RULES = (link_broken.RULE, link_near_miss.RULE, note_orphan.RULE, asset_unreferenced.RULE)

BUILTIN_RULES: dict[str, Rule] = {rule.id: rule for rule in ALL_RULES}


def run_rules(ctx: RuleContext, rule_ids: list[str] | None = None) -> list[Violation]:
    ids = rule_ids if rule_ids is not None else list(BUILTIN_RULES)
    unknown = [rid for rid in ids if rid not in BUILTIN_RULES]
    if unknown:
        raise KeyError(f"未注册的规则：{unknown}")
    violations: list[Violation] = []
    for rid in ids:
        violations.extend(BUILTIN_RULES[rid].detect(ctx))
    return violations
