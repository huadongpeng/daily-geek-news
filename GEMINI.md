# GEMINI.md

Easton Radar is a source-first personal intelligence pipeline.

## Current Flow

```text
RSS source collection
  -> persona filter
  -> briefing
  -> deeper search and evidence review
  -> long-form articles
  -> Gemini Banana cover prompt
  -> Telegram + Hugo website
```

## Persona

一个小公司的软件技术经理，人到中年，还在摸爬滚打。不教你成功，只分享我探索的方向、踩过的坑，和那些让我"卧槽"的东西。

## Focus Areas

- AI 技术雷达
- 赚钱副业实验室
- 社会热点与生活信号
- 信息差雷达

## Key Files

- `purifier.py`: pipeline entrypoint
- `config/persona.md`: persona
- `config/research_skill.md`: source tracing and research method
- `config/writing_skill.md`: article style method
- `.github/workflows/main.yml`: twice-daily automation
- `hugo.toml`: site config

## Local Commands

```bash
pip install feedparser requests ddgs
python purifier.py --slot morning
hugo serve
```

WeChat API publishing and image-generation API calls are intentionally not part of the main path. The pipeline only writes WeChat-ready source files under `outputs/wechat_articles/`.
