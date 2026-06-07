# Easton Radar · [hdop家](https://www.huadongpeng.com)

> 驱动 [www.huadongpeng.com](https://www.huadongpeng.com) 的个人情报系统  
> The pipeline powering [www.huadongpeng.com](https://www.huadongpeng.com) — daily briefings on AI tools, side projects, overseas signals & life trends.

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
写成兼具调查严谨性和老花个人判断的网站深度文章
        ↓
复用同一篇文章生成公众号文章源文件并推送公众号草稿 + Telegram 通知 + VPS 部署
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

公众号文章输出参考并整合了旧项目 `/ws/project/article/` 的 `output/` 工作流，但现在由主流程自动生成，不再需要手工改写项目中转。

也可以通过环境变量覆盖：

- `PERSONA_PATH`
- `RESEARCH_SKILL_PATH`
- `WRITING_SKILL_PATH`

## 本地运行

```bash
pip install -r requirements.txt

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

公众号文章会额外输出到 `outputs/wechat_articles/`。正文直接复用网站深度文章，不再单独调用 DeepSeek 二次改写；封面图已由主流程生成。每篇文章会生成一个 Markdown 源文件和一个 `*-draft.json` 草稿载荷：

```text
标题
公众号标题
公众号摘要
封面图
网站链接
正文内容
```

其中正文面向微信公众号编辑器复制粘贴，只保留 `**加粗**` 这一种特殊 Markdown 格式。GitHub Actions 会把 `*-draft.json` 同步到 VPS，再由 VPS 创建公众号多图文草稿。

## GitHub Secrets

| Secret | 说明 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 必需，调用 DeepSeek V4 系列模型做分析和写作 |
| `TELEGRAM_BOT_TOKEN` | 可选，发送 Telegram 通知 |
| `TELEGRAM_CHAT_ID` | 可选，Telegram 目标群或频道 |
| `TG_THREAD_BRIEFING` | 可选，Telegram 简讯 topic id |
| `TG_THREAD_AI` / `TG_THREAD_DEV` | 可选，Telegram AI 工具分类 topic id；优先使用 `TG_THREAD_AI` |
| `TG_THREAD_ARBITRAGE` | 可选，Telegram 副业/机会分类 topic id |
| `TG_THREAD_CROSS` | 可选，Telegram 出海/跨境分类 topic id |
| `TG_THREAD_MACRO` / `TG_THREAD_CHINA` | 可选，Telegram 生活信号分类 topic id；优先使用 `TG_THREAD_MACRO` |
| `SILICONFLOW_API_KEY` | 可选，生成封面图；未配置或失败时会跳过封面 |
| `ALLOW_POLLINATIONS_COVER` | 可选，是否允许封面降级到 Pollinations，默认 `true`；设为 `false` 可只使用 SiliconFlow |
| `INDEXNOW_KEY` | 可选，IndexNow 主动推送 key |
| `BAIDU_PUSH_TOKEN` | 可选，百度主动推送 token |
| `EMAIL_FROM` / `EMAIL_PASSWORD` / `EMAIL_TO` | 可选，发送通知邮件 |
| `SOURCES_CONFIG_PATH` | 可选，覆盖默认 `config/sources.json` 来源配置路径 |
| `PUBLIC_ENABLE_ANALYTICS` | Astro 构建变量，设为 `false` 时不注入 GA |
| `PUBLIC_ENABLE_ADS` | Astro 构建变量，设为 `false` 时不注入 AdSense |
| `PUBLIC_GA_ID` | Astro 构建变量，GA4 Measurement ID，默认使用当前站点 ID |
| `PUBLIC_ADSENSE_CLIENT` | Astro 构建变量，AdSense client id，默认使用当前站点 ID |
| `PUBLIC_BAIDU_VERIFY` | Astro 构建变量，百度搜索资源平台校验码，默认使用当前站点校验码 |

默认轻量步骤使用 `deepseek-v4-flash`，包括初筛和简讯整理；深度长文使用 `deepseek-v4-pro`，并默认启用 Thinking Mode + `max`。
如需临时切换，可在 GitHub Variables 里设置 `DEEPSEEK_FLASH_MODEL` 或 `DEEPSEEK_PRO_MODEL`。

深度检索不会使用 DeepSeek tool-calling。当前流程是 Flash 生成查询，程序抓取 seed URL、DDGS 搜索结果和可访问正文，去重并检查最小证据量；证据不足的候选只保留在简讯，不进入调查报告和公众号文章输出。

GitHub Actions 每天北京时间 06:00 和 18:00 自动运行，也可以手动触发并选择 `morning/evening`。定时/手动运行会先执行内容管线，同时写入网站 Markdown、生成公众号文章源文件；随后按 Telegram 分类推送，提交新 Markdown 和封面图，再用本次生成后的 commit 构建 Astro 并通过 rsync 部署到 VPS，最后由 VPS 推送公众号草稿。

微信公众号草稿推送不在 GitHub runner 里直连微信接口。Actions 会把 `deploy/wechat_draft_push.py` 和本批次 `outputs/wechat_articles/*-draft.json` 同步到 VPS，再由 VPS 执行脚本创建草稿，避免 GitHub 动态 IP 触发微信白名单问题。服务器脚本同目录需要放一个不进 Git 的密钥文件：

```python
# /ws/scripts/wechat_draft_secrets.py
WECHAT_APP_ID = "你的公众号 AppID"
WECHAT_APP_SECRET = "你的公众号 AppSecret"
WECHAT_AUTHOR = "老花"
```

可选 GitHub Variables：

| Variable | 说明 |
| --- | --- |
| `WECHAT_DRAFT_SCRIPT_PATH` | VPS 上的草稿推送脚本路径，默认 `/ws/scripts/easton_wechat_draft_push.py` |
| `WECHAT_DRAFT_REMOTE_DIR` | VPS 上本批次草稿载荷临时目录，默认 `/tmp/easton-radar-wechat` |
| `SEARCH_PUSH_STATE_DIR` | VPS 上的搜索引擎补推状态目录，默认 `/ws/state/easton-radar-search-push` |

公众号草稿默认按多图文合并创建：VPS 脚本会把本批次最多 8 篇 `*-draft.json` 合并到同一个草稿的 `articles` 数组里。可在 VPS 环境或 `wechat_draft_config.json` 中配置：

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `WECHAT_DRAFT_GROUP_MODE` | `1` | `0/false/no` 时改为每篇单独创建草稿 |
| `WECHAT_DRAFT_MAX_ARTICLES` | `8` | 单个多图文草稿最多合并篇数 |

公众号草稿推送时每篇文章固定设置 `need_open_comment: 1`，不再发送原创、AI 标识、广告或其他未确认字段。公众号草稿正文使用朴素 HTML：短段落、小标题、加粗和少量列表/引用，封面图作为草稿封面展示，不做复杂排版。

`main` 分支 push 也会触发构建部署，但不会运行 `purifier.py`，避免代码修复时误调用 DeepSeek 生成文章。

运行期状态：

- `.cache/radar/source_health.json`：记录 RSS 源连续失败次数，便于发现长期失效来源。
- `.cache/radar/new_push_urls.json`：记录本批次新生成的站内文章 URL，部署完成后再用于 IndexNow / 百度主动推送。
- `search-push-results` artifact：记录部署后 URL 可访问性、IndexNow / 百度推送结果，以及仍需补推的 URL。
- VPS `SEARCH_PUSH_STATE_DIR`：持久保存 IndexNow / 百度推送失败或暂未上线的 URL，下次部署后自动合并补推。
- `outputs/wechat_articles/*-archive.json`：记录公众号文章输出批次和文章元数据，不提交到 Git。
