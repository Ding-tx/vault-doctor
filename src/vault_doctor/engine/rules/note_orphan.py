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
                    message="孤儿笔记：没有任何笔记链接它，它也没链接别人",
                    detail={},
                )
            )
    return violations


RULE = Rule(
    id="note/orphan",
    severity="warn",
    autofixable=False,
    label="孤儿笔记",
    description="没有任何笔记链接它、它也不链接别人——写完就孤零零躺在库里，很容易永远想不起来，建议归档或补几个链接",
    detect=_detect,
)
