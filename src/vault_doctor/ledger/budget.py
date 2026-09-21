"""token 账本（M2-D）：会话内累计用量、超预算熔断、事件流留痕。

预算语义：max_total_tokens 按 prompt+completion 之和计算；
超限在下一次 record 时抛 BudgetExceeded（当前那次调用已发生，后续调用被阻止）。
"""
from __future__ import annotations

from vault_doctor.kernel.transcript import Transcript


class BudgetExceeded(RuntimeError):
    pass


class TokenLedger:
    def __init__(
        self,
        max_total_tokens: int | None = None,
        transcript: Transcript | None = None,
    ):
        self.max_total_tokens = max_total_tokens
        self.transcript = transcript
        self.total = 0
        self.calls = 0

    def record(self, usage: dict, **event_fields) -> None:
        prompt = usage.get("prompt_tokens") or 0
        completion = usage.get("completion_tokens") or 0
        self.total += prompt + completion
        self.calls += 1
        if self.transcript is not None:
            self.transcript.append(
                {
                    "type": "llm_call",
                    "usage": usage,
                    "session_total_tokens": self.total,
                    **event_fields,
                }
            )
        if self.max_total_tokens is not None and self.total > self.max_total_tokens:
            raise BudgetExceeded(
                f"会话 token 预算已耗尽：{self.total} > {self.max_total_tokens}"
            )
