"""规则协议：Violation / RuleContext / Rule（DESIGN.md 4.1）。

- Violation 用 pydantic 建模，天然可 JSON 序列化（B5 的 --format json 直接复用）
- 每条规则一个模块，注册制（engine/rules/__init__.py）
- M0 所有规则 autofixable=False：确定性引擎只检测，修复归 agent（M2）
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, Field

SEVERITIES = ("error", "warn", "info")


class Violation(BaseModel):
    rule_id: str
    severity: str
    file: str
    line: int | None = None
    message: str
    detail: dict = Field(default_factory=dict)


@dataclass
class RuleContext:
    """规则拿到的世界：一份建好索引的 SQLite 连接。"""

    conn: sqlite3.Connection

    def note_paths(self) -> list[str]:
        return [row[0] for row in self.conn.execute("SELECT path FROM files ORDER BY path")]

    def asset_paths(self) -> list[str]:
        return [row[0] for row in self.conn.execute("SELECT path FROM assets ORDER BY path")]


@dataclass
class Rule:
    id: str
    severity: str
    detect: Callable[[RuleContext], list[Violation]]
    autofixable: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"规则 {self.id} 的 severity 非法：{self.severity}")
