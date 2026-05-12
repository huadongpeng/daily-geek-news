# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this repository.

## Project overview

「老花有话说」— Automated pipeline: 70+ global RSS feeds → DeepSeek V4 Pro → actionable Chinese-language opportunity briefings + hands-on tutorials → Hugo static site → GitHub Pages + Telegram + WeChat Official Account drafts.

**Target reader**: 28-38 year olds with tech skills, hit hard by AI disruption — possibly unemployed, in debt, tight cash flow. They need concrete "what can I do this week" guides, not industry analysis. All content must be zero-cost actionable.

## Commands

```bash
pip install feedparser requests ddgs  # pipeline dependencies
pip install -r tools/requirements_wechat.txt        # WeChat publisher dependencies (mistune)
python purifier.py        # Run pipeline → content/posts/
hugo serve                # Local preview
hugo --minify             # Production build
bash tools/publish_wechat.sh              # Push deep dives to WeChat drafts
bash tools/publish_wechat.sh --yesterday  # Push yesterday's articles
bash tools/publish_wechat.sh --dry-run    # Preview
```

## Architecture

### `purifier.py` — main pipeline engine (v2)

**6 engines** in `AGENTS` dict, redesigned for actionable opportunities:

| Engine | Title | Deep Dive? | Focus |
|---|---|---|---|
| Arbitrage-Radar | 套利雷达 | Yes | Verifiable opportunities within 7 days |
| AI-Frontier | AI 工具实战 | Yes | Tool comparisons, hands-on tutorials, efficiency |
| Cross-Border-Insights | 海外信息差 | Yes | Overseas info arbitrage, copy/adapt/localize |
| Macro-Events | 宏观风向标 | **No** | Briefing only — event screening, personal impact |
| China-Going-Global | 出海工具链 | Yes | Platform registration, payment, compliance how-tos |
| Developer-Goldmine | 效率工具与自动化 | Yes | Workflow automation, free tools, AI-assisted dev |

**Key changes from v1:**
- **Reader persona injected** via `SYSTEM_PROMPT` — targets AI-disrupted individuals with <1000 RMB startup
- **No fixed chapter structure** — free-form articles, must include core insight + action steps + pitfalls + earnings forecast
- **Writing rules**: every claim must follow with "what you can do now"; no "trend analysis", only "open X → register → do Y"
- **Macro-Events**: deep_dive_prompt set to `"NO_DEEP_DIVE"` — only generates news briefings
- **All schemes**: must label startup cost (RMB), time investment (hours), expected first-week earnings (RMB)

**Flow per engine:**
1. `fetch_and_augment()` — parallel RSS fetch (4 workers) + DuckDuckGo RAG (5 results). Feed caching via `_FEED_CACHE` (5min TTL).
2. `deep_dive_worker()` — one DeepSeek API call generates both `briefing` and optional `deep_dive` JSON.
3. `save_deep_dive()` / `save_aggregated_briefing()` — write Hugo Markdown.
4. `send_deep_dive_tg()` / `send_aggregated_briefing_tg()` — Telegram push.

### `tools/wechat_publisher.py` — WeChat Official Account draft publisher (v2)

Runs on Tencent Cloud server. Key changes from v1:
- **`md_to_wechat_html()`** now uses `mistune` parser (custom `WeChatRenderer`) instead of fragile line-by-line regex
- **Cleaner template**: minimal header/footer, no more dark gradient brand bar, 15px body text, `#576b95` accent color
- `polish_for_wechat()` dead code removed (was never defined, caused silent error)
- Dependencies: `mistune>=3.0` added to `tools/requirements_wechat.txt`

### `tools/publish_wechat.sh` — server-side convenience script

Wraps git fetch + source .env + python3 wechat_publisher.py.

### Deployment flow (GitHub Actions → GitLab → WeChat)

`.github/workflows/main.yml` runs at UTC 22:00 (Beijing 06:00):

1. **Checkout** (with PaperMod submodule) → install Python + `pip install feedparser requests ddgs`
2. **Run `purifier.py`** → generates Markdown to `content/posts/`
3. **Commit + push** new articles back to GitHub
4. **Mirror-push to GitLab** (`git push gitlab +main:main`) → Tencent Cloud server pulls from local GitLab
5. **Pull cover images from GitLab** — the WeChat publisher on Tencent Cloud generates AI cover images and pushes them to GitLab; this step pulls them back so Hugo can reference them
6. **Hugo build** (`hugo --minify`) → deploy to GitHub Pages (`gh-pages` branch) with CNAME `radar.huadongpeng.com`

