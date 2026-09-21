# 贡献指南 / Contributing

## 开发环境

需要 Python ≥ 3.12：

```bash
git clone <repo> && cd vault-doctor
pip install -e .
pip install pytest
pytest -v
```

提 PR 前请确保 `pytest -v` 全绿（CI 在 ubuntu + windows 双矩阵上跑同一套测试）。

## 写一条插件规则

任何 pip 包都能注册规则，在你的 `pyproject.toml` 里：

```toml
[project.entry-points."vault_doctor.rules"]
my_rule = "my_package.rules:MY_RULE"
```

`my_package/rules.py`：

```python
from vault_doctor.engine.rules.base import Rule, RuleContext, Violation

def _detect(ctx: RuleContext) -> list[Violation]:
    return [Violation(rule_id="my/rule", severity="warn", file="x.md",
                      message="…", detail={})]

RULE = Rule(id="my/rule", severity="warn", description="…", detect=_detect)
```

规则 id 与内置冲突时内置优先；实现要点见 `src/vault_doctor/engine/rules/base.py` 的 docstring。

## 约定

- 写路径只有一个：`policy/gates.apply_with_gate`——不要绕过它写用户文件
- 检测必须确定性：同一索引 + 同一规则 ⇒ 同一结果（复扫即断言的前提）
- 模型只提议"改什么"（old_text/new_text），定位与校验永远在本地代码
- 全链路 UTF-8；新功能请配测试（fixtures 库在 `tests/fixtures/`）
