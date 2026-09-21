# Changelog

## v0.3.0 (2026-09-21)

- **agent 修复循环**：`vault-doctor fix`——LLM 起草补丁（本地定位、前置条件校验）→ diff 预览 + y/n/a/q 人工闸门 → 自动快照 → 应用 → **复扫验证**（违规 N → 残留 M）
- **快照与回滚**：`vault-doctor snapshots` / `rollback <sid>`，修复完全可逆
- **会话转录**：`.vaultdoctor/transcripts/<sid>.jsonl`——每次 LLM 调用、每个闸门决定、复扫结果全程留痕（append-only，可审计）
- **token 预算熔断**：配置 `max_session_tokens`，超限当场停止
- 文本补丁模型：字符区间 + `expected_old` 前置条件 + 同文件冲突整文件跳过

## v0.2.0 (2026-09-21)

- **规则插件 SDK**：entry_points 组 `vault_doctor.rules`，第三方包可注册规则（内置优先，坏插件跳过告警）；`vault-doctor rules` 命令
- **SARIF 2.1.0 输出**：`--format sarif` / `-o`，GitHub Code Scanning 原生消费；仓库根 `action.yml` 复合 Action
- **`why` 命令**：LLM 把一条违规翻译成人话（首次 API 调用）；配置三来源（`--config` > 环境变量 > `config.local.toml`）；base_url 安全校验（仅 http/https，拒绝环回/私有/保留地址）

## v0.1.0 (2026-09-21)

- 确定性引擎：SQLite 增量索引（FTS5 trigram 中文全文）、链接图（wikilink 全语法 + md 相对路径，大小写不敏感，反斜杠归一化）、near-miss 改名检测（比例 + 扩展名双过滤）
- 四条内置规则：`link/broken`、`link/near-miss`、`note/orphan`、`asset/unreferenced`
- CLI：`vault-doctor scan`（表格/JSON、CI 退出码、`--rules` 过滤）；`.vaultdoctorignore`
- src 布局打包（`pip install -e .`）、MIT License、双语 README
