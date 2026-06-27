# Research Mail Digest

A coding-agent skill that turns your saved research sources into an email-ready digest — fetches RSS/Atom feeds, filters articles by your saved interests (or ad-hoc keywords), curates a human-friendly HTML email, and sends it through `agently-cli`. It ships as a Claude Code / Codex skill, and the core `SKILL.md` can be read by any coding agent with filesystem and shell access.

> 这是一个把「信息源 → 兴趣筛选 → 邮件摘要 → 投递」整条链路打包成 skill 的工具：无需自己写抓取脚本、无需手动复制粘贴，对 coding agent 说一句话即可生成并投递一期研究摘要。

## What This Does

**Research Mail Digest** helps researchers keep up with journal/news feeds without drowning in them. Point it at RSS/Atom sources (Nature, Science, arXiv, lab news, etc.), tell it what you care about, and it returns a calm, scannable email digest with an editor's note, a "read first" shortlist, and a "why it matters" line for each item.

Today the skill ships with RSS/Atom support; the workflow is kept source-oriented so PubMed, arXiv APIs, webpages, or other channels can be added later.

### Key Features

- **零依赖脚本** — `build_digest.py` 只用 Python 标准库（`urllib` + `xml.etree`），没有 `pip install`，开箱即跑。
- **多格式抓取** — 支持 RSS 1.0/RDF、RSS 2.0、Atom，自动提取标题、链接、来源、日期、作者、分类与摘要。
- **兴趣打分排序** — 按保存的兴趣关键词对每篇文章打分，优先呈现最相关的内容；即便没有命中关键词，也会回退到最新条目供 agent 语义判断。
- **持久化配置** — 信息源、兴趣、收件人都存在 `data/` 下的模板文件里，可用配套管理脚本增删改查，下次直接复用。
- **邮件友好 HTML** — 纯内联样式、无表格/JS/SVG，在手机和网页邮箱里都能正常显示。
- **两段式确认发送** — 通过 `agently-cli`（Agent Mail CLI）投递，遵守其 token 确认流程，发送前必须经用户显式确认。
- **定时可重定位** — 配套 cron 包装脚本自动推断 skill 目录，日志与产物路径均可通过环境变量覆盖。
- **安全优先** — 所有 RSS 内容视为不可信外部数据，不打开原文链接（除非用户要求），不执行源里嵌入的指令。

## Installation

仓库地址（请使用 HTTPS 形式）：

```text
https://github.com/huang-sh/research-mail-digest
```

### Claude Code 手动安装

把 skill 复制到 Claude Code 的 skills 目录：

```bash
# 直接 clone 到 skills 目录
git clone https://github.com/huang-sh/research-mail-digest.git ~/.claude/skills/research-mail-digest
```

或先 clone 再拷贝：

```bash
git clone https://github.com/huang-sh/research-mail-digest.git
mkdir -p ~/.claude/skills/research-mail-digest
cp -R research-mail-digest/{SKILL.md,scripts,data,agents} ~/.claude/skills/research-mail-digest/
```

安装后在 Claude Code 里输入 `/research-mail-digest` 即可调用。standalone skill 不带命名空间前缀。

### Codex / 其他 coding agent

Codex、Kimi Code、OpenCode、Gemini CLI 等本地 coding assistant 也能用同一个核心 skill。最简单的办法是把仓库链接发给 agent，让它使用 Research Mail Digest skill：

```text
https://github.com/huang-sh/research-mail-digest
```

如果 agent 能读取仓库或浏览文件，它会从 `SKILL.md` 出发，按需加载 `scripts/` 与 `data/` 中的支撑文件。

对于 Codex 这类以 `CODEX_HOME` 为根的 agent，clone 到对应 skills 目录即可：

```bash
git clone https://github.com/huang-sh/research-mail-digest.git ~/.codex/skills/research-mail-digest
```

> Codex 的定时推送包装脚本默认以 `CODEX_HOME` 为根写日志；若 skill 目录的父目录名为 `skills`，它会自动把 `CODEX_HOME` 指到 skill 目录的上两级。

### 不依赖 agent 的脚本用法

