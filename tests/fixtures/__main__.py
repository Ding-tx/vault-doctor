"""python -m tests.fixtures <target>：把病态测试库物化到目标目录。"""
import sys
from pathlib import Path

from tests.fixtures import ASSETS, NOTES, build_vault

target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tests/fixtures/vault")
build_vault(target)
print(f"fixtures 已物化到 {target.resolve()}：{len(NOTES)} 篇笔记 + {len(ASSETS)} 个资产")
