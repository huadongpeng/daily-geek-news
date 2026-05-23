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
  -> Phase 1: investigation report (objective, structured) -> Hugo website
  -> Phase 2: WeChat article (personal voice re-telling) -> email + outputs/wechat_articles/
  -> Telegram notification
```

## Commands

```bash
pip install feedparser requests ddgs

python purifier.py --slot morning
python purifier.py --slot evening

hugo serve
hugo --minify
```

## Configuration

Prompt and editorial configuration lives in `config/`:

- `config/persona.md`
- `config/research_skill.md`
- `config/writing_skill.md`

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
5. **Phase 1** — Ask Pro model to write objective investigation reports → save to Hugo under `content/posts/{category}/investigation-*.md`.
6. **Phase 2** — Ask Pro model to rewrite each report in Easton's personal voice → save to `outputs/wechat_articles/` and send by email.
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

`.github/workflows/main.yml` runs twice daily:

- 06:00 Beijing
- 18:00 Beijing

The workflow runs `purifier.py`, commits generated Markdown and WeChat-ready source files, builds Hugo, and deploys to GitHub Pages.

## Notes

- Do not reintroduce WeChat API publishing or image-generation API calls into the main path unless explicitly requested.
- Keep generated content under `content/posts/`.
- Keep generated WeChat-ready article source files under `outputs/wechat_articles/` (gitignored — not committed to repo).
- The project has historical content under older category slugs. New generated content must use the four new slugs above.
- Research uses guarded AI-guided search: FLASH generates queries → seed/search pages are fetched → evidence is deduplicated and checked → PRO+thinking analyzes only candidates that pass the evidence threshold. No DeepSeek tool-calling (causes 400 errors).
- WeChat articles are written as Easton Hua / 老花 (first person identity, not ghostwriter). Fixed sign-off format required at the end of every article.
