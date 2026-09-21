"""M1-C why 命令测试：上下文组装、假客户端解释、缺配置退出码。"""
from pathlib import Path

from vault_doctor.cli.__main__ import main
from vault_doctor.cli.why import build_user_prompt, explain
from vault_doctor.engine.indexer import connect, default_db_path, index_vault
from vault_doctor.engine.rules import run_rules
from vault_doctor.engine.rules.base import RuleContext
from tests.fixtures import build_vault


class FakeClient:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, user: str):
        self.calls.append((system, user))
        return "这是一条人话解释。", {"prompt_tokens": 7, "completion_tokens": 3}


def test_explain_builds_context_and_returns_answer(tmp_path: Path):
    build_vault(tmp_path)
    index_vault(tmp_path)
    conn = connect(default_db_path(tmp_path))
    try:
        violations = run_rules(RuleContext(conn))
    finally:
        conn.close()

    # 首条违规（UTF-8 字节序）：daily/2026-09-18.md 的断链
    first = violations[0]
    assert first.file == "daily/2026-09-18.md"

    fake = FakeClient()
    answer, usage = explain(tmp_path, first, fake)
    assert answer == "这是一条人话解释。"
    system, user = fake.calls[0]
    assert "解释器" in system
    assert "daily/2026-09-18.md" in user
    assert "|" in user  # 文件节选带行号前缀


def test_near_miss_prompt_carries_candidates(tmp_path: Path):
    build_vault(tmp_path)
    index_vault(tmp_path)
    conn = connect(default_db_path(tmp_path))
    try:
        violations = run_rules(RuleContext(conn))
        nm = next(
            v for v in violations
            if v.rule_id == "link/near-miss" and v.detail["target_raw"] == "算法导论2"
        )
        prompt = build_user_prompt(tmp_path, nm, conn)
    finally:
        conn.close()
    assert "改名候选" in prompt
    assert "计算机/算法导论.md" in prompt


def test_cmd_why_missing_config_returns_2(tmp_path: Path, monkeypatch, capsys):
    build_vault(tmp_path)
    monkeypatch.delenv("VAULT_DOCTOR_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # cwd 下无 config.local.toml
    code = main(["why", str(tmp_path)])
    assert code == 2
    assert "config.local.toml" in capsys.readouterr().err
