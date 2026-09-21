"""修复编排器（M2-C）：起草 → 闸门 → 应用 → 复扫验证。

闭环语义：修复前记录 (文件, 目标) 违规集合，应用后全量复扫 link/broken，
仍在集合内的记为"残留"——复扫即断言，模型说"修好了"不算数。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console

from vault_doctor.agent.drafter import draft_file_patches, merge_usage
from vault_doctor.engine.indexer import connect, default_db_path, index_vault
from vault_doctor.engine.patches import Patch
from vault_doctor.engine.rules import run_rules
from vault_doctor.engine.rules.base import RuleContext
from vault_doctor.policy.gates import GateOutcome, apply_with_gate

SUPPORTED_RULES = {"link/near-miss"}


@dataclass
class FixReport:
    files_attempted: int = 0
    patches_drafted: int = 0
    applied_files: list[str] = field(default_factory=list)
    before: int = 0
    cleared: int = 0
    remaining_pairs: list[tuple[str, str]] = field(default_factory=list)
    snapshot_id: str | None = None
    usage: dict = field(default_factory=dict)

    @property
    def remaining(self) -> int:
        return len(self.remaining_pairs)


def run_fix(
    vault: Path,
    client,
    *,
    rule: str = "link/near-miss",
    limit: int = 5,
    assume_yes: bool = False,
    input_fn=input,
    console: Console | None = None,
) -> FixReport:
    console = console or Console()
    if rule not in SUPPORTED_RULES:
        raise ValueError(f"M2-C 仅支持 {sorted(SUPPORTED_RULES)}，收到 {rule!r}")

    report = FixReport()
    index_vault(vault)
    conn = connect(default_db_path(vault))
    try:
        violations = run_rules(RuleContext(conn), [rule])
    finally:
        conn.close()
    if not violations:
        return report

    before_pairs = {(v.file, v.detail["target_raw"]) for v in violations}
    report.before = len(before_pairs)

    by_file: dict[str, list] = {}
    for v in violations:
        by_file.setdefault(v.file, []).append(v)

    all_patches: list[Patch] = []
    for relpath, file_violations in sorted(by_file.items())[:limit]:
        report.files_attempted += 1
        patches, usage = draft_file_patches(client, vault, relpath, file_violations, rule)
        merge_usage(report.usage, usage)
        if patches:
            console.print(f"[dim]起草[/dim] {relpath}：{len(patches)} 个补丁")
            all_patches.extend(patches)
    report.patches_drafted = len(all_patches)

    outcome: GateOutcome | None = None
    if all_patches:
        outcome = apply_with_gate(
            vault, all_patches, assume_yes=assume_yes, input_fn=input_fn, console=console
        )
        report.applied_files = outcome.applied_files
        if outcome.snapshot:
            report.snapshot_id = outcome.snapshot.session_id

    # 复扫验证（闭环断言）
    index_vault(vault)
    conn = connect(default_db_path(vault))
    try:
        after = run_rules(RuleContext(conn), ["link/broken"])
    finally:
        conn.close()
    after_pairs = {(v.file, v.detail["target_raw"]) for v in after}
    report.remaining_pairs = sorted(before_pairs & after_pairs)
    report.cleared = report.before - len(report.remaining_pairs)
    return report
