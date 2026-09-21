"""权限闸门（M2-B）：diff 预览 + 人工确认，RULES 规则 6 的机制化。

写用户文件的唯一合法路径：apply_with_gate ——
逐文件渲染统一 diff，y/n/a/q 确认（a=本会话全放行，q=全部取消），
批准的文件先快照再应用；任何情况下都不存在绕过本函数的写路径。
input_fn / console 可注入，全自动可测。
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.text import Text

from vault_doctor.engine.patches import (
    ApplyResult,
    Patch,
    PatchError,
    apply_patches,
    apply_to_text,
    detect_conflicts,
)
from vault_doctor.policy.snapshot import Snapshot, create_snapshot


@dataclass
class GateOutcome:
    snapshot: Snapshot | None = None
    approved: list[Patch] = field(default_factory=list)
    skipped: list[Patch] = field(default_factory=list)
    apply_result: ApplyResult | None = None

    @property
    def applied_files(self) -> list[str]:
        if not self.apply_result:
            return []
        return [f.file for f in self.apply_result.files if f.ok]


def _print_diff(console: Console, before: str, after: str, relpath: str) -> None:
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{relpath}",
        tofile=f"b/{relpath}",
    )
    for line in diff:
        line = line.rstrip("\r\n")
        # Text 对象不经 markup 解析——文件内容里的 [] 不会被 rich 误当标记
        if line.startswith("+") and not line.startswith("+++"):
            console.print(Text(line, style="green"))
        elif line.startswith("-") and not line.startswith("---"):
            console.print(Text(line, style="red"))
        else:
            console.print(Text(line))


def _ask(console: Console, input_fn) -> str:
    while True:
        try:
            answer = input_fn("应用？[y]是 [n]跳过 [a]本会话全部应用 [q]全部取消: ").strip().lower()
        except EOFError:
            return "q"
        if answer in ("y", "n", "a", "q"):
            return answer
        console.print("[yellow]请输入 y / n / a / q[/yellow]")


def apply_with_gate(
    vault: Path,
    patches: list[Patch],
    *,
    assume_yes: bool = False,
    input_fn=input,
    console: Console | None = None,
) -> GateOutcome:
    """唯一写路径：确认 → 快照 → 应用。q 取消一切（含已按 y 的文件）。"""
    console = console or Console()
    outcome = GateOutcome()

    conflicts = detect_conflicts(patches)
    conflicted_files = {a.file for a, _ in conflicts} | {b.file for _, b in conflicts}
    by_file: dict[str, list[Patch]] = {}
    for p in patches:
        if p.file in conflicted_files:
            outcome.skipped.append(p)
            continue
        by_file.setdefault(p.file, []).append(p)
    for a, b in conflicts:
        console.print(f"[red]冲突，跳过[/red]：{a.file} 的补丁区间重叠（{a.rule_id} × {b.rule_id}）")

    always = assume_yes
    approved: list[Patch] = []
    for relpath, group in sorted(by_file.items()):
        path = vault / relpath
        try:
            before = path.read_text(encoding="utf-8", errors="replace")
            after = apply_to_text(before, group)
        except (OSError, PatchError) as exc:
            console.print(f"[red]跳过[/red] {relpath}：{exc}")
            outcome.skipped.extend(group)
            continue

        if not always:
            console.print(f"\n[bold]提议[/bold]：{relpath} · {len(group)} 处修改 · 来源 {group[0].rule_id or '未知'}")
            if group[0].rationale:
                console.print(f"理由：{group[0].rationale}")
            _print_diff(console, before, after, relpath)
            answer = _ask(console, input_fn)
            if answer == "n":
                outcome.skipped.extend(group)
                continue
            if answer == "q":
                outcome.skipped.extend(p for p in patches if p not in approved and p not in outcome.skipped)
                console.print("[yellow]已全部取消，未写入任何文件[/yellow]")
                return outcome
            if answer == "a":
                always = True
        approved.extend(group)

    if not approved:
        return outcome

    outcome.snapshot = create_snapshot(vault, sorted({p.file for p in approved}))
    outcome.approved = approved
    outcome.apply_result = apply_patches(vault, approved, write=True)
    console.print(
        f"[green]已应用[/green] {len(outcome.applied_files)} 个文件 · 快照 [bold]{outcome.snapshot.session_id}[/bold]"
        f"（回滚：vault-doctor rollback {outcome.snapshot.session_id} <vault>）"
    )
    return outcome
