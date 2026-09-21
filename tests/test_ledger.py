"""M2-D 账本测试：累计、事件留痕、预算熔断。"""
from pathlib import Path

import pytest

from vault_doctor.kernel.transcript import Transcript
from vault_doctor.ledger.budget import BudgetExceeded, TokenLedger


def test_ledger_records_totals_and_events(tmp_path: Path):
    t = Transcript(tmp_path / "s.jsonl")
    ledger = TokenLedger(transcript=t)

    ledger.record({"prompt_tokens": 100, "completion_tokens": 10}, purpose="draft", file="a.md")
    ledger.record({"prompt_tokens": 50, "completion_tokens": 5}, purpose="explain", file="b.md")

    assert ledger.total == 165 and ledger.calls == 2
    events = t.read()
    assert [e["type"] for e in events] == ["llm_call", "llm_call"]
    assert events[0]["purpose"] == "draft" and events[0]["session_total_tokens"] == 110
    assert events[1]["session_total_tokens"] == 165


def test_budget_exceeded_raises_on_next_record(tmp_path: Path):
    ledger = TokenLedger(max_total_tokens=150)
    ledger.record({"prompt_tokens": 100, "completion_tokens": 10})   # 110，未超
    with pytest.raises(BudgetExceeded, match="150"):
        ledger.record({"prompt_tokens": 40, "completion_tokens": 5})  # 155，超
    assert ledger.total == 155
