"""CLI 入口：`vault-doctor <command>`（安装后）或 `python -m vault_doctor <command>`。"""
from __future__ import annotations

import argparse
import sys

from vault_doctor import __version__

_EPILOG = """示例：
  vault-doctor scan .                        # 扫描当前目录（只读）
  vault-doctor scan . --severity error --top 20
  vault-doctor scan . --format sarif -o out.sarif
  vault-doctor why . --index 1               # LLM 解释一条违规（需配置 API key）
  vault-doctor fix .                         # agent 修复（diff 闸门 + 快照 + 复扫验证）
  vault-doctor snapshots . / rollback <sid> ."""


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
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"vault-doctor {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser("scan", help="扫描知识库，输出违规报告")
    scan_p.add_argument("vault", nargs="?", default=".", help="知识库路径（默认当前目录）")
    scan_p.add_argument(
        "--format", choices=("table", "json", "sarif"), default="table", help="输出格式（默认 table）"
    )
    scan_p.add_argument("-o", "--output", help="写入文件而非 stdout（json/sarif 常用）")
    scan_p.add_argument("--rules", help="只运行指定规则，逗号分隔，如 link/broken,note/orphan")
    scan_p.add_argument("--severity", choices=("error", "warn", "info"), help="只显示指定严重度")
    scan_p.add_argument("--top", type=int, default=50, help="表格最多显示条数（默认 50；汇总行统计全量）")

    sub.add_parser("rules", help="列出已注册的规则（内置 + 插件）")

    why_p = sub.add_parser("why", help="用 LLM 把一条违规翻译成人话（需配置 API key）")
    why_p.add_argument("vault", nargs="?", default=".", help="知识库路径（默认当前目录）")
    why_p.add_argument("--rule", help="只看指定规则，如 link/near-miss")
    why_p.add_argument("--index", type=int, help="选第 N 条违规（默认 1）")
    why_p.add_argument("--config", help="配置文件路径（默认找 config.local.toml 或环境变量）")

    snap_p = sub.add_parser("snapshots", help="列出可回滚的修复快照")
    snap_p.add_argument("vault", nargs="?", default=".", help="知识库路径（默认当前目录）")

    rb_p = sub.add_parser("rollback", help="回滚一次修复会话")
    rb_p.add_argument("session_id", help="快照 session id（vault-doctor snapshots 查看）")
    rb_p.add_argument("vault", nargs="?", default=".", help="知识库路径（默认当前目录）")

    fix_p = sub.add_parser("fix", help="起草并应用修复（当前仅 link/near-miss；diff 闸门 + 快照 + 复扫验证）")
    fix_p.add_argument("vault", nargs="?", default=".", help="知识库路径（默认当前目录）")
    fix_p.add_argument("--rule", default="link/near-miss", help="修复的规则（当前仅 link/near-miss）")
    fix_p.add_argument("--limit", type=int, default=5, help="最多处理多少个文件（默认 5）")
    fix_p.add_argument("--yes", action="store_true", help="跳过人工确认（仍会先快照）")
    fix_p.add_argument("--config", help="配置文件路径（默认找 config.local.toml 或环境变量）")

    ui_p = sub.add_parser("ui", help="启动本地 Web 图形界面（浏览器打开，仅本机可访问）")
    ui_p.add_argument("vault", nargs="?", default=".", help="知识库路径（默认当前目录）")
    ui_p.add_argument("--port", type=int, default=8765, help="监听端口（默认 8765，仅绑定 127.0.0.1）")
    ui_p.add_argument("--no-open", action="store_true", help="不自动打开浏览器")

    mcp_p = sub.add_parser(
        "mcp", help="以 MCP server 运行（stdio 只读图谱工具，供 Claude Code / Cursor 等 agent 调用）"
    )
    mcp_p.add_argument("vault", nargs="?", default=".", help="知识库路径（默认当前目录）")
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
    if args.command == "fix":
        from vault_doctor.cli.fix import cmd_fix

        return cmd_fix(args)
    if args.command == "ui":
        from vault_doctor.cli.ui import cmd_ui

        return cmd_ui(args)
    if args.command == "mcp":
        from vault_doctor.cli.mcp import cmd_mcp

        return cmd_mcp(args)
    parser.error(f"未知命令：{args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
