# Easton 跨国智库

每日自动化扫描 **70+ 全球权威信息源**，DeepSeek V4 Pro 深度推理，输出中文可执行商业情报。GitHub Actions 全自动运行，Hugo 静态站点部署至 GitHub Pages，Telegram + 微信公众号双通道推送。

## 架构

```
70+ RSS Feeds (全球 7 区域: 北美/欧洲/亚洲/中东/拉美/非洲/中国)
        │
        ▼
  并行抓取 (6 引擎 × 4 worker，请求级缓存去重)
        │
        ▼
  DuckDuckGo RAG 检索 (每条 5 个深度来源)
        │
        ▼
  DeepSeek V4 Pro 双轨引擎 (6 引擎并发)
        │
        ├── 📋 每日快讯 (聚合为 1 篇，按 topic 分组)
        │       ├──► Hugo Markdown → GitHub Pages
        │       └──► Telegram Topic 推送
        │
        └── 🔥 深度长文 (宁缺毋滥，1-2 篇/天)
                ├──► Hugo Markdown → GitHub Pages
                ├──► Telegram 各 Topic 推送
                └──► 微信公众号草稿箱 (通义万相/智谱生图)
```

## 六大情报引擎

| 引擎 | 信息源 | 定位 |
|------|--------|------|
| 套利雷达 | HN, ProductHunt, IndieHackers, r/SaaS, r/SideProject, Acquire, BetaList, V2EX, SSPAI 等 15 源 | 零成本商业模型本土化套利 |
| 跨国脑洞 | Wired, Rest of World, Guardian, Semafor, Stratechery, Pragmatic Engineer 等 9 源 | 海外模式中国本土化落地方案 |
| 中国出海 | 36Kr, 虎嗅, Pandaily, TechNode, Nikkei Asia, SCMP, TechInAsia, e27, Inc42, LatamList, Disrupt Africa 等 15 源 | 中国独有模式反向出海套利 |
| AI 前沿 | OpenAI, Anthropic, Google AI, DeepMind, Meta AI, Mistral, TLDR AI, HuggingFace, ArXiv, 机器之心 等 17 源 | 大模型动态 + AI 工具实战接入 |
| 开发者金矿 | HN, r/programming, GitHub Trending, ProductHunt, Dev.to, InfoWorld, IndieHackers 等 12 源 | 独立开发者技术变现路径 |
| 宏观风向 | TechCrunch, Bloomberg, The Verge, BBC, CNBC, Sifted, YC, a16z 等 10 源 | 全球事件对独立开发者的冲击与对冲 |

## 内容体系

| 类型 | 频率 | 内容 | 标准 |
|------|------|------|------|
| 每日快讯 | 1 篇/天 | 6 引擎情报聚合，按 topic 分组，每条含来源+要点+零成本切入点 | 始终输出 |
| 深度长文 | 1-2 篇/天 | 四章结构深度拆解，核心章节 ≥1200 字，有理有据有推演 | 宁缺毋滥 |

## 本地运行

```bash
pip install feedparser requests ddgs

# 环境变量
export DEEPSEEK_API_KEY="sk-xxx"
export TELEGRAM_BOT_TOKEN="xxx"
export TELEGRAM_CHAT_ID="-100xxx"
export TG_THREAD_ARBITRAGE="xxx"  # 各引擎 Topic ID（可选）
# ... 其他 TG_THREAD_* 变量

python purifier.py   # 生成 content/posts/ 下 Markdown
hugo serve           # 本地预览 http://localhost:1313
```

## 微信公众号发布

部署在腾讯云服务器上，每日 crontab 触发：

```bash
# 推送今日深度长文
bash tools/publish_wechat.sh

# 推送昨日文章
bash tools/publish_wechat.sh --yesterday

# 指定日期 / 预览
bash tools/publish_wechat.sh --date 2026-05-12
bash tools/publish_wechat.sh --dry-run
```

环境变量配置见 `tools/.env.example`。

## 部署

GitHub Actions 每日 UTC 22:00（北京时间 06:00）自动运行。

### GitHub Secrets

| Secret | 说明 |
|--------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | 超级群组 ID |
| `TG_THREAD_ARBITRAGE` | 套利雷达 Topic ID |
| `TG_THREAD_AI` | AI 前沿 Topic ID |
| `TG_THREAD_CROSS` | 跨国脑洞 Topic ID |
| `TG_THREAD_MACRO` | 宏观风向 Topic ID |
| `TG_THREAD_CHINA` | 中国出海 Topic ID |
| `TG_THREAD_DEV` | 开发者金矿 Topic ID |
| `TG_THREAD_BRIEFING` | 每日快讯 Topic ID |
| `GITLAB_HOST` | 自建 GitLab 地址 |
| `GITLAB_USERNAME` | GitLab 用户名 |
| `GITLAB_ACCESS_TOKEN` | GitLab Access Token |

## 联系方式

- 网站：[radar.huadongpeng.com](https://radar.huadongpeng.com)
- 公众号：**老花有话说**（lanrenleyou）
- 邮箱：hdop1993@gmail.com
