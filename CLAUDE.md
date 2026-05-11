# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this repository.

## Project overview

Automated pipeline: 70+ global RSS feeds → DeepSeek V4 Pro → Chinese-language intelligence briefings + deep-dive articles → Hugo static site → GitHub Pages + Telegram + WeChat Official Account drafts.

## Commands

```bash
pip install feedparser requests duckduckgo-search  # dependencies
python purifier.py        # Run pipeline → content/posts/
hugo serve                # Local preview
hugo --minify             # Production build
bash tools/publish_wechat.sh              # Push deep dives to WeChat drafts
bash tools/publish_wechat.sh --yesterday  # Push yesterday's articles
bash tools/publish_wechat.sh --dry-run    # Preview
```

## Architecture

### `purifier.py` — main pipeline engine

**6 engines** in `AGENTS` dict: Arbitrage-Radar, Cross-Border-Insights, China-Going-Global, AI-Frontier, Developer-Goldmine, Macro-Events. Each has feeds (9-17 URLs), briefing_prompt, deep_dive_prompt.

**Flow per engine:**
1. `fetch_and_augment()` — parallel RSS fetch (4 workers) + DuckDuckGo RAG (5 results). Feed caching via `_FEED_CACHE` (5min TTL) prevents cross-engine URL re-fetch.
2. `deep_dive_worker()` — one DeepSeek API call generates both `briefing` and optional `deep_dive` JSON. Uses `_extract_json()` with balanced-brace matching + multi-level repair.
3. `save_deep_dive()` / `save_aggregated_briefing()` — write Hugo Markdown via `_write_hugo_post()` helper.
4. `send_deep_dive_tg()` / `send_aggregated_briefing_tg()` — Telegram push via `_tg_post()`.

**Key design decisions:**
- All datetimes use `bj_now()` (UTC+8) for Beijing time consistency
- Deep dive filenames include HHMM timestamp to avoid multi-run overwrites
- Deep dives: quality-gated (宁缺毋滥), core chapters ≥1200 words, code optional
- Briefings: 6 engines aggregated into ONE file per day under `daily-briefing/`
- Feed fetching: `feedparser.parse(url)` preferred for RSS compatibility, `requests.get()` as fallback

### `tools/wechat_publisher.py` — WeChat Official Account draft publisher

Runs on Tencent Cloud server (not GitHub Actions). Flow:
1. `find_articles()` — scan `content/posts/` for today's deep dives, skip already-published (tracked in `tools/.published`)
2. Dual-engine cover image generation (通义万相 primary, 智谱 CogView fallback)
3. `md_to_wechat_html()` — Markdown to WeChat-compatible HTML with branded header/footer
4. `optimize_wechat_title()` — byte-level truncation (30B title, 60B digest) for WeChat API limits
5. `sanitize_for_wechat()` — sensitive content pattern scanning with review warnings

### `tools/publish_wechat.sh` — server-side convenience script

Wraps git fetch + source .env + python3 wechat_publisher.py.

### Site config

- `hugo.toml` — PaperMod theme, 9 nav items (首页→每日快讯→6 engines→关于), logo.svg favicon, Asia/Shanghai timezone
- `static/css/custom.css` — mobile-first responsive (44px touch targets, bottom nav bar, safe-area)
- `layouts/_partials/` — extend_head.html (SEO/JSON-LD/AI crawler hints), extend_footer.html (mobile nav + Busuanzi page counter)
- `static/robots.txt` — allow all AI crawlers, block SEO tools

### GitHub Actions (`.github/workflows/main.yml`)

Daily at UTC 22:00 (06:00 BJT). Steps: checkout (with PaperMod submodule) → pip install → purifier.py (10 env vars) → git commit + push → mirror push to self-hosted GitLab → fetch covers from GitLab → Hugo build → deploy to gh-pages via peaceiris/actions-gh-pages.

## Environment variables

**pipeline (10 vars):** DEEPSEEK_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TG_THREAD_ARBITRAGE, TG_THREAD_AI, TG_THREAD_CROSS, TG_THREAD_MACRO, TG_THREAD_CHINA, TG_THREAD_DEV, TG_THREAD_BRIEFING

**GitLab mirror (3 vars):** GITLAB_HOST, GITLAB_USERNAME, GITLAB_ACCESS_TOKEN

**WeChat publisher (5 vars, on Tencent server):** WECHAT_APPID, WECHAT_APPSECRET, WECHAT_AUTHOR, DASHSCOPE_API_KEY, ZHIPU_API_KEY

## Critical bugs to avoid

- **Telegram URL**: Must be `f"https://api.telegram.org/bot{TOKEN}/sendMessage"` — never Markdown link format
- **Workflow env injection**: All 10 TG vars must be in the workflow `env:` block. Missing TG_THREAD_* = messages go to main chat instead of topics
- **TOML syntax**: Use `[params.section]` notation, NOT YAML-style indentation
- **Curly quotes**: The Edit tool sometimes corrupts Unicode quotes. Use PowerShell byte-level fix if `"` or `"` appear in Python source
- **WeChat title limit**: 32 bytes (≈10 Chinese chars). Use `optimize_wechat_title()` with byte-level truncation
- **WeChat digest limit**: 64 bytes. Use `DIGEST_BYTES = 60` for safe margin
- **Time zone**: Always use `bj_now()` (UTC+8) in purifier.py. Server-side datetime is CST natively
