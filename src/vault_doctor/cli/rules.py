"""rules 子命令：列出注册表里的内置与插件规则。"""
from __future__ import annotations

import argparse

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from vault_doctor.engine.rules import BUILTIN_RULES, REGISTRY


def cmd_rules(args: argparse.Namespace) -> int:
    console = Console()
    console.print(f"[bold]vault-doctor[/bold] · 已注册 {len(REGISTRY)} 条规则")
    table = Table()
    for col in ("规则 id", "严重度", "可自动修复", "来源", "说明"):
        table.add_column(col)
    for rule_id, rule in REGISTRY.items():
        source = "内置" if rule_id in BUILTIN_RULES else "插件"
        table.add_row(
            escape(rule_id),
            rule.severity,
            "是" if rule.autofixable else "否",
            source,
            escape(rule.description or ""),
        )
    console.print(table)
    return 0
