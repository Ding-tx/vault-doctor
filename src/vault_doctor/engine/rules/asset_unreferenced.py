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
                    message="未引用资产：没有任何笔记链接到它",
                    detail={},
                )
            )
    return violations


RULE = Rule(
    id="asset/unreferenced",
    severity="warn",
    autofixable=False,
    description="检测从未被引用的图片等资产文件",
    detect=_detect,
)
