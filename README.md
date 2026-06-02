# Easton Radar

给一个中年小公司技术经理用的个人情报系统：早晚抓取尽量接近源头的信息，按人设初筛，生成每日简讯，并从候选里深挖 1-3 篇值得写的深度文章。输出到 Astro 静态网站，并通过 Telegram 通知。

## 新流程

```text
一手/近源 RSS
        ↓
按人设与关注主题初筛
        ↓
整理每日简讯合集
        ↓
对深度候选二次检索与溯源
        ↓
证据去重与门槛检查（不足则跳过长文）
        ↓
优中择优生成深度好文
        ↓
生成 Gemini Banana 公众号封面提示词
        ↓
写入 Astro 内容目录 + 公众号源文件 + Telegram 通知 + VPS 部署
```

## 当前关注主题

| 主题 | 关注点 |
| --- | --- |
| AI 技术雷达 | AI 最新技术资讯、模型能力变化、论文、官方发布、开发者可试用工具 |
| 赚钱副业实验室 | 个人赚钱渠道、副业、独立产品、低成本验证机会 |
| 社会热点与生活信号 | 不限 AI，只要可能影响职业、收入、生活和风险决策 |
| 信息差雷达 | 跨语言、跨地区、跨平台的信息差和可迁移机会 |

## 配置

核心个人配置在 `config/`：

- `config/persona.md`：人设
- `config/research_skill.md`：深度检索与溯源方法论
- `config/writing_skill.md`：深度文章写作方法论
- `config/sources.json`：RSS 源与检索种子覆盖配置

公众号源文件输出参考并整合了旧项目 `/ws/project/article/` 的 `output/` 工作流，但现在由主流程自动生成，不再需要手工改写项目中转。

也可以通过环境变量覆盖：

- `PERSONA_PATH`
- `RESEARCH_SKILL_PATH`
- `WRITING_SKILL_PATH`

## 本地运行

```bash
pip install feedparser requests ddgs

export DEEPSEEK_API_KEY="sk-xxx"
export DEEPSEEK_FLASH_MODEL="deepseek-v4-flash"
export DEEPSEEK_FLASH_THINKING="disabled"
export DEEPSEEK_FLASH_REASONING_EFFORT="low"
export DEEPSEEK_PRO_MODEL="deepseek-v4-pro"
export DEEPSEEK_PRO_THINKING="enabled"
export DEEPSEEK_PRO_REASONING_EFFORT="max"
export TELEGRAM_BOT_TOKEN="xxx"      # 可选
export TELEGRAM_CHAT_ID="-100xxx"    # 可选

python purifier.py --slot morning
python purifier.py --slot evening
npm run dev
npm run build
```

Windows PowerShell 示例：

```powershell
$env:DEEPSEEK_API_KEY="sk-xxx"
$env:DEEPSEEK_FLASH_MODEL="deepseek-v4-flash"
$env:DEEPSEEK_PRO_MODEL="deepseek-v4-pro"

python purifier.py --slot morning
npm.cmd run dev
npm.cmd run build
```

公众号文章会额外输出到 `outputs/wechat_articles/`，每篇文件包含标题、封面提示词和正文：

```text
标题
封面图提示词（英文版，Midjourney / DALL-E）
封面图提示词（中文版，即梦 / 通义万相）
正文内容
```

其中正文面向微信公众号编辑器复制粘贴，只保留 `**加粗**` 这一种特殊 Markdown 格式。

## GitHub Secrets

| Secret | 说明 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 必需，调用 DeepSeek V4 系列模型做分析和写作 |
| `TELEGRAM_BOT_TOKEN` | 可选，发送 Telegram 通知 |
| `TELEGRAM_CHAT_ID` | 可选，Telegram 目标群或频道 |
| `TG_THREAD_BRIEFING` | 可选，Telegram topic id |
| `SILICONFLOW_API_KEY` | 可选，生成封面图；未配置或失败时会跳过封面 |
| `ALLOW_POLLINATIONS_COVER` | 可选，是否允许封面降级到 Pollinations，默认 `true`；设为 `false` 可只使用 SiliconFlow |
| `INDEXNOW_KEY` | 可选，IndexNow 主动推送 key |
| `BAIDU_PUSH_TOKEN` | 可选，百度主动推送 token |
| `EMAIL_FROM` / `EMAIL_PASSWORD` / `EMAIL_TO` | 可选，发送公众号源文件邮件 |
| `SOURCES_CONFIG_PATH` | 可选，覆盖默认 `config/sources.json` 来源配置路径 |

默认轻量步骤使用 `deepseek-v4-flash`，包括初筛和简讯整理；深度长文使用 `deepseek-v4-pro`，并默认启用 Thinking Mode + `max`。
如需临时切换，可在 GitHub Variables 里设置 `DEEPSEEK_FLASH_MODEL` 或 `DEEPSEEK_PRO_MODEL`。

深度检索不会使用 DeepSeek tool-calling。当前流程是 Flash 生成查询，程序抓取 seed URL、DDGS 搜索结果和可访问正文，去重并检查最小证据量；证据不足的候选只保留在简讯，不进入调查报告和公众号长文。

GitHub Actions 每天北京时间 06:00 和 18:00 自动运行，也可以手动触发并选择 `morning/evening`。工作流会运行内容管线、提交新 Markdown 和封面图、构建 Astro，并通过 rsync 部署到 VPS。
