# Changelog

## Unreleased（v0.4.1 候选）

- **UI 文件夹选择器**（用户提议）：🚫 取消打开页面自动体检——改为空态引导"选文件夹 → 点开始体检"；右上角新增 📁 浏览按钮弹出文件夹选择框（磁盘 → 逐层进入 → 选择此文件夹，选完自动体检）。服务端 `GET /api/browse` 只列子目录、过滤隐藏/缓存目录，仅 127.0.0.1 可达；路径输入框保留（粘贴党兼作当前库显示）
- **Web UI"模型与 API key"设置卡**：国产厂商预设（智谱 GLM / DeepSeek / Kimi / 通义千问 / 豆包 / MiniMax / 硅基流动）+ OpenAI / 自定义，选厂商自动填地址与默认模型（均可改）；**测试连接**真调一次最小请求验证；保存写入 `config.local.toml`——key 只存本机、页面仅打码显示（`sk-***abcd`）、留空保存 = 只改地址/模型沿用已存密钥；base_url 过 SSRF 校验（拒绝内网/环回）

## v0.4.0 (2026-09-23)

- **MCP server 模式（M3-A）**：`vault-doctor mcp <vault>` 以 stdio 启动只读 MCP server（Claude Code / Cursor / ZCode 等 agent 即插即用）。五个只读图谱工具：`scan_vault`（大库支持 `limit` 概览，`violation_count` 给全量数）、`outgoing_links` / `backlinks`、`near_miss_candidates`、`search_notes`（中文子串）。可选依赖 `pip install "vault-doctor[mcp]"`；兼容 MCP SDK 1.x/2.x；`--check` 一键自检；**不含任何写工具**——修改永远走 `fix` 的人工闸门
- **本地 Web UI**：扫描表格（按文件分组、严重度/规则/关键词筛选、医疗青品牌设计）、"为什么？"LLM 解释、修复卡片三段式（为什么改 / AI 理由 / diff + 预览即验证）、快照详情与一键回滚；零新增依赖，仅绑 127.0.0.1
- **链接愈合与失效（引擎修复，校准 #7）**：目标文件晚于链接落盘时，断链会在下次扫描自动愈合（此前永不复检，出现"断链与 near-miss 距离 0 自相矛盾"）；反向，指向已删文件的链接即时断裂。LINKS_VERSION 2→3，存量索引首次扫描自愈。**该盲区由 Claude Code 通过 MCP 体检真实库时发现**
- 全量文案白话化：规则中文名（断链/疑似改名/孤儿笔记/未引用附件）、违规消息与图例去术语化

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
