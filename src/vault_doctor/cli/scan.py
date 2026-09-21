"""scan 子命令：建索引 → 跑规则 → 渲染（table/json）→ CI 友好退出码。

退出码：0 无 error 级违规；1 存在 error 级违规；2 路径/用法错误。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from vault_doctor.cli import sarif
from vault_doctor.engine.indexer import connect, default_db_path, index_vault
from vault_doctor.engine.rules import run_rules
from vault_doctor.engine.rules.base import RuleContext, Violation

_SEVERITY_STYLE = {"error": "[red]error[/red]", "warn": "[yellow]warn[/yellow]", "info": "[cyan]info[/cyan]"}


def _collect(vault: Path, rule_ids: list[str] | None):
    stats = index_vault(vault)
    conn = connect(default_db_path(vault))
    try:
        notes = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        assets = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        violations = run_rules(RuleContext(conn), rule_ids)
    finally:
        conn.close()
    return stats, notes, assets, violations


def cmd_scan(args: argparse.Namespace) -> int:
    vault = Path(args.vault)
    if not vault.is_dir():
        print(f"错误：路径不存在或不是目录：{vault}", file=sys.stderr)
        return 2

    rule_ids = [r.strip() for r in args.rules.split(",") if r.strip()] if args.rules else None
    try:
        stats, notes, assets, violations = _collect(vault, rule_ids)
    except KeyError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    if args.format in ("json", "sarif"):
        if args.format == "json":
            payload = json.dumps(
                {
                    "vault": str(vault),
                    "notes": notes,
                    "assets": assets,
                    "index_elapsed_seconds": round(stats.elapsed, 3),
                    "violations": [v.model_dump() for v in violations],
                },
                ensure_ascii=False,
                indent=2,
            )
        else:
            payload = sarif.dumps(violations)
        if args.output:
            Path(args.output).write_text(payload, encoding="utf-8")
        else:
            print(payload)
    else:
        render_table(vault, notes, assets, stats.elapsed, violations)

    return 1 if any(v.severity == "error" for v in violations) else 0


def render_table(
    vault: Path,
    notes: int,
    assets: int,
    elapsed: float,
    violations: list[Violation],
    console: Console | None = None,
) -> None:
    console = console or Console()
    console.print(f"[bold]vault-doctor[/bold] · 扫描 [underline]{escape(str(vault))}[/underline]")
    console.print(f"{notes} 篇笔记 · {assets} 个资产 · 索引耗时 {elapsed:.2f}s")

    if not violations:
        console.print("[green]未发现违规[/green]")
        return

    table = Table()
    for col in ("严重度", "规则", "位置", "说明"):
        table.add_column(col)
    for v in violations:
        loc = f"{v.file}:{v.line}" if v.line else v.file
        # 断链消息含 [[...]]，必须转义，否则会被 rich 当作样式标记
        table.add_row(
            _SEVERITY_STYLE.get(v.severity, v.severity),
            v.rule_id,
            escape(loc),
            escape(v.message),
        )
    console.print(table)

    errors = sum(1 for v in violations if v.severity == "error")
    warns = sum(1 for v in violations if v.severity == "warn")
    infos = len(violations) - errors - warns
    console.print(
        f"共 {len(violations)} 条：[red]{errors} error[/red] · [yellow]{warns} warn[/yellow] · {infos} info"
    )