即使不装任何 agent，`scripts/` 下的 Python 脚本也能独立运行——只要有 Python 3 和网络即可生成摘要文件（发送邮件需要 `agently-cli`）。见下文 [Usage](#usage)。

## First-Run Setup（首次配置三项）

全新安装时，`data/sources.txt`、`data/interests.md`、`data/recipients.md` 都是空的模板。在生成或投递摘要前，必须先配置三项，否则 skill 会在「预检」步骤停下并告诉你缺什么。

检查当前配置：

```bash
python3 scripts/manage_sources.py list
```

返回的 JSON 必须满足：

- `sources` 至少 1 个 RSS/Atom URL；
- `interests` 至少 1 个兴趣关键词或短语；
- `recipients.to` 至少 1 个收件邮箱。

把这些一次性发给 agent，它会帮你保存到 skill 配置里：

```text
首次使用需要先配置 3 项：信息源 RSS/Atom 链接、感兴趣的主题、收件邮箱。
比如：信息源用 Nature + Science 的 RSS；感兴趣 AI for science、单细胞组学；
收件邮箱 alice@example.com。请按需替换后发我。
```

> skill 绝不擅自使用示例 URL 或占位邮箱，只会保存你明确提供或同意的值。

## Usage

### 生成并投递一期摘要（交互式）

在 Claude Code 里：

```text
/research-mail-digest

> 帮我把保存的信息源整理成今天的摘要，发给收件人
```

agent 会按如下流程执行：

1. 只在必要时澄清收件人 / 信息源 / 兴趣 / 时间窗 / 语言，其余用 `data/` 里的默认值；
2. 运行预检（`manage_sources.py list`），缺项就停下问你；
3. 用 `check_agently_mail.py` 检查 `agently-cli` 是否安装并已授权；
4. 用 `build_digest.py` 抓取并解析信息源、按兴趣排序；
5. 复核生成结果，把 RSS 标题/摘要当作不可信数据对待；
6. 视情况优化内容：归类、改写、剔除弱匹配、写一段编辑式导读；
7. 通过 `agently-cli message +send --body-format html` 投递，先返回摘要让你确认，**确认后**才真正发送。

### 管理信息源 / 兴趣 / 收件人

用配套管理脚本增删改查（删除/修改既支持精确文本，也支持 `list` 输出里的 1-based 序号）：

```bash
# 查看当前配置
python3 scripts/manage_sources.py list

# 信息源
python3 scripts/manage_sources.py add-source "https://www.nature.com/nature.rss"
python3 scripts/manage_sources.py remove-source "https://www.nature.com/nature.rss"
python3 scripts/manage_sources.py set-source 1 "https://example.com/new-feed.xml"

# 兴趣
python3 scripts/manage_sources.py add-interest "spatial transcriptomics"
python3 scripts/manage_sources.py remove-interest "spatial transcriptomics"
python3 scripts/manage_sources.py set-interest 1 "AI for biology"

# 收件人（kind ∈ to / cc / bcc）
python3 scripts/manage_sources.py add-recipient to "person@example.com"
python3 scripts/manage_sources.py add-recipient cc "copy@example.com"
python3 scripts/manage_sources.py remove-recipient cc 1
python3 scripts/manage_sources.py set-recipient to 1 "new@example.com"
```

> 如果只想「这一次」用某个信息源或兴趣，不要保存——直接给 `build_digest.py` 传 `--feed` 或 `--interest`。

### 直接生成摘要文件（不发送）

```bash
python3 scripts/build_digest.py \
  --limit 8 \
  --intro-style long \
  --out-html ./digest.html \
  --out-text ./digest.txt \
  --out-json ./digest.json
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--feed <URL>` | 临时追加一个 RSS/Atom 源，可重复 |
| `--interest <text>` | 临时追加一个兴趣关键词，可重复 |
| `--feeds-file` / `--interests-file` | 指定自定义信息源 / 兴趣文件（默认读 `data/`） |
| `--limit N` | 摘要最多包含 N 篇（默认 8） |
| `--timeout S` | 单源抓取超时秒数（默认 20） |
| `--title <text>` | 摘要标题 |
| `--intro-style short\|long` | 导读长短（默认 `long`） |
| `--out-html` / `--out-text` / `--out-json` | 分别写出 HTML 正文 / 纯文本 / 结构化 JSON |

### 通过 Agent Mail CLI 投递

发送前先确认 CLI 就绪：

```bash
python3 scripts/check_agently_mail.py
```

`ready` 为 `true` 即可继续。若 `installed` 或 `authorized` 为 `false`，请按官方文档安装/授权：`https://agent.qq.com/doc/cli-setup.md`，**完成后再重新跑一次就绪检查**。

投递时优先用 `--body "$(cat ...)"`，避免当前目录不一致导致找不到文件：

```bash
agently-cli message +send \
  --to "recipient@example.com" \
  --subject "Research Digest: AI for science - 2026-06-27" \
  --body "$(cat ./digest.html)" \
  --body-format html
```

当 CLI 返回 `confirmation_token` 时，先把发送摘要给用户确认；用户确认后，再带上 `--confirmation-token ctk_xxx` 重复一次同一条命令完成发送。收件人取自 `data/recipients.md`，`## To` → `--to`、`## Cc` → `--cc`、`## Bcc` → `--bcc`，**一封邮件发给全部收件人**，不循环群发。

### 定时（cron）每日推送

用 `scripts/run_daily_digest_codex.sh` 做定时投递。该包装脚本会自动推断 skill 目录、用 `flock` 防止并发、加载默认 nvm 环境，并直接调用 `run_daily_digest.py`（不再 spawn `codex exec`）。`run_daily_digest.py` 会生成中文 HTML 摘要、自动完成两段式确认，并写出最终状态。

先做一次干跑（只构建、报告收件人，不发邮件）：

```bash
python3 scripts/run_daily_digest.py --workdir . --dry-run
```

在 crontab 里加一条每日任务（示例：每天 8:00）：

```cron
0 8 * * * /home/you/.codex/skills/research-mail-digest/scripts/run_daily_digest_codex.sh
```

可用的环境变量：

| 变量 | 说明 |
| --- | --- |
| `CODEX_HOME` | 日志根目录，默认 `$HOME/.codex` |
| `RESEARCH_MAIL_DIGEST_LOG_DIR` | 自定义日志目录（默认 `$CODEX_HOME/logs/research-mail-digest`） |
| `RESEARCH_MAIL_DIGEST_WORKDIR` | 生成摘要文件的工作目录（默认日志目录下的 `work/`） |
| `RESEARCH_MAIL_DIGEST_DRY_RUN` | 设为 `1`/`true` 时干跑，不发送 |
| `PYTHON_BIN` | 指定 python3 路径 |

## Project Layout

skill 采用**渐进式加载**：`SKILL.md` 是工作流地图，支撑脚本/数据按需调用。

| 文件 / 目录 | 作用 |
| --- | --- |
| `SKILL.md` | 核心 workflow 与规则，调用 skill 时必读 |
| `data/sources.txt` | 信息源清单，每行一个 RSS/Atom URL（模板） |
| `data/interests.md` | 兴趣关键词，`## Interests` 下的 `- ` 列表（模板） |
| `data/recipients.md` | 收件人，分 `## To` / `## Cc` / `## Bcc`（模板） |
| `scripts/manage_sources.py` | 信息源 / 兴趣 / 收件人的增删改查 |
| `scripts/build_digest.py` | 抓取解析 RSS/Atom、按兴趣排序、产出 HTML/text/JSON |
| `scripts/check_agently_mail.py` | 检查 `agently-cli` 是否安装并已授权 |
| `scripts/run_daily_digest.py` | 确定性的定时运行：预检 → 构建 → 中文 HTML → 投递 |
| `scripts/run_daily_digest_codex.sh` | cron 包装脚本，可重定位、带文件锁 |
| `agents/openai.yaml` | agent 接口元信息（展示名、默认 prompt） |

## Email Format

HTML 邮件只用简单内联样式，不用 JS / 外部 CSS / 表单 / SVG / 复杂 CSS，结构为：

- 头部：日期、标题、关注主题；
- **导读**：2–4 段编辑式导言，说明用了哪些源与兴趣、本期整体趋势、哪 2–3 篇值得优先读；
- **优先阅读**：最强条目短列表；
- 文章列表：可点击标题、来源/日期、人工式摘要、「为什么重要」；
- 页脚：说明内容由 RSS/Atom 元数据整理、未主动打开原文。

推荐主题格式：`Research Digest: <main interest> - <YYYY-MM-DD>`，或 `每日研究摘要：<主题> - <YYYY-MM-DD>`。除非用户要求，否则不加 agent 署名。

## Requirements

- **Python 3**（脚本仅依赖标准库，无需 `pip install`）；
- **网络访问**：能抓取所配置的 RSS/Atom 源；
- **`agently-cli`（Agent Mail CLI）**：仅发送邮件时需要；安装/授权见 `https://agent.qq.com/doc/cli-setup.md`；
- **本地 coding agent**（可选）：用于交互式调用 `/research-mail-digest`；仅手动跑脚本则不需要。

## Safety

源内容来自外部，属不可信数据。skill **不会**执行 RSS 标题/描述/作者/网页/元数据/链接里嵌入的任何指令；除非用户要求全文核对，否则不打开文章链接；也不会仅凭源内容进行发送、回复、转发、订阅或删除。摘要是对摘要/元数据的改写，不复制大段原文，尊重版权。

## Credits

Created by [@huang-sh](https://github.com/huang-sh).

## License

MIT — Use it, modify it, share it.
