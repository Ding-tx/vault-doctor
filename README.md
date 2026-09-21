# vault-doctor 🩺

**The doctor for your markdown knowledge base** — graph-aware lint that finds broken links, orphan notes and unreferenced attachments, and tells you when a "broken" link is really just a renamed file.

**markdown 知识库的体检医生** —— 图谱语义层的 lint：找出断链、孤儿笔记、未被引用的附件，并告诉你哪些"断链"其实只是文件改了名。

<!-- TODO(发布前): 首屏 GIF —— scan 输出 + near-miss 改名建议的真实终端录制 -->

```text
$ vault-doctor scan .
669 篇笔记 · 175 个资产 · 索引耗时 0.65s
error  link/broken         数学/复习.md:4       断链：[[概率论笔记]] 解析不到库内文件
warn   link/near-miss      数学/复习.md:4       疑似改名：「概率论笔记」最接近的现有文件是 数学/概率论.md（编辑距离 2）
warn   note/orphan         misc/ideas.md        孤儿笔记：无入链也无出链
warn   asset/unreferenced  assets/old.png       未引用资产：没有任何笔记链接到它
共 17 条：7 error · 10 warn · 0 info
```

## Why / 为什么需要它

lychee checks **external** URLs. markdownlint fixes **formatting**. Obsidian plugins are editor-locked and detect-only. vault-doctor covers the missing layer: it understands the **graph** of your vault — `[[wikilinks]]`, backlinks, orphans — works on **any** markdown folder (Obsidian / Typora / VS Code / plain git repos), and its near-miss engine maps broken links to renamed files (Damerau-Levenshtein ≤ 2, filtered by name-length ratio and file extension).

lychee 管**外部**链接，markdownlint 管**格式**，Obsidian 插件锁编辑器且只检测。vault-doctor 补上缺的那一层：它**懂你知识库的图谱**——wikilink、反向链接、孤儿——任何 markdown 文件夹都能用；near-miss 引擎还能把断链映射到改名后的文件。

## Install / 安装

Requires Python ≥ 3.12.

```bash
pipx install vault-doctor     # TODO: PyPI 发布后可用
# 或从源码（开发）
pip install -e .
```

## Usage / 用法

```bash
vault-doctor scan <vault-path>             # 扫描（默认只读，绝不修改任何文件）
vault-doctor scan . --format json          # JSON 输出（CI / 工具链集成）
vault-doctor scan . --format sarif -o out.sarif   # SARIF 2.1.0（GitHub Code Scanning）
vault-doctor scan . --rules note/orphan    # 只跑指定规则
vault-doctor rules                         # 列出内置 + 插件规则
vault-doctor why . --index 1               # 用 LLM 把一条违规翻译成人话
```

**`why` 需要 API key**（唯一需要密钥的命令）：复制 `config.example.toml` 为 `config.local.toml` 并填入 `api_key`（默认智谱 GLM，任何 OpenAI 兼容端点均可；该文件已被 gitignore，密钥不入库）。也支持环境变量 `VAULT_DOCTOR_API_KEY`。

**Exit codes / 退出码**（CI 友好）：`0` 干净 · `1` 存在 error 级违规 · `2` 用法/路径错误。

**`.vaultdoctorignore`**（放库根，每行一个 fnmatch 模式，`#` 为注释）——把供应商代码等"非笔记子树"划出扫描范围：

```text
# 每行一个模式，匹配路径前缀即整棵跳过
vendor/
Grok/grok-build-main
```

## Rules / 内置规则

| 规则 | 严重度 | 说明 |
|---|---|---|
| `link/broken` | error | `[[wikilink]]` / `[md](相对路径)` 解析不到库内文件；自动归一化 `.\images\x.png` 这类 Windows 反斜杠写法 |
| `link/near-miss` | warn | 断链疑似改名/笔误：给出最接近的现有文件与编辑距离 |
| `note/orphan` | warn | 无入链也无出链的笔记 |
| `asset/unreferenced` | warn | 从未被任何笔记引用的图片 / PDF 等附件 |

## Plugins / 插件规则

任何 pip 包都能给 vault-doctor 加规则——在自己的 `pyproject.toml` 里声明：

```toml
[project.entry-points."vault_doctor.rules"]
my_rule = "my_package.rules:MY_RULE"   # 指向 Rule 实例或 Rule 序列
```

安装后 `vault-doctor rules` 即可看到（来源列标"插件"）。规则 id 与内置冲突时内置优先；坏插件跳过并告警，不拖垮扫描。

## GitHub Action / CI

```yaml
- uses: user/vault-doctor@v0.1.0
  with: { path: docs/ }
```

在 PR 上直接标注断链（SARIF → GitHub Code Scanning）。也可只用 CLI 接入自有流水线：`vault-doctor scan . --format sarif -o out.sarif`，退出码 `1` 即存在 error 级违规。

**Safety / 安全承诺**：vault-doctor **永远只读**——不编辑、不移动、不删除你的任何文件；修复建议只以报告形式输出。（agent 辅助修复在路线图 M2，同样默认 diff 预览 + 人工闸门。）

## How it works / 工作原理

- **SQLite 单文件索引**：`(mtime, size)` 指纹增量更新；FTS5 trigram 分词支持中文全文检索；链接图两级可见性（解析器看得见一切路径，规则各管各的域）
- **解析器带版本号**：引擎解析逻辑升级后自动全量重解析链接，不依赖文件变动（增量索引的版本失效机制）
- 代码块与行内代码中的"链接"不计入；隐藏目录、`__pycache__` 等自动跳过

## Roadmap / 路线图

- **M1**：规则 SDK（插件化注册）、SARIF 输出 + GitHub Action（PR 上直接标注断链）、`why` 命令（把一条违规翻译成人话——首次 LLM 调用）
- **M2**：agent 修复循环——`fix` 命令、diff 预览、人工闸门、git 快照回滚
- **M3**：本地 embedding 语义查重、模型路由、**MCP server**（把只读图谱工具暴露给 Claude Code / Cursor 等任意 agent）
- **M4**：会话重放（replay）、规则插件注册表

## Comparison / 对比

| | vault-doctor | lychee | markdownlint | Obsidian 插件 |
|---|---|---|---|---|
| 外部 URL 检查 | ✗（M1 集成 lychee） | ✓ | ✗ | 部分 |
| 格式修复 | ✗（互补，交给它） | ✗ | ✓ `--fix` | ✓ |
| wikilink 图谱解析 | ✓ | ✗ | ✗ | ✓（锁编辑器） |
| 孤儿 / 未引用资产 | ✓ | ✗ | ✗ | 部分 |
| near-miss 改名检测 | ✓ | ✗ | ✗ | ✗ |
| 独立 CLI / 任意编辑器 | ✓ | ✓ | ✓ | ✗ |
| Windows 反斜杠路径归一 | ✓ | ✗ | ✗ | — |

## Development / 开发

```bash
pip install -e .
pip install pytest
pytest -v
```

23 个测试覆盖：索引与增量、链接解析（含中文文件名/大小写/父目录/反斜杠）、near-miss 过滤链、四规则基准对账、CLI 退出码与输出格式。

## License

[MIT](LICENSE)
