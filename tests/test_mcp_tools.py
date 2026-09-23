"""M3-A MCP 只读工具测试：纯引擎函数（不依赖 mcp SDK 安装）。"""
from pathlib import Path

import pytest

from vault_doctor.mcp import tools as T
from tests.fixtures import build_vault


def test_scan_vault_and_rule_filter(tmp_path: Path):
    build_vault(tmp_path)
    report = T.scan_vault(tmp_path)
    assert report["notes"] == 26
    assert len(report["violations"]) == 17

    broken = T.scan_vault(tmp_path, "link/broken")
    assert len(broken["violations"]) == 7
    assert all(v["rule_id"] == "link/broken" for v in broken["violations"])
    # near-miss 违规的 detail 带改名候选（外部 agent 据此提议修复）
    near = T.scan_vault(tmp_path, "link/near-miss")
    assert near["violations"][0]["detail"]["candidates"]


def test_outgoing_and_backlinks_roundtrip(tmp_path: Path):
    build_vault(tmp_path)
    links = T.outgoing_links(tmp_path, "数学/复习.md")
    assert {"target_raw": "概率论笔记"} in ({"target_raw": l["target_raw"]} for l in links)

    # 结构性往返：任取一条可解析出链，反向链接里必能查到来源
    resolved = [l for l in links if l["target_resolved"]]
    assert resolved
    back = T.backlinks(tmp_path, resolved[0]["target_resolved"])
    assert any(b["source"] == "数学/复习.md" for b in back)


def test_near_miss_candidates(tmp_path: Path):
    build_vault(tmp_path)
    cands = T.near_miss_candidates(tmp_path, "概率论笔记")
    assert cands[0] == {"path": "数学/概率论.md", "distance": 2}


def test_search_notes_chinese_and_short_query(tmp_path: Path):
    build_vault(tmp_path)
    hits = T.search_notes(tmp_path, "概率论")
    assert any(h["path"] == "数学/概率论.md" for h in hits)
    assert all("snippet" in h and "title" in h for h in hits)
    # trigram 下限：不足 3 字符的查询静默返回空（不报错，agent 可换关键词）
    assert T.search_notes(tmp_path, "ab") == []


def test_invalid_vault_raises(tmp_path: Path):
    with pytest.raises(ValueError, match="路径不存在"):
        T.scan_vault(tmp_path / "不存在")
