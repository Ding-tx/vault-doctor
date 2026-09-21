"""SARIF v2.1.0 输出：把违规清单转成 GitHub Code Scanning 可消费的格式。

约定：
- 等级映射 error→error，warn→warning，info→note
- 位置用 POSIX 相对 URI + uriBaseId=%SRCROOT%（代码扫描在仓库根下解析）
- results 里出现过的 ruleId 必须在 tool.driver.rules 有描述（GitHub 摄取要求）
"""
from __future__ import annotations

import json

import vault_doctor
from vault_doctor.engine.rules import REGISTRY
from vault_doctor.engine.rules.base import Violation

_LEVEL = {"error": "error", "warn": "warning", "info": "note"}


def to_sarif(violations: list[Violation], registry: dict | None = None) -> dict:
    rules = registry if registry is not None else REGISTRY
    used_rule_ids: list[str] = []
    for v in violations:
        if v.rule_id not in used_rule_ids:
            used_rule_ids.append(v.rule_id)
    return {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "vault-doctor",
                        "version": vault_doctor.__version__,
                        "informationUri": "https://github.com/vault-doctor/vault-doctor",
                        "rules": [
                            {
                                "id": rid,
                                "shortDescription": {
                                    "text": (rules[rid].description if rid in rules else None) or rid
                                },
                            }
                            for rid in used_rule_ids
                        ],
                    }
                },
                "results": [_result(v) for v in violations],
            }
        ],
    }


def _result(v: Violation) -> dict:
    physical_location: dict = {
        "artifactLocation": {"uri": v.file, "uriBaseId": "%SRCROOT%"}
    }
    if v.line is not None:
        physical_location["region"] = {"startLine": max(v.line, 1)}
    return {
        "ruleId": v.rule_id,
        "level": _LEVEL.get(v.severity, "note"),
        "message": {"text": v.message},
        "locations": [{"physicalLocation": physical_location}],
    }


def dumps(violations: list[Violation], registry: dict | None = None) -> str:
    return json.dumps(to_sarif(violations, registry), ensure_ascii=False, indent=2)
