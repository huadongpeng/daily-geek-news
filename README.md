# Easton 跨国智库 · 自动化情报雷达站

基于 Hugo + GitHub Pages 的全自动海外信息聚合与深度分析系统。每日定时抓取海外 RSS 源，通过 DeepSeek V4 Pro 大模型进行中文深度解读，生成静态博客并推送 Telegram 通知。

## 架构

```
RSS Feeds (Reddit/HN/TechCrunch/IndieHackers/Wired)
        │
        ▼
  DuckDuckGo 主动检索 (RAG 外网扩充)
        │
        ▼
  DeepSeek V4 Pro 深度推理 (4 引擎并发)
        │
        ├──► Hugo Markdown → GitHub Pages
        └──► Telegram Topic 推送
```

## 四大情报引擎

| 引擎 | 数据源 | 定位 |
|------|--------|------|
| 💰 套利雷达 | r/SaaS, IndieHackers | 低成本零库存套利项目拆解 |
| 🤖 AI 前沿 | Hacker News | AI 工具/Agent 工作流深度分析 |
| 🌍 跨国脑洞 | r/Entrepreneur, Wired | 国外商业模式本土化套利 |
| 📉 宏观风向 | TechCrunch | 全球科技经济事件与风险对冲 |

## 本地运行

```bash
# 安装依赖
pip install feedparser requests duckduckgo-search

# 设置环境变量
$env:DEEPSEEK_API_KEY="sk-xxx"
$env:TELEGRAM_BOT_TOKEN="xxx"
$env:TELEGRAM_CHAT_ID="xxx"

# 运行情报引擎（生成 content/posts/ 下的 Markdown）
python purifier.py

# 启动 Hugo 本地预览
hugo serve
```

## GitHub Actions 自动部署

每日 UTC 22:00（北京时间 06:00）自动触发：
1. 运行 `purifier.py` 生成文章
2. 提交 Markdown 到仓库
3. Hugo 编译静态站点
4. 部署到 GitHub Pages

## 环境变量

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | Telegram 频道/群组 ID |
| `TG_THREAD_ARBITRAGE` | 【可选】套利雷达 Topic ID |
| `TG_THREAD_AI` | 【可选】AI 前沿 Topic ID |
| `TG_THREAD_CROSS` | 【可选】跨国脑洞 Topic ID |
| `TG_THREAD_MACRO` | 【可选】宏观风向 Topic ID |
