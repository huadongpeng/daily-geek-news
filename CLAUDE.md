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
  -> long-form articles
  -> Gemini Banana cover prompts for WeChat
  -> Telegram notification + Hugo website
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
4. Search around selected deep candidates using DuckDuckGo.
5. Ask the LLM to write 1-3 deep-dive articles.
6. Write Hugo Markdown under `content/posts/`.
7. Write WeChat-ready source files under `outputs/wechat_articles/`.
8. Send a Telegram summary if configured.

Focus areas:

- `ai-tech`: AI technical news, official releases, papers, developer tooling.
- `income-lab`: side income, micro-SaaS, solo products, low-cost experiments.
- `world-signals`: major social events and life-impacting signals.
- `info-gap`: cross-language, cross-region, cross-platform information gaps.

## Environment Variables

Required:

- `DEEPSEEK_API_KEY`

Optional:

- `DEEPSEEK_MODEL`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TG_THREAD_BRIEFING`
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
- Keep generated WeChat-ready article source files under `outputs/wechat_articles/`.
- The project has historical content under older categories. New generated content should use the four new categories.