### Cover image generation (dual-engine)

`tools/wechat_publisher.py` generates AI cover images for WeChat articles:

- **Primary**: 通义万相 (`wanx2.0-t2i-turbo`) via DashScope API — 200 free images/month
- **Fallback**: 智谱 CogView-3 via Zhipu API — 100 free images/month
- Images saved to both `tools/covers/` (for WeChat upload) and `static/images/covers/` (for website)
- Cover URL written back to Hugo frontmatter as `cover:` field

### WeChat content compliance

`tools/wechat_publisher.py` has a `SENSITIVE_PATTERNS` list that flags: VPN/tool references, crypto, political terms, security vulnerabilities, COVID origins, and regional naming issues (Taiwan/HK/Macau). Flagged content is warned but not auto-removed — manual review required before publishing from WeChat drafts.

### Site config

- `hugo.toml` — PaperMod theme, updated nav: 首页→每日快讯→套利雷达→信息差→出海工具→AI实战→效率工具→宏观风向→关于
- PaperMod CSS overrides go in `assets/css/extended/custom.css` (auto-loaded by PaperMod) or inline in `extend_head.html`
- `layouts/_partials/` — extend_head.html (inline critical mobile CSS + SEO + JSON-LD), extend_footer.html (mobile bottom nav + Busuanzi + Article schema)

## Environment variables

**Pipeline (GitHub Actions secrets + local `.env`):**

| Var | Used by | Purpose |
|---|---|---|
| `DEEPSEEK_API_KEY` | purifier.py | DeepSeek V4 Pro API |
| `TELEGRAM_BOT_TOKEN` | purifier.py | Telegram bot auth |
| `TELEGRAM_CHAT_ID` | purifier.py | Target Telegram supergroup |
| `TG_THREAD_ARBITRAGE` | purifier.py | Arbitrage-Radar topic ID |
| `TG_THREAD_AI` | purifier.py | AI-Frontier topic ID |
| `TG_THREAD_CROSS` | purifier.py | Cross-Border-Insights topic ID |
| `TG_THREAD_MACRO` | purifier.py | Macro-Events topic ID |
| `TG_THREAD_CHINA` | purifier.py | China-Going-Global topic ID |
| `TG_THREAD_DEV` | purifier.py | Developer-Goldmine topic ID |
| `TG_THREAD_BRIEFING` | purifier.py | Aggregated briefing topic ID |

**GitLab mirror (GitHub Actions secrets):**

| Var | Purpose |
|---|---|
| `GITLAB_HOST` | Tencent Cloud GitLab hostname |
| `GITLAB_USERNAME` | GitLab username |
| `GITLAB_ACCESS_TOKEN` | GitLab personal access token |

**WeChat publisher (Tencent Cloud server `tools/.env`, see `tools/.env.example`):**

| Var | Purpose |
|---|---|
| `WECHAT_APPID` | 公众号 AppID |
| `WECHAT_APPSECRET` | 公众号 AppSecret |
| `WECHAT_AUTHOR` | Author display name (default: Easton Hua) |
| `DASHSCOPE_API_KEY` | 通义万相 cover image (200 free/month) |
| `ZHIPU_API_KEY` | 智谱 CogView cover image fallback (100 free/month) |
| `GIT_REPO_DIR` | Repo path on server (default: `/ws/web/daily-geek-news`)

## Critical bugs to avoid

- **Telegram URL**: Must be `f"https://api.telegram.org/bot{TOKEN}/sendMessage"` — never Markdown link format
- **WeChat title limit**: 30 bytes (≈10 Chinese chars). Use `optimize_wechat_title()` with byte-level truncation
- **WeChat digest limit**: 64 bytes. Use `DIGEST_BYTES = 60` for safe margin
- **Time zone**: Always use `bj_now()` (UTC+8) in purifier.py
- **Macro-Events deep_dive**: Must be `"NO_DEEP_DIVE"` string in AGENTS config — otherwise the prompt logic will try to generate
- **mistune dependency**: Must be installed on Tencent server before running wechat_publisher.py
- **PaperMod CSS priority**: Use `!important` + `body` prefix selector + inline `<style>` in extend_head.html for mobile overrides
