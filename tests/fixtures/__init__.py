"""fixtures：代码化的"病态笔记库"（B3），规则引擎（B4）与 CLI（B5）的共享试验场。

单一事实源：库的文件清单 + 每类病例的期望结果都在本模块，
测试断言与未来规则的验收共用同一份期望，防止两处漂移。

病例清单（26 篇笔记 + 4 个资产）：
- 断链 7 条：见 EXPECTED_BROKEN（含 md 相对路径断链、路径型 wikilink 断链）
- near-miss 3 组：算法导论2→算法导论(d=1)、概率论笔记→概率论(d=2)、
  daily/2026-09-17→2026-09-18(d=1)/2026-09-19(d=2)
- 孤儿 4 篇：无入链也无出链
- 未引用资产 3 个：其中 ghost.png 只在代码块里被"引用"，必须识破
- 对照组：hub 页、健康的 md/wikilink/嵌入链接
"""
from __future__ import annotations

from pathlib import Path

NOTES: dict[str, str] = {
    "README.md": "# Vault\n\n[[index]]\n",
    "index.md": "# 知识索引\n\n- [[线性代数]]\n- [[算法导论]]\n- [[术语表]]\n- [周报](项目/周报-0920.md)\n",
    "数学/线性代数.md": "# 线性代数\n\n特征值与特征向量。\n",
    "数学/概率论.md": "# 概率论\n\n贝叶斯公式。\n",
    "数学/复习.md": "# 复习计划\n\n- [[概率论笔记]]\n- [[线性代数]]\n",
    "数学/公式速查.md": "# 公式速查\n\n![[diagram.png]]\n",
    "数学/未整理的草稿.md": "# 草稿\n\n一些没整理的想法。\n",
    "计算机/算法导论.md": "# 算法导论\n\n排序与图算法。\n",
    "计算机/操作系统.md": "# 操作系统\n\n![](../assets/diagram.png)\n\n参见 [[网络]]。\n",
    "计算机/网络.md": "# 网络\n\nTCP/IP 三次握手。参见 [[操作系统]] 与 [[算法导论]]。\n",
    "计算机/示例.md": (
        "# 示例：代码块里的链接不算数\n\n"
        "```md\n![](../assets/ghost.png)\n[[幻影链接]]\n```\n"
        "行内代码也不算：`[[行内幻影]]`\n"
    ),
    "计算机/学习计划.md": "# 学习计划\n\n- [[算法导论2]]\n- [[算法导论]]\n",
    "读书/百年孤独.md": "# 百年孤独\n\n布恩迪亚家族七代人的故事。\n",
    "读书/读书方法.md": "# 读书方法\n\n参见 [[百年孤独]] 的笔记。\n",
    "读书/书单.md": "# 书单\n\n- [[不存在的书]]\n- [读书方法](读书方法.md)\n",
    "读书/孤岛笔记.md": "# 孤岛\n\n没人链接我，我也不链接别人。\n",
    "项目/vault-doctor笔记.md": (
        "---\ntitle: vault-doctor 开发笔记\ndate: 2026-09-20\n---\n"
        "# vault-doctor\n\n- [[算法导论]]\n- [操作系统](../计算机/操作系统.md)\n"
    ),
    "项目/旧项目.md": "# 旧项目\n\n[[已删除的页面]]\n",
    "项目/迁移记录.md": "# 迁移记录\n\n[丢失的文档](../gone.md)\n[旧图](./missing.png)\n",
    "项目/周报-0920.md": (
        "---\ntitle: 周报\ndate: 2026-09-20\n---\n"
        "# 周报\n\n[算法笔记](../计算机/算法导论.md)\n"
    ),
    "daily/2026-09-18.md": "# 0918\n\n[[daily/2026-09-17]]\n",
    "daily/2026-09-19.md": "# 0919\n\n[[index]]\n",
    "daily/2026-09-20.md": "# 0920\n\n[[index]]\n",
    "misc/术语表.md": "# 术语表\n\n常见术语的解释。\n",
    "misc/ideas.md": "# Ideas\n\n- 想法一\n- 想法二\n",
    "misc/random-thoughts.md": "# 随想\n\n碎片记录。\n",
}

ASSETS: list[str] = [
    "assets/diagram.png",
    "assets/old-photo.jpg",
    "assets/screenshot-2026.png",
    "assets/ghost.png",
]

# ---- 期望结果（B4 规则的验收基准）----

EXPECTED_BROKEN: set[tuple[str, str]] = {
    ("读书/书单.md", "不存在的书"),
    ("计算机/学习计划.md", "算法导论2"),
    ("数学/复习.md", "概率论笔记"),
    ("项目/旧项目.md", "已删除的页面"),
    ("项目/迁移记录.md", "../gone.md"),
    ("项目/迁移记录.md", "./missing.png"),
    ("daily/2026-09-18.md", "daily/2026-09-17"),
}

EXPECTED_ORPHANS: set[str] = {
    "数学/未整理的草稿.md",
    "读书/孤岛笔记.md",
    "misc/ideas.md",
    "misc/random-thoughts.md",
}

EXPECTED_UNREFERENCED_ASSETS: set[str] = {
    "assets/old-photo.jpg",
    "assets/screenshot-2026.png",
    "assets/ghost.png",
}


def build_vault(root: Path) -> Path:
    """把 fixtures 物化到目标目录（已存在的同名文件会被覆盖）。"""
    root.mkdir(parents=True, exist_ok=True)
    for relpath, text in NOTES.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for relpath in ASSETS:
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture-asset")
    return root


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tests/fixtures/vault")
    build_vault(target)
    print(f"fixtures 已物化到 {target.resolve()}：{len(NOTES)} 篇笔记 + {len(ASSETS)} 个资产")
