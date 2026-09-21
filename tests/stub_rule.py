"""插件规则的测试替身：entry point 的加载目标。"""
from vault_doctor.engine.rules.base import Rule, RuleContext, Violation


def _detect(ctx: RuleContext) -> list[Violation]:
    return [
        Violation(
            rule_id="stub/demo",
            severity="info",
            file="stub.md",
            line=1,
            message="插件规则的示范违规",
            detail={},
        )
    ]


RULE = Rule(
    id="stub/demo",
    severity="info",
    autofixable=False,
    description="测试用插件规则",
    detect=_detect,
)
