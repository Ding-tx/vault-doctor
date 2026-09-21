"""规则 note/orphan：无入链也无出链的笔记（warn 级，P0）。"""
from __future__ import annotations

from vault_doctor.engine.graph import links_of, who_links_to
from vault_doctor.engine.rules.base import Rule, RuleContext, Violation


def _detect(ctx: RuleContext) -> list[Violation]:
    violations: list[Violation] = []
    for path in ctx.note_paths():
        if not links_of(ctx.conn, path) and not who_links_to(ctx.conn, path):
            violations.append(
                Violation(
                    rule_id=RULE.id,
                    severity=RULE.severity,
                    file=path,
                    line=None,
                    message="孤儿笔记：无入链也无出链",
                    detail={},
                )
            )
    return violations


RULE = Rule(
    id="note/orphan",
    severity="warn",
    autofixable=False,
    description="检测既没有被链接也没有链接别人的笔记",
    detect=_detect,
)
