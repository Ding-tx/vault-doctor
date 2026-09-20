"""规则 link/broken：解析不到库内文件的链接（error 级，P0）。"""
from __future__ import annotations

from engine.rules.base import Rule, RuleContext, Violation

_DISPLAY = {"wikilink": "[[{t}]]", "wikilink-embed": "![[{t}]]", "md": "({t})", "md-embed": "!({t})"}


def _detect(ctx: RuleContext) -> list[Violation]:
    rows = ctx.conn.execute(
        "SELECT source, target_raw, line, kind FROM links "
        "WHERE target_resolved IS NULL ORDER BY source, line"
    ).fetchall()
    return [
        Violation(
            rule_id=RULE.id,
            severity=RULE.severity,
            file=source,
            line=line,
            message=f"断链：{_DISPLAY.get(kind, '{t}').format(t=target_raw)} 解析不到库内文件",
            detail={"target_raw": target_raw, "kind": kind},
        )
        for source, target_raw, line, kind in rows
    ]


RULE = Rule(
    id="link/broken",
    severity="error",
    autofixable=False,
    description="检测 [[wikilink]] 与 [md](相对路径) 中无法解析到库内文件的链接",
    detect=_detect,
)
