"""规则 link/broken：解析不到库内文件的链接（error 级，P0）。"""
from __future__ import annotations

from vault_doctor.engine.rules.base import Rule, RuleContext, Violation

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
            message=f"断链：{_DISPLAY.get(kind, '{t}').format(t=target_raw)} 指向的文件不存在，点开会落空",
            detail={"target_raw": target_raw, "kind": kind},
        )
        for source, target_raw, line, kind in rows
    ]


RULE = Rule(
    id="link/broken",
    severity="error",
    autofixable=False,
    label="断链",
    description="链接指向的文件不存在，点开会落空——多半是文件被删除、移动或改名后，笔记里的引用没跟上",
    detect=_detect,
)
