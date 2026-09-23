"""事件流：append-only JSONL，fix/why 会话的完整记录，也是将来会话重放的数据源。

事件约定（type 字段）：
- session_start / session_end —— 会话边界，携带 command/vault/version/结果
- llm_call —— 一次模型调用（purpose=draft|explain、file、usage、会话累计）
- draft / draft_error —— 起草产物（补丁列表）/ 起草失败
- gate_decision —— 闸门决定（y|n|a|q|auto，文件级）
- applied —— 应用结果（文件清单、快照 id）
- verify —— 复扫验证（before/cleared/remaining）
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path


class Transcript:
    """append-only JSONL 转录。坏行在读取时跳过并计数——转录损坏不拖垮回放。"""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.skipped_lines = 0

    def append(self, event: dict) -> None:
        event = dict(event)
        event.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    def read(self) -> list[dict]:
        self.skipped_lines = 0
        events: list[dict] = []
        if not self.path.is_file():
            return events
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                self.skipped_lines += 1
        return events


def new_session_id() -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
