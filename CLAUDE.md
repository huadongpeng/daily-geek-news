# CLAUDE.md

This file provides guidance to coding agents working in this repository.

## Project Overview

Easton Radar is a personal intelligence pipeline for a mid-career software engineering manager in a small company.

Persona:

> 一个小公司的软件技术经理，人到中年，还在摸爬滚打。不教你成功，只分享我探索的方向、踩过的坑，和那些让我"卧槽"的东西。

The project does not call the WeChat official API yet. It does generate WeChat-ready article source files. The core loop is:

```text
first-hand / near-source RSS
  -> persona-based filtering
  -> daily briefing
  -> deep research on selected candidates
  -> Phase 1: investigation article (evidence-grounded, with Easton's personal closing) -> Astro website
  -> Phase 2: reuse the same article for WeChat-ready source files -> email + outputs/wechat_articles/
  -> Telegram notification
```

## Commands

```bash
pip install feedparser requests ddgs

python purifier.py --slot morning
python purifier.py --slot evening

npm run dev
npm run build

# Windows PowerShell may block npm.ps1; use npm.cmd if needed:
npm.cmd run dev
npm.cmd run build
```

## Configuration

Prompt and editorial configuration lives in `config/`:

- `config/persona.md`
- `config/research_skill.md`
- `config/writing_skill.md`
- `config/sources.json`

These can be overridden with:

- `PERSONA_PATH`
- `RESEARCH_SKILL_PATH`
- `WRITING_SKILL_PATH`

## Main Script

`purifier.py` owns the full pipeline:

1. Collect RSS entries from source-oriented feeds.
2. Ask the LLM to filter items against the persona and four focus areas.
3. Generate the daily briefing.
4. Research selected deep candidates: FLASH generates targeted queries, seed URLs and search results are fetched, evidence is deduplicated, and weak-evidence candidates are skipped.
5. **Phase 1** — Ask Pro model to write evidence-grounded investigation articles with a first-person Easton closing → save to Astro under `src/content/blog/{category}/investigation-*.md`.
6. **Phase 2** — Reuse the same article body for WeChat-ready source files → save to `outputs/wechat_articles/` and send by email. Do not run a second LLM rewrite for WeChat.
7. Send a Telegram summary if configured.

Focus areas (priority order — pick first match):

1. `side-hustle`: clear side-income path, ordinary person can start validating within a week.
2. `ai-tools`: an AI tool/capability as the main subject, usable today by developers or general users.
3. `overseas`: cross-language/cross-region information gap, Chinese-speaking readers likely haven't seen it.
4. `life-signal`: doesn't fit above three, but affects ordinary people's work/income/life decisions (catch-all).

**严禁创造新 slug** — topic field must be one of these four exact values.

## Environment Variables

Required:

- `DEEPSEEK_API_KEY`

Optional:

- `DEEPSEEK_FLASH_MODEL`
- `DEEPSEEK_FLASH_THINKING`
- `DEEPSEEK_FLASH_REASONING_EFFORT`
- `DEEPSEEK_PRO_MODEL`
- `DEEPSEEK_PRO_THINKING`
- `DEEPSEEK_PRO_REASONING_EFFORT`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TG_THREAD_BRIEFING`
- `EMAIL_FROM` — sender email address (SMTP auto-detected by domain: QQ→ssl:465, Outlook/Gmail→starttls:587)
- `EMAIL_PASSWORD` — email password or app password
- `EMAIL_TO` — recipient address (default: huadongpeng@outlook.com)
- `PERSONA_PATH`
- `RESEARCH_SKILL_PATH`
- `WRITING_SKILL_PATH`

## Deployment

`.github/workflows/deploy.yml` has three triggers:

- **Schedule** — twice daily, 06:00 and 18:00 Beijing time. Runs the full pipeline.
- **Manual (`workflow_dispatch`)** — run the **full pipeline on demand** to verify the whole flow end to end. GitHub → Actions → "Easton Radar — Build & Deploy" → **Run workflow**, pick a `slot` (`auto` / `morning` / `evening`). Or via CLI: `gh workflow run deploy.yml -f slot=evening`. This behaves exactly like a scheduled run (DeepSeek, covers, email, Telegram, WeChat draft push), so it's the way to validate fixes without waiting for the cron.
- **Push to `main`** — only builds/deploys the current site (gated by `paths:`). It must **not** run the intelligence pipeline or call DeepSeek.

Pipeline-vs-build gating is driven by `github.event_name != 'push'`: schedule and manual dispatch run `generate-content` and the WeChat-draft steps; pushes skip them and only build/deploy.

The workflow runs `purifier.py`, commits generated Markdown and cover images, builds Astro, and deploys `dist/` to the VPS via rsync.

## Notes

- Do not reintroduce WeChat API publishing or image-generation API calls into the main path unless explicitly requested.
- Keep generated website content under `src/content/blog/`.
- Keep generated WeChat-ready article source files under `outputs/wechat_articles/` (gitignored — not committed to repo).
- The project has historical content under older category slugs. New generated content must use the four new slugs above.
- Research uses guarded AI-guided search: FLASH generates queries → seed/search pages are fetched → evidence is deduplicated and checked → PRO+thinking analyzes only candidates that pass the evidence threshold. No DeepSeek tool-calling (causes 400 errors).
- WeChat articles are written as Easton Hua / 老花 (first person identity, not ghostwriter). Fixed sign-off format required at the end of every article.
- Website investigation articles should be readable articles, not rigid reports. Avoid fixed headings like "导言 / 核心段 / 证据展开 / 反驳视角 / 影响与悬问"; keep evidence labels in the body where they matter.
- Avoid stiff phrases like "对普通技术经理的现实影响" or "像 Easton 这样的普通技术经理". Use Easton's actual voice near the end: "咱们这些快毕业/刚毕业的 IT 打工人", "35 岁门槛前后的程序员", "大龄程序员", "怕失业的人", etc.
- Runtime health files live under `.cache/radar/`: source health and pending search-engine push queues. These are diagnostics/artifacts, not source content.
