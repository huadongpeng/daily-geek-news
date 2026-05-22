# Easton Radar

给一个中年小公司技术经理用的个人情报系统：早晚抓取尽量接近源头的信息，按人设初筛，生成每日简讯，并从候选里深挖 1-3 篇值得写的深度文章。输出到 Hugo 网站，并通过 Telegram 通知。

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
优中择优生成深度好文
        ↓
生成 Gemini Banana 公众号封面提示词
        ↓
写入 Hugo + 公众号源文件 + Telegram 通知 + GitHub Pages
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

公众号源文件输出参考并整合了旧项目 `/ws/project/article/` 的 `output/` 工作流，但现在由主流程自动生成，不再需要手工改写项目中转。

也可以通过环境变量覆盖：

- `PERSONA_PATH`
- `RESEARCH_SKILL_PATH`
- `WRITING_SKILL_PATH`

## 本地运行

```bash
pip install feedparser requests ddgs

export DEEPSEEK_API_KEY="sk-xxx"
export DEEPSEEK_MODEL="deepseek-v4-pro"
export DEEPSEEK_THINKING="enabled"
export DEEPSEEK_REASONING_EFFORT="max"
export TELEGRAM_BOT_TOKEN="xxx"      # 可选
export TELEGRAM_CHAT_ID="-100xxx"    # 可选

python purifier.py --slot morning
python purifier.py --slot evening
hugo serve
```

深度文章会额外输出到 `outputs/wechat_articles/`，每篇文件只有三个部分：

```text
标题
Gemini Banana 生图提示词（公众号封面图适配）
正文内容
```

其中正文面向微信公众号编辑器复制粘贴，只保留 `**加粗**` 这一种特殊 Markdown 格式。

## GitHub Secrets

| Secret | 说明 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 必需，调用 DeepSeek V4 Pro 做分析和写作 |
| `TELEGRAM_BOT_TOKEN` | 可选，发送 Telegram 通知 |
| `TELEGRAM_CHAT_ID` | 可选，Telegram 目标群或频道 |
| `TG_THREAD_BRIEFING` | 可选，Telegram topic id |

默认模型是 `deepseek-v4-pro`。如需临时切换，可在 GitHub Variables 里设置 `DEEPSEEK_MODEL`。
默认启用 Thinking Mode，`DEEPSEEK_REASONING_EFFORT` 默认使用 `max`。

GitHub Actions 每天北京时间 06:00 和 18:00 自动运行，也可以手动触发并选择 `morning/evening`。
