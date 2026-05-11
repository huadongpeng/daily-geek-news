# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Automated pipeline that fetches overseas RSS feeds daily, uses DeepSeek's flagship model + DuckDuckGo RAG to generate Chinese-language deep-dive articles, deploys them as a Hugo static site to GitHub Pages, and pushes Telegram notifications per category topic.

## Commands

```bash
# Run the intelligence pipeline (generates Markdown under content/posts/)
python purifier.py

# Local Hugo preview
hugo serve

# Build for production
hugo --minify
```

No test suite or linting is configured.

## Architecture

`purifier.py` is the single-file core engine. It defines 4 independent "agents" in the `AGENTS` dict — each with RSS feeds, a persona prompt, and a Telegram topic. On each run:

1. **RSS Fetch + RAG** (`fetch_and_augment`): Pulls top 3 entries per feed, strips HTML, then calls DuckDuckGo (`duckduckgo_search`) for supplemental context on the top-ranked article.
2. **DeepSeek API** (`deep_dive_worker`): Sends the augmented context + persona prompt to `deepseek-chat` (V4 Pro). Parses the response for a JSON object with `title`, `content_md`, and `tg_summary` fields. All 4 agents run concurrently via `ThreadPoolExecutor`.
3. **Hugo output** (`save_to_hugo`): Writes frontmatter + body Markdown to `content/posts/<CategoryName>/deep-dive-YYYY-MM-DD.md`.
4. **Telegram push** (`send_to_telegram`): Sends a summary to the configured chat, optionally routing to a topic thread via `message_thread_id`.

`hugo.toml` configures the PaperMod theme and 4 category-based nav menu entries.

`.github/workflows/main.yml` runs daily at 22:00 UTC (06:00 Beijing). Steps: checkout (with submodules), install Python deps, run `purifier.py`, commit generated posts, build Hugo, deploy to `gh-pages` branch via `peaceiris/actions-gh-pages`.

The PaperMod theme is a git submodule at `themes/PaperMod`.

## Environment variables

All secrets are injected via GitHub Actions. Local runs need these set:

- `DEEPSEEK_API_KEY` — DeepSeek API key
- `TELEGRAM_BOT_TOKEN` — Telegram bot token
- `TELEGRAM_CHAT_ID` — Target chat/group ID
- `TG_THREAD_ARBITRAGE`, `TG_THREAD_AI`, `TG_THREAD_CROSS`, `TG_THREAD_MACRO` — optional per-category Telegram topic IDs

## Important notes

- **Telegram URL bug**: The Telegram API URL must be a plain string `f"https://api.telegram.org/bot{TOKEN}/sendMessage"`. A known corruption rewrites it as a Markdown link `[https://...](https://...)` which causes `requests` to fail with "No connection adapters were found". Always verify this line after editing.
- **DeepSeek model**: Uses `deepseek-chat` (DeepSeek V4 Pro). The older `deepseek-reasoner` model name should not be reintroduced. If the API evolves, check the latest model ID at https://api-docs.deepseek.com.
- **No `response_format`**: The code relies on regex extraction (`re.search(r'\{.*\}', ...)`) to pull JSON from the model response rather than Structured Outputs, because reasoning-oriented models may not consistently support `response_format: json_object`.
- **DuckDuckGo search**: Used for zero-cost, no-proxy external context retrieval. If `duckduckgo-search` breaks (rate limits, API changes), the pipeline falls back to RSS-only mode.
