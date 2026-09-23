"""修复编排器：起草 → 闸门 → 应用 → 复扫验证。

闭环语义：修复前记录 (文件, 目标) 违规集合，应用后全量复扫 link/broken，
仍在集合内的记为"残留"——复扫即断言，模型说"修好了"不算数。
全程写 transcript 事件流、经 ledger 记账（预算熔断在起草层生效）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import vault_doctor
from rich.console import Console

from vault_doctor.agent.drafter import draft_file_patches, merge_usage
from vault_doctor.engine.indexer import connect, default_db_path, index_vault
from vault_doctor.engine.patches import Patch
from vault_doctor.engine.rules import run_rules
from vault_doctor.engine.rules.base import RuleContext
from vault_doctor.kernel.transcript import Transcript
from vault_doctor.ledger.budget import TokenLedger
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
    transcript: Transcript | None = None,
    ledger: TokenLedger | None = None,
) -> FixReport:
    console = console or Console()
    if rule not in SUPPORTED_RULES:
        raise ValueError(f"当前仅支持规则 {sorted(SUPPORTED_RULES)}，收到 {rule!r}")
    if transcript is not None:
        transcript.append(
            {"type": "session_start", "command": "fix", "rule": rule,
             "vault": str(vault), "version": vault_doctor.__version__}
        )

    report = FixReport()
    index_vault(vault)
    conn = connect(default_db_path(vault))
    try:
        violations = run_rules(RuleContext(conn), [rule])
    finally:
        conn.close()
    if not violations:
        if transcript is not None:
            transcript.append({"type": "session_end", "ok": True, "note": "无违规"})
        return report

    before_pairs = {(v.file, v.detail["target_raw"]) for v in violations}
    report.before = len(before_pairs)

    by_file: dict[str, list] = {}
    for v in violations:
        by_file.setdefault(v.file, []).append(v)

    all_patches: list[Patch] = []
    for relpath, file_violations in sorted(by_file.items())[:limit]:
        report.files_attempted += 1
        patches, usage = draft_file_patches(
            client, vault, relpath, file_violations, rule, ledger=ledger
        )
        merge_usage(report.usage, usage)
        if transcript is not None:
            transcript.append(
                {"type": "draft", "file": relpath, "patches": [p.model_dump() for p in patches]}
            )
        if patches:
            console.print(f"[dim]起草[/dim] {relpath}：{len(patches)} 个补丁")
            all_patches.extend(patches)
    report.patches_drafted = len(all_patches)

    outcome: GateOutcome | None = None
    if all_patches:
        on_decision = (
            (lambda f, d: transcript.append({"type": "gate_decision", "file": f, "decision": d}))
            if transcript is not None
            else None
        )
        outcome = apply_with_gate(
            vault, all_patches, assume_yes=assume_yes, input_fn=input_fn,
            console=console, on_decision=on_decision,
        )
        report.applied_files = outcome.applied_files
        if outcome.snapshot:
            report.snapshot_id = outcome.snapshot.session_id
        if transcript is not None:
            transcript.append(
                {"type": "applied", "files": report.applied_files, "snapshot": report.snapshot_id}
            )

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
    if transcript is not None:
        transcript.append(
            {"type": "verify", "before": report.before, "cleared": report.cleared,
             "remaining": report.remaining_pairs, "usage": report.usage}
        )
        transcript.append({"type": "session_end", "ok": report.remaining == 0})
    return report
