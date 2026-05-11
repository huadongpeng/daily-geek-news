# Easton 跨国智库 · 自动化情报雷达站

每日自动扫描 **20+ 海外权威信息源**，DeepSeek V4 Pro 深度推理，输出中文可执行情报。GitHub Actions 全自动运行，Hugo 静态站点部署至 GitHub Pages。

## 架构

```
20+ RSS Feeds (Reddit/HN/TechCrunch/Wired/ArXiv/BBC/CNBC...)
        │
        ▼
  DuckDuckGo 全网主动检索 (RAG 外网扩充，每条 ≥5 深度来源)
        │
        ▼
  DeepSeek V4 Pro 双轨引擎 (4 大引擎并发)
        │
        ├── 📋 每日快讯 (3-5条，含零成本切入点)
        │       ├──► Hugo Markdown → GitHub Pages
        │       └──► Telegram Topic 推送（丰满格式）
        │
        └── 🔥 深度长文 (有话题价值时触发)
                ├──► Hugo Markdown → GitHub Pages
                └──► Telegram Topic 单独推送
```

## 双轨内容体系

| 类型 | 频率 | 内容 | 质量门 |
|------|------|------|--------|
| 📋 快讯 | 每日 4 篇 | 3-5 条海外信息汇总，含来源+要点+零成本切入点 | 始终输出 |
| 🔥 深度长文 | 有话题时 | 四章结构化深度拆解，含可运行代码 | 模型自主判断 |

## 四大情报引擎

| 引擎 | 信息源 | 定位 |
|------|--------|------|
| 💰 套利雷达 | r/SaaS, r/SideProject, r/juststart, r/startups, IndieHackers, HN | 零成本套利项目拆解 |
| 🤖 AI 前沿 | HN, MIT Tech Review, The Verge AI, VentureBeat AI, ArXiv CS.AI, OpenAI Blog | AI 技术硬核分析 |
| 🌍 跨国脑洞 | r/Entrepreneur, Wired, Rest of World, The Guardian, Semafor | 商业模式本土化套利 |
| 📉 宏观风向 | TechCrunch, The Verge, Ars Technica, BBC Tech, CNBC, The Guardian | 全球事件对冲策略 |

## 本地运行

```bash
pip install feedparser requests duckduckgo-search

# 环境变量（Linux/Mac 用 export，Win 用 $env:）
export DEEPSEEK_API_KEY="sk-xxx"
export TELEGRAM_BOT_TOKEN="xxx"
export TELEGRAM_CHAT_ID="-100xxxxxxxxx"
export TG_THREAD_ARBITRAGE="xxx"
export TG_THREAD_AI="xxx"
export TG_THREAD_CROSS="xxx"
export TG_THREAD_MACRO="xxx"

python purifier.py   # 生成 content/posts/ 下 Markdown
hugo serve           # 本地预览
```

## 部署

GitHub Actions 每日 UTC 22:00（北京时间 06:00）自动运行。需要配置 GitHub Secrets：

| Secret | 说明 |
|--------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | 超级群组 ID（-100 开头） |
| `TG_THREAD_ARBITRAGE` | 套利雷达 Topic ID |
| `TG_THREAD_AI` | AI 前沿 Topic ID |
| `TG_THREAD_CROSS` | 跨国脑洞 Topic ID |
| `TG_THREAD_MACRO` | 宏观风向 Topic ID |

## 联系方式

📧 hdop1993@gmail.com
