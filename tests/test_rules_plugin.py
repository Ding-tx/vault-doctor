"""M1 规则 SDK 验收：entry_points 插件加载、注册表合并、插件规则参与扫描。"""
from importlib.metadata import EntryPoint

from vault_doctor.engine.indexer import connect, default_db_path, index_vault
from vault_doctor.engine.rules import BUILTIN_RULES, build_registry, load_plugin_rules, run_rules
from vault_doctor.engine.rules.base import Rule, RuleContext
from tests.fixtures import build_vault


def _stub_ep() -> EntryPoint:
    return EntryPoint(name="stub", value="tests.stub_rule:RULE", group="vault_doctor.rules")


def test_load_plugin_rules_from_entry_point():
    rules = load_plugin_rules([_stub_ep()])
    assert [r.id for r in rules] == ["stub/demo"]


def test_registry_builtin_wins_on_conflict():
    imposter = Rule(id="link/broken", severity="info", detect=lambda ctx: [])
    registry = build_registry(plugin_rules=[imposter])
    assert registry["link/broken"] is BUILTIN_RULES["link/broken"]
    assert len(registry) == len(BUILTIN_RULES)


def test_run_rules_with_plugin_registry(tmp_path):
    build_vault(tmp_path)
    index_vault(tmp_path)
    registry = build_registry(plugin_rules=load_plugin_rules([_stub_ep()]))
    ctx = RuleContext(connect(default_db_path(tmp_path)))

    violations = run_rules(ctx, registry=registry)
    stub_hits = [v for v in violations if v.rule_id == "stub/demo"]
    assert len(stub_hits) == 1
    assert len(violations) == 18  # 基准 17 + 插件 1
