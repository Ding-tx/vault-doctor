"""CLI 入口：python -m cli <command>。M0 仅提供 scan，其余子命令按里程碑加入。"""
from __future__ import annotations

import argparse
import sys


def _force_utf8_stdout() -> None:
    # Windows 控制台默认 GBK；全链路 UTF-8（DESIGN 第 8 节）从源头处理
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vault-doctor",
        description="markdown 知识库的体检医生：图谱语义层 lint + 修复",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser("scan", help="扫描知识库，输出违规报告")
    scan_p.add_argument("vault", nargs="?", default=".", help="知识库路径（默认当前目录）")
    scan_p.add_argument(
        "--format", choices=("table", "json"), default="table", help="输出格式（默认 table）"
    )
    scan_p.add_argument("--rules", help="只运行指定规则，逗号分隔，如 link/broken,note/orphan")
    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "scan":
        from cli.scan import cmd_scan

        return cmd_scan(args)
    parser.error(f"未知命令：{args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
