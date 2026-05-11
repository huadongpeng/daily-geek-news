# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Automated pipeline that scans 20+ overseas RSS feeds daily, uses DeepSeek V4 Pro to generate Chinese-language intelligence briefings + optional deep-dive articles, deploys via Hugo to GitHub Pages, and pushes enriched Telegram notifications per category topic.

## Commands

```bash
pip install feedparser requests duckduckgo-search  # dependencies
python purifier.py    # Run pipeline → generates content/posts/
hugo serve            # Local preview
hugo --minify         # Production build → public/
```

No test suite or linting.

## Architecture

`purifier.py` — single-file core engine with a **dual-track output model**:

### Track 1: Daily Briefing (always)
Each of 4 agents produces a briefing with 3-5 info items. Each item includes: title, source, one-liner, why-matters, and a zero-cost angle. Briefings are always saved to Hugo and pushed to Telegram.

### Track 2: Deep Dive (quality-gated)
Each agent evaluates whether its top article warrants deep analysis. The model decides — returns `null` if nothing is worth it. Deep dives follow a 4-chapter structure specific to each agent, with code requirements (30-40+ lines), word counts (500+), and data-driven analysis.

### Agent config (`AGENTS` dict)
Each agent has: `feeds` (list), `briefing_prompt` (for daily summary), `deep_dive_prompt` (for optional long-form). Both prompts instruct the model to output a single JSON with `briefing` and `deep_dive` fields.

### Flow
1. `fetch_and_augment()` — RSS parsing + DuckDuckGo RAG (5 results per query)
2. `deep_dive_worker()` — Single API call to DeepSeek generates both briefing + optional deep dive
3. `save_to_hugo()` — Writes `briefing-YYYY-MM-DD.md` and optionally `deep-dive-YYYY-MM-DD.md`
4. `send_to_telegram()` — Pushes enriched briefing + separate deep dive message to group topics
5. All 4 agents run concurrently via `ThreadPoolExecutor(max_workers=4)`

### Content output
- `content/posts/<Category>/briefing-YYYY-MM-DD.md` — always
- `content/posts/<Category>/deep-dive-YYYY-MM-DD.md` — quality-gated
- `content/about.md` — personal/about page

### Site config
`hugo.toml` uses PaperMod theme with profile mode on homepage. Custom domain via `static/CNAME`.

`.github/workflows/main.yml` — daily at 22:00 UTC. Steps: checkout (with submodules), Python deps, run purifier.py (with 7 env vars), commit generated posts, Hugo build, deploy to gh-pages.

PaperMod theme at `themes/PaperMod` (git submodule).

## Environment variables

All 7 must be set in GitHub Secrets AND injected in the workflow `env` block:

- `DEEPSEEK_API_KEY` — DeepSeek API key
- `TELEGRAM_BOT_TOKEN` — Telegram bot token
- `TELEGRAM_CHAT_ID` — Supergroup ID (format: `-100xxxxxxxxx`)
- `TG_THREAD_ARBITRAGE` — Arbitrage topic ID
- `TG_THREAD_AI` — AI topic ID
- `TG_THREAD_CROSS` — Cross-border topic ID
- `TG_THREAD_MACRO` — Macro topic ID

## Critical bugs to avoid

- **Telegram URL corruption**: The API URL must be `f"https://api.telegram.org/bot{TOKEN}/sendMessage"` — never a Markdown link format `[https://...](https://...)`. Verify after any edit to the Telegram function.
- **Missing workflow env vars**: All 7 env vars must be injected in the workflow YAML `env:` block. If TG_THREAD_* vars are missing, messages go to the main chat instead of topics.
- **DeepSeek model**: Use `deepseek-chat` (V4 Pro). Model parameters like `thinking` or `tools` may not be supported — keep the payload clean (`model` + `messages` only) unless confirmed supported by the API.

## Zero-cost principle

All prompts enforce a hard requirement: personal opportunities must assume zero-cost or low-cost (< 500 RMB) startup. This is a core editorial stance across all 4 agents.
