"""CLI 入口：`vault-doctor <command>`（安装后）或 `python -m vault_doctor <command>`。M0 仅提供 scan。"""
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
        "--format", choices=("table", "json", "sarif"), default="table", help="输出格式（默认 table）"
    )
    scan_p.add_argument("-o", "--output", help="写入文件而非 stdout（json/sarif 常用）")
    scan_p.add_argument("--rules", help="只运行指定规则，逗号分隔，如 link/broken,note/orphan")

    sub.add_parser("rules", help="列出已注册的规则（内置 + 插件）")

    why_p = sub.add_parser("why", help="用 LLM 把一条违规翻译成人话（首次 API 调用）")
    why_p.add_argument("vault", nargs="?", default=".", help="知识库路径（默认当前目录）")
    why_p.add_argument("--rule", help="只看指定规则，如 link/near-miss")
    why_p.add_argument("--index", type=int, help="选第 N 条违规（默认 1）")
    why_p.add_argument("--config", help="配置文件路径（默认找 config.local.toml 或环境变量）")

    snap_p = sub.add_parser("snapshots", help="列出可回滚的修复快照")
    snap_p.add_argument("vault", nargs="?", default=".", help="知识库路径（默认当前目录）")

    rb_p = sub.add_parser("rollback", help="回滚一次修复会话")
    rb_p.add_argument("session_id", help="快照 session id（vault-doctor snapshots 查看）")
    rb_p.add_argument("vault", nargs="?", default=".", help="知识库路径（默认当前目录）")
    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "scan":
        from vault_doctor.cli.scan import cmd_scan

        return cmd_scan(args)
    if args.command == "rules":
        from vault_doctor.cli.rules import cmd_rules

        return cmd_rules(args)
    if args.command == "why":
        from vault_doctor.cli.why import cmd_why

        return cmd_why(args)
    if args.command == "snapshots":
        from vault_doctor.cli.rollback import cmd_snapshots

        return cmd_snapshots(args)
    if args.command == "rollback":
        from vault_doctor.cli.rollback import cmd_rollback

        return cmd_rollback(args)
    parser.error(f"未知命令：{args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
