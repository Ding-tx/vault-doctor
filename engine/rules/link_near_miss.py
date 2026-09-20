"""规则 link/near-miss：断链里疑似"改名/笔误"的子集（warn 级，P0，杀手锏功能）。

对每条断链目标跑 near_miss（编辑距离 ≤ 2），有候选才报告；
消息直接给出最优候选与距离，供人工确认或 M2 agent 起草修复。
"""
from __future__ import annotations

from engine.graph import near_miss
from engine.rules.base import Rule, RuleContext, Violation


def _detect(ctx: RuleContext) -> list[Violation]:
    violations: list[Violation] = []
    rows = ctx.conn.execute(
        "SELECT DISTINCT source, target_raw, line FROM links "
        "WHERE target_resolved IS NULL ORDER BY source, line"
    ).fetchall()
    for source, target_raw, line in rows:
        candidates = near_miss(ctx.conn, target_raw)
        if not candidates:
            continue
        best_path, best_distance = candidates[0]
        violations.append(
            Violation(
                rule_id=RULE.id,
                severity=RULE.severity,
                file=source,
                line=line,
                message=f"疑似改名：「{target_raw}」最接近的现有文件是 {best_path}（编辑距离 {best_distance}）",
                detail={"target_raw": target_raw, "candidates": candidates},
            )
        )
    return violations


RULE = Rule(
    id="link/near-miss",
    severity="warn",
    autofixable=False,
    description="断链目标与现有文件名编辑距离 ≤ 2 时，提示改名/笔误候选",
    detect=_detect,
)
