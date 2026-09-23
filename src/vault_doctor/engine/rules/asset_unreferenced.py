"""规则 asset/unreferenced：没有被任何笔记引用的资产（warn 级，P0）。"""
from __future__ import annotations

from vault_doctor.engine.graph import who_links_to
from vault_doctor.engine.rules.base import Rule, RuleContext, Violation


def _detect(ctx: RuleContext) -> list[Violation]:
    violations: list[Violation] = []
    for path in ctx.asset_paths():
        if not who_links_to(ctx.conn, path):
            violations.append(
                Violation(
                    rule_id=RULE.id,
                    severity=RULE.severity,
                    file=path,
                    line=None,
                    message="未引用附件：没有任何笔记引用它",
                    detail={},
                )
            )
    return violations


RULE = Rule(
    id="asset/unreferenced",
    severity="warn",
    autofixable=False,
    label="未引用附件",
    description="没有任何笔记引用的图片等附件——可能是删笔记时留下的遗留文件，白占空间，可考虑清理",
    detect=_detect,
)
