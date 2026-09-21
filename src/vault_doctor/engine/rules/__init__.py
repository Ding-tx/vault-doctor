"""规则注册表：内置规则 + 第三方插件规则（entry_points 组 vault_doctor.rules）。

- 插件在其包的 pyproject 里声明：[project.entry-points."vault_doctor.rules"]
  my_rule = "my_package.rules:MY_RULE"；entry point 指向 Rule 实例或 Rule 序列
- id 冲突时内置规则永远优先（防止伪装成内置规则的行为替换）；插件之间先到先得
- 坏插件（加载失败/类型不对）跳过并告警，不得拖垮扫描

确定性输出：run_rules 按注册顺序产出，规则内部按 (file, line) 排序，
同一次扫描同一索引必然得到完全相同的结果——这是"复扫即断言"的前提。
"""
from __future__ import annotations

import sys
from importlib.metadata import EntryPoint, entry_points

from vault_doctor.engine.rules import asset_unreferenced, link_broken, link_near_miss, note_orphan
from vault_doctor.engine.rules.base import Rule, RuleContext, Violation

BUILTIN_RULES: dict[str, Rule] = {
    rule.id: rule
    for rule in (link_broken.RULE, link_near_miss.RULE, note_orphan.RULE, asset_unreferenced.RULE)
}

PLUGIN_GROUP = "vault_doctor.rules"


def load_plugin_rules(ep_source: list[EntryPoint] | None = None) -> list[Rule]:
    """从 entry points 加载第三方规则；坏插件跳过并告警。"""
    if ep_source is None:
        ep_source = list(entry_points(group=PLUGIN_GROUP))
    loaded_rules: list[Rule] = []
    for ep in ep_source:
        try:
            loaded = ep.load()
        except Exception as exc:  # noqa: BLE001 插件的失败属于外部输入
            print(f"[vault-doctor] 插件规则加载失败，已跳过：{ep.name}（{exc}）", file=sys.stderr)
            continue
        if isinstance(loaded, Rule):
            loaded_rules.append(loaded)
        elif isinstance(loaded, (list, tuple)) and all(isinstance(r, Rule) for r in loaded):
            loaded_rules.extend(loaded)
        else:
            print(f"[vault-doctor] 插件规则类型非法，已跳过：{ep.name}", file=sys.stderr)
    return loaded_rules


def build_registry(plugin_rules: list[Rule] | None = None) -> dict[str, Rule]:
    """内置优先合并插件规则；同 id 冲突忽略后注册者。"""
    if plugin_rules is None:
        plugin_rules = load_plugin_rules()
    registry = dict(BUILTIN_RULES)
    for rule in plugin_rules:
        if rule.id in registry:
            print(f"[vault-doctor] 规则 id 冲突，忽略后注册者：{rule.id}", file=sys.stderr)
            continue
        registry[rule.id] = rule
    return registry


REGISTRY: dict[str, Rule] = build_registry()


def run_rules(
    ctx: RuleContext,
    rule_ids: list[str] | None = None,
    registry: dict[str, Rule] | None = None,
) -> list[Violation]:
    rules = registry if registry is not None else REGISTRY
    ids = rule_ids if rule_ids is not None else list(rules)
    unknown = [rid for rid in ids if rid not in rules]
    if unknown:
        raise KeyError(f"未注册的规则：{unknown}")
    violations: list[Violation] = []
    for rid in ids:
        violations.extend(rules[rid].detect(ctx))
    return violations
