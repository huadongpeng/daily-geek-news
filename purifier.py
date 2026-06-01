import argparse
import concurrent.futures
import sys

# On Windows, cmd/PowerShell defaults to GBK which breaks emoji in print().
# CI sets PYTHONIOENCODING=utf-8 in the workflow env; this guard handles local
# Windows dev sessions where that variable is absent.
# errors="backslashreplace" preserves unencodable chars in escaped form rather
# than silently dropping them.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
import hashlib
import html
import json
import os
import re
import smtplib
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import feedparser
import requests
from ddgs import DDGS


BJT = timezone(timedelta(hours=8))
SITE_URL = os.environ.get("SITE_URL", "https://radar.huadongpeng.com").rstrip("/")
FLASH_MODEL = os.environ.get("DEEPSEEK_FLASH_MODEL", os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"))
PRO_MODEL = os.environ.get("DEEPSEEK_PRO_MODEL", "deepseek-v4-pro")
FLASH_THINKING = os.environ.get("DEEPSEEK_FLASH_THINKING", "disabled")
FLASH_REASONING_EFFORT = os.environ.get("DEEPSEEK_FLASH_REASONING_EFFORT", "low")
PRO_THINKING = os.environ.get("DEEPSEEK_PRO_THINKING", os.environ.get("DEEPSEEK_THINKING", "enabled"))
PRO_REASONING_EFFORT = os.environ.get("DEEPSEEK_PRO_REASONING_EFFORT", os.environ.get("DEEPSEEK_REASONING_EFFORT", "max"))
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
TG_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TG_THREAD_BRIEFING = os.environ.get("TG_THREAD_BRIEFING")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "huadongpeng@outlook.com")
EMAIL_SMTP_HOST = os.environ.get("EMAIL_SMTP_HOST", "")
EMAIL_SMTP_PORT = int(os.environ.get("EMAIL_SMTP_PORT", "0"))
ROOT = Path(__file__).resolve().parent
CONTENT_DIR = ROOT / "src" / "content" / "blog"
CACHE_DIR = ROOT / ".cache" / "radar"
WECHAT_OUTPUT_DIR = ROOT / "outputs" / "wechat_articles"
COVERS_DIR = ROOT / "public" / "images" / "covers"
SILICONFLOW_API_KEY = os.environ.get("SILICONFLOW_API_KEY")
MIN_EVIDENCE_ITEMS = 3
MIN_EVIDENCE_DOMAINS = 2
MAX_FULLTEXT_EVIDENCE = 8
MAX_SEARCH_PAGE_FETCHES = 12
MAX_EVIDENCE_TEXT_CHARS = 5000


@dataclass(frozen=True)
class Topic:
    slug: str
    title: str
    category: str
    intent: str
    feeds: tuple[str, ...]
    search_seeds: tuple[str, ...]


TOPICS: tuple[Topic, ...] = (
    Topic(
        slug="ai-tools",
        title="AI 工具前线",
        category="ai-tools",
        intent=(
            "今天能实际用上的 AI 工具、模型能力变化、工程实践。"
            "优先官方发布、开发者可直接调用的新能力、编码代理更新。"
            "过滤纯融资新闻、营销口水、纯学术论文（除非有立竿见影的工程意义）。"
            "【判断标准】主角是一个 AI 工具/能力，且开发者/普通用户今天就能试用 → 此分类。"
        ),
        feeds=(
            "https://openai.com/blog/rss.xml",
            "https://blog.google/technology/ai/rss/",
            "https://huggingface.co/blog/feed.xml",
            "https://arxiv.org/rss/cs.AI",
            "https://arxiv.org/rss/cs.LG",
            "https://news.ycombinator.com/rss",
            "https://dev.to/feed/tag/ai",
            "https://venturebeat.com/category/ai/feed/",
        ),
        search_seeds=("AI model release site:openai.com OR site:google.com", "AI coding agent new feature", "AI tool developer update"),
    ),
    Topic(
        slug="side-hustle",
        title="副业实验室",
        category="side-hustle",
        intent=(
            "普通人可以低成本验证的赚钱路径和市场空缺。"
            "优先有具体操作步骤、真实案例、平台规则变化、需求外溢信号。"
            "过滤大公司战略、VC 融资、无操作路径的机会分析。"
            "【判断标准】这件事有明确的副业路径，普通人能在一周内开始验证 → 此分类（优先级最高）。"
        ),
        feeds=(
            "https://news.ycombinator.com/rss",
            "https://www.producthunt.com/feed",
            "https://www.reddit.com/r/SaaS/top/.rss?t=day",
            "https://www.reddit.com/r/SideProject/top/.rss?t=day",
            "https://www.reddit.com/r/Entrepreneur/top/.rss?t=day",
            "https://www.reddit.com/r/SomebodyMakeThis/top/.rss?t=day",
            "https://www.reddit.com/r/freelance/top/.rss?t=day",
            "https://v2ex.com/feed/create.xml",
        ),
        search_seeds=("side project revenue case study", "indie hacker success story", "micro saas market gap"),
    ),
    Topic(
        slug="overseas",
        title="出海信号",
        category="overseas",
        intent=(
            "海外已发生但中文圈还没注意到的趋势、机会、规则变化和信息差。"
            "优先：海外平台政策变化、跨地区商业模式差异、非中文圈的用户需求/抱怨、"
            "中外同一事件的叙事差异。过滤中文圈已大量报道的内容。"
            "【判断标准】这条信息有跨语言/跨地区的信息差价值，中文圈读者大概率没看到 → 此分类。"
        ),
        feeds=(
            "https://restofworld.org/feed/latest/",
            "https://www.wired.com/feed/rss",
            "https://www.semafor.com/rss.xml",
            "http://www.chinadaily.com.cn/rss/world_rss.xml",
            "http://www.chinadaily.com.cn/rss/bizchina_rss.xml",
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            "https://www.reddit.com/r/digitalnomad/top/.rss?t=day",
            "https://www.reddit.com/r/InternetIsBeautiful/top/.rss?t=day",
            "https://www.producthunt.com/feed",
        ),
        search_seeds=("overseas market China information gap", "emerging market platform opportunity", "cross-border business trend 2025"),
    ),
    Topic(
        slug="life-signal",
        title="生活信号",
        category="life-signal",
        intent=(
            "可能影响普通人工作、收入、生活决策的宏观社会/经济/政策变化。"
            "优先：利率/就业政策变化、平台监管、大规模裁员潮、消费趋势。"
            "过滤纯政治外交、和普通人生活无关的宏观分析。"
            "【判断标准】不是AI工具/副业路径/海外信息差，但这件事会影响普通人今后的决策 → 此分类（兜底）。"
        ),
        feeds=(
            "https://www.federalreserve.gov/feeds/press_all.xml",
            "https://www.sec.gov/news/pressreleases.rss",
            "https://www.ecb.europa.eu/rss/press.html",
            "http://www.chinadaily.com.cn/rss/china_rss.xml",
            "https://feeds.bbci.co.uk/news/business/rss.xml",
            "https://www.theguardian.com/world/rss",
            "https://www.theverge.com/rss/index.xml",
            "https://techcrunch.com/feed/",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        ),
        search_seeds=("tech layoffs 2025", "platform policy change affects workers", "consumer economy trend"),
    ),
)


PERSONA_DEFAULT = """
Easton，30多岁，信阳人，IT技术经理，负责公司软件研发的所有内容，一个人扛着整个技术方向。
日子过得比较艰难，压力不小，这影响他对风险的判断——比普通人更在乎代价，更在乎这事我真的能做吗。

日常：喝信阳毛尖，下班喝点小酒（白的黄的啤的都行），平时逛论坛刷帖子玩英雄联盟，
周末去奥乐齐/河马奥莱这类平价超市，或者找地方露营看网络小说一呆一下午。

认知模式（核心特征）：研究得很深，实践得很少。对感兴趣的东西会做很深的信息检索和筛选，
有自己的思维框架，能看到别人不一定看到的角度。但受限于经济情况和性格特征，真正下场尝试的次数有限。
对新事物往往研究到七八成深度，站在可以开始动手了的门口——然后没有迈进去。
这是真实的自我描述，也是可以自嘲的地方。

写给和他处境类似的人：想探副业但启动资金有限，想睁眼看世界但信息来源乱，研究了不少但不知道怎么开始的普通打工人。
不教人成功，只是一个站在门口研究了很久但还没迈进去的人，认真把自己看到的东西写出来。
"""

RESEARCH_METHOD_DEFAULT = """
信息探索原则：
1. 优先官方公告、原始论文、公司文档、监管文件、当事人原帖；其次主流媒体、行业媒体、开发者讨论。
2. 来源必须分层：高可信 / 中可信 / 线索级，不能混写在一起。
3. 明确区分已确认事实、高概率推断、待验证线索、观点/立场，不把猜测包装成结论。
4. 引用商业公司报告时标注利益动机，对数字打折说明。
5. 不把单个 Reddit/论坛帖子写成确定事实，只当需求线索。
6. 整理结果时：找最重要的 2-3 个有据可查的事实，找最反直觉/最让人停下来的 1-2 个角度。
"""

WRITING_METHOD_DEFAULT = """
写作原则：
开头必须从一个具体细节切入（时间、价格、页面、报错、聊天句子），绝不用"在当今AI快速发展的时代"。
文章风格是有见识的普通技术人在认真聊一件打动他的事，不是媒体报道，不是知识付费教程。
反证和不确定性嵌在正文中间出现，不单独开一节。
来源可信度在正文引用时就带出来，不在文章末尾单独开"信息来源与可信度"一节。
标题要短，避免夸张承诺，宁可少写也不要水。

结构禁令：
- 禁止"一、二、三、四、五、六"数字编号大标题
- 禁止"本周/两周内/一个月内"三段时间轴行动计划
- 禁止工具推荐列满四五个选项，只写自己真正用过或打算用的那一两个
- 禁止引用数据不带个人判断（说明来源动机、说明我信几成）
"""


def bj_now() -> datetime:
    return datetime.now(BJT)


def load_optional_text(env_name: str, fallback: str) -> str:
    path = os.environ.get(env_name)
    if not path:
        return fallback.strip()
    p = Path(path)
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError as exc:
        print(f"   ⚠️ 无法读取 {env_name}={path}: {exc}")
        return fallback.strip()


def load_text_config(env_name: str, default_path: Path, fallback: str) -> str:
    if os.environ.get(env_name):
        return load_optional_text(env_name, fallback)
    if default_path.exists():
        return default_path.read_text(encoding="utf-8").strip()
    return fallback.strip()


def generate_cover_prompt(title: str, summary: str) -> str:
    """Ask Flash to produce a concise English image-generation prompt for a cover."""
    try:
        result = llm_json(
            system=(
                "You are a creative director. Generate a concise English image prompt for an article cover."
                " Output only valid JSON, no markdown."
            ),
            user=(
                f"Article title: {title}\n"
                f"Summary: {summary[:300]}\n\n"
                "Generate an English image prompt under 30 words for a 16:9 cover image. "
                "Minimalist or flat-vector style. No text, no logos, no human faces. "
                'Output JSON: {"prompt": "..."}'
            ),
            max_tokens=200,
            model=FLASH_MODEL,
            thinking_type="disabled",
            reasoning_effort="low",
        )
        prompt = (result.get("prompt") or "").strip()
        return prompt or f"Minimalist digital art representing '{title[:40]}', clean background, technology aesthetic, 16:9"
    except Exception as exc:
        print(f"   ⚠️ 封面提示词生成失败: {exc}")
        return f"Minimalist digital art, clean background, technology aesthetic, 16:9"


def generate_cover_image(prompt: str, filename_stem: str) -> str:
    """Generate cover via SiliconFlow FLUX.1-schnell; fall back to Pollinations.ai.

    Returns the public-relative URL path ("/images/covers/foo.jpg") or empty string.
    """
    output_path = COVERS_DIR / f"{filename_stem}.jpg"

    if SILICONFLOW_API_KEY:
        try:
            resp = requests.post(
                "https://api.siliconflow.cn/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "black-forest-labs/FLUX.1-schnell",
                    "prompt": prompt,
                    "image_size": "1024x576",
                    "num_inference_steps": 4,
                },
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            images = data.get("images") or data.get("data") or []
            img_url = images[0].get("url", "") if images else ""
            if img_url:
                img_data = requests.get(img_url, timeout=60)
                img_data.raise_for_status()
                output_path.write_bytes(img_data.content)
                print(f"   🎨 封面图已生成 (SiliconFlow): {output_path.name}")
                return f"/images/covers/{output_path.name}"
        except Exception as exc:
            print(f"   ⚠️ SiliconFlow 生图失败，降级到 Pollinations: {exc}")

    try:
        encoded = quote(prompt, safe="")
        pol_url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            "?width=1024&height=576&nologo=true"
        )
        img_data = requests.get(pol_url, timeout=120, headers={"User-Agent": "EastonRadar/4.0"})
        img_data.raise_for_status()
        output_path.write_bytes(img_data.content)
        print(f"   🎨 封面图已生成 (Pollinations): {output_path.name}")
        return f"/images/covers/{output_path.name}"
    except Exception as exc:
        print(f"   ⚠️ 封面图生成失败: {exc}")
        return ""


def detect_slot(now: datetime, explicit: str | None) -> str:
    if explicit and explicit != "auto":
        return explicit
    return "morning" if now.hour < 12 else "evening"


def ensure_runtime() -> None:
    if not DEEPSEEK_API_KEY:
        raise SystemExit("❌ 缺少 DEEPSEEK_API_KEY，无法调用 AI 分析。")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    WECHAT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    COVERS_DIR.mkdir(parents=True, exist_ok=True)


def strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_entry_time(entry: Any) -> datetime | None:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not parsed:
        return None
    return datetime.fromtimestamp(time.mktime(parsed), tz=timezone.utc).astimezone(BJT)


def fetch_feed(url: str, limit: int, max_age_hours: int) -> list[dict[str, Any]]:
    try:
        resp = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "EastonRadar/4.0 (+https://radar.huadongpeng.com)"},
        )
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except Exception as exc:
        print(f"   ⚠️ RSS 失败: {url} | {exc}")
        return []

    cutoff = bj_now() - timedelta(hours=max_age_hours)
    items: list[dict[str, Any]] = []
    for entry in parsed.entries[: limit * 2]:
        published_at = parse_entry_time(entry)
        if published_at and published_at < cutoff:
            continue
        title = strip_tags(getattr(entry, "title", ""))
        if not title:
            continue
        summary = strip_tags(getattr(entry, "summary", "") or getattr(entry, "description", ""))[:600]
        items.append(
            {
                "title": title,
                "url": getattr(entry, "link", ""),
                "summary": summary,
                "published_at": published_at.isoformat() if published_at else "",
                "source": parsed.feed.get("title", url),
            }
        )
        if len(items) >= limit:
            break
    return items


def collect_sources(max_age_hours: int) -> dict[str, list[dict[str, Any]]]:
    print("📡 抓取一手/近源信息...")
    collected: dict[str, list[dict[str, Any]]] = {topic.slug: [] for topic in TOPICS}
    tasks: dict[Any, Topic] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        for topic in TOPICS:
            for feed in topic.feeds:
                tasks[pool.submit(fetch_feed, feed, 8, max_age_hours)] = topic
        for future in concurrent.futures.as_completed(tasks):
            topic = tasks[future]
            collected[topic.slug].extend(future.result())

    for topic in TOPICS:
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for item in collected[topic.slug]:
            key = item.get("url") or item["title"].lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        collected[topic.slug] = unique[:30]
        print(f"   {topic.title}: {len(collected[topic.slug])} 条")
    return collected


def llm_json(
    system: str,
    user: str,
    max_tokens: int = 8192,
    model: str | None = None,
    thinking_type: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    def parse_json_object(raw: str) -> dict[str, Any]:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        candidates = [raw]
        match = re.search(r"\{.*\}", raw, re.S)
        if match:
            candidates.append(match.group(0))
        last_error: Exception | None = None
        for candidate in candidates:
            try:
                return json.loads(candidate, strict=False)
            except json.JSONDecodeError as exc:
                last_error = exc
        raise last_error or ValueError("No JSON object found")

    last_error: Exception | None = None
    for attempt in range(2):
        chosen_model = model or FLASH_MODEL
        chosen_thinking = FLASH_THINKING if thinking_type is None else thinking_type
        chosen_effort = FLASH_REASONING_EFFORT if reasoning_effort is None else reasoning_effort
        user_content = user
        if attempt:
            user_content = (
                "上一次输出不是可解析 JSON。请只返回一个完整、合法、未截断的 JSON object。"
                "不要代码块，不要解释文字，字符串里的换行必须正确转义。\n\n"
                + user
            )
        thinking: dict[str, str] = {"type": chosen_thinking}
        if chosen_thinking == "enabled":
            thinking["reasoning_effort"] = chosen_effort
        payload: dict[str, Any] = {
            "model": chosen_model,
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "thinking": thinking,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_content}],
        }
        resp = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        finish_reason = choice.get("finish_reason")
        text = choice.get("message", {}).get("content") or ""
        if finish_reason == "length":
            last_error = ValueError("DeepSeek response was truncated because finish_reason=length")
            continue
        if not text.strip():
            last_error = ValueError("DeepSeek returned empty content")
            continue
        try:
            return parse_json_object(text)
        except Exception as exc:
            last_error = exc
            debug_path = CACHE_DIR / f"bad-json-{bj_now().strftime('%Y%m%d-%H%M%S')}-try{attempt + 1}.txt"
            debug_path.write_text(text, encoding="utf-8")

    raise ValueError(f"LLM JSON parse failed after retry: {last_error}") from last_error


def source_digest(collected: dict[str, list[dict[str, Any]]]) -> str:
    blocks: list[str] = []
    topic_map = {t.slug: t for t in TOPICS}
    for slug, items in collected.items():
        topic = topic_map[slug]
        blocks.append(f"\n## {topic.title}\n关注目标：{topic.intent}")
        for i, item in enumerate(items, 1):
            blocks.append(
                f"{i}. {item['title']}\n"
                f"source={item.get('source','')}\n"
                f"url={item.get('url','')}\n"
                f"time={item.get('published_at','')}\n"
                f"summary={item.get('summary','')}"
            )
    return "\n".join(blocks)


def load_recent_titles(days: int = 7) -> list[str]:
    """扫描 content/posts/ 下近 N 天内生成的深度文章标题，用于防重复。"""
    cutoff = bj_now() - timedelta(days=days)
    titles: list[str] = []
    for category in ("ai-tools", "side-hustle", "overseas", "life-signal"):
        cat_dir = CONTENT_DIR / category
        if not cat_dir.exists():
            continue
        for md_file in cat_dir.glob("*.md"):
            try:
                mtime = datetime.fromtimestamp(md_file.stat().st_mtime, tz=BJT)
                if mtime < cutoff:
                    continue
                text = md_file.read_text(encoding="utf-8")
                m = re.search(r'^title:\s*"([^"]+)"', text, re.MULTILINE)
                if m:
                    titles.append(m.group(1))
            except Exception:
                continue
    if titles:
        print(f"   📚 近 {days} 天已发布深度文章: {len(titles)} 篇，用于防重复选题")
    return titles


def initial_filter(
    collected: dict[str, list[dict[str, Any]]],
    persona: str,
    recent_titles: list[str],
) -> dict[str, Any]:
    print("🧭 初筛符合人设和关注方向的信息...")
    topics = "\n".join(f"- {t.title}: {t.intent}" for t in TOPICS)
    recent_block = ""
    if recent_titles:
        recent_block = (
            "\n【近7天已发布深度文章（选 deep_candidates 时主动回避主题高度重合的话题）】\n"
            + "\n".join(f"- {t}" for t in recent_titles)
        )
    return llm_json(
        system=(
            "你是 Easton 的个人情报编辑。任务是从源头信息中筛出真正值得进入日报的内容。"
            "你必须输出合法 JSON，不要 Markdown。"
        ),
        user=f"""
当前时间：{bj_now().strftime('%Y-%m-%d %H:%M')} BJT

【人设】
{persona}

【关注主题】
{topics}
{recent_block}

【候选信息】
{source_digest(collected)[:250000]}

请输出 JSON：
{{
  "briefing_items": [
    {{
      "topic": "ai-tools|side-hustle|overseas|life-signal",
      "title": "不超过16字",
      "source": "来源名",
      "url": "原始链接",
      "credibility": "高|中|线索",
      "why_it_matters": "为什么和我有关，60字内",
      "action": "今天能做的一个动作，60字内"
    }}
  ],
  "deep_candidates": [
    {{
      "topic": "ai-tools|side-hustle|overseas|life-signal",
      "title": "深度选题标题，16字内",
      "core_question": "这篇文章要回答的问题",
      "seed_urls": ["原始链接1", "原始链接2"],
      "reason": "为什么值得深挖"
    }}
  ]
}}

分类决策规则（按优先级顺序，选第一个匹配的）：
1. side-hustle：有明确副业路径，普通人能在一周内开始验证 → 最高优先级
2. ai-tools：主角是一个 AI 工具/能力，开发者/普通用户今天就能试用
3. overseas：有跨语言/跨地区信息差价值，中文圈读者大概率没看到
4. life-signal：不符合以上三项，但会影响普通人的工作/收入/生活决策 → 兜底

【严禁创造新 slug】topic 字段只能是上面 4 个值之一，不得自创任何其他分类名。

其他规则：
- briefing_items 总数 12-20 条，宁缺毋滥。
- deep_candidates 选择 2-4 个，必须能通过进一步检索验证。近7天已发布的主题优先跳过，除非有实质性新进展值得追。
- 优先官方、论文、原始帖、当事公司博客、权威媒体；少用二手转述。
""",
        model=FLASH_MODEL,
        thinking_type=FLASH_THINKING,
        reasoning_effort=FLASH_REASONING_EFFORT,
    )


def search_cache_key(query: str) -> Path:
    h = hashlib.sha256(query.encode("utf-8")).hexdigest()[:20]
    return CACHE_DIR / f"search-{h}.json"


def page_cache_key(url: str) -> Path:
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    return CACHE_DIR / f"page-{h}.json"


def hostname(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    return host.removeprefix("www.")


def web_search(query: str, max_results: int = 6) -> list[dict[str, str]]:
    cache = search_cache_key(query)
    if cache.exists() and time.time() - cache.stat().st_mtime < 60 * 60 * 12:
        return json.loads(cache.read_text(encoding="utf-8"))
    try:
        results = [
            {"title": r.get("title", ""), "url": r.get("href", ""), "body": r.get("body", "")}
            for r in DDGS().text(query, max_results=max_results)
        ]
    except Exception as exc:
        print(f"   ⚠️ 检索失败: {query[:80]} | {exc}")
        results = []
    cache.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def fetch_page_evidence(url: str, source_type: str, query: str = "") -> dict[str, Any] | None:
    """Fetch a lightweight text snapshot for stronger evidence than search snippets."""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return None

    cache = page_cache_key(url)
    if cache.exists() and time.time() - cache.stat().st_mtime < 60 * 60 * 24:
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if cached.get("ok"):
                return cached.get("evidence")
            return None
        except Exception:
            pass

    evidence: dict[str, Any] | None = None
    try:
        resp = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "EastonRadar/4.0 (+https://radar.huadongpeng.com)"},
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        is_text_like = (
            not content_type
            or "text/html" in content_type
            or "text/plain" in content_type
            or "xml" in content_type
            or "json" in content_type
        )
        if not is_text_like:
            raise ValueError(f"unsupported content-type: {content_type}")

        raw = resp.text[:400000]
        title_match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
        title = strip_tags(title_match.group(1)) if title_match else ""
        text = strip_tags(raw)[:MAX_EVIDENCE_TEXT_CHARS]
        if len(text) < 300:
            raise ValueError("page text too short")
        evidence = {
            "source_type": source_type,
            "query": query,
            "title": title,
            "url": url,
            "domain": hostname(url),
            "body": text,
            "body_type": "page_text",
        }
        cache.write_text(json.dumps({"ok": True, "evidence": evidence}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"      ⚠️ 正文抓取失败: {hostname(url) or url[:40]} | {exc}")
        cache.write_text(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), encoding="utf-8")
    return evidence


def _normalize_queries(raw_queries: Any) -> list[str]:
    if not isinstance(raw_queries, list):
        return []
    seen: set[str] = set()
    queries: list[str] = []
    for raw in raw_queries:
        if not isinstance(raw, str):
            continue
        query = re.sub(r"\s+", " ", raw).strip()
        if not query or len(query) > 220:
            continue
        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        queries.append(query)
    return queries[:8]


def _dedupe_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip().lower()
        key = url or f"{item.get('domain', '')}:{title}"
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _evidence_domains(evidence: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("domain") or hostname(str(item.get("url") or ""))) for item in evidence if item.get("url")}


def _has_minimum_evidence(evidence: list[dict[str, Any]]) -> bool:
    substantive = [item for item in evidence if item.get("body_type") == "page_text" and len(str(item.get("body") or "")) >= 500]
    domains = {d for d in _evidence_domains(evidence) if d}
    return len(evidence) >= MIN_EVIDENCE_ITEMS and len(domains) >= MIN_EVIDENCE_DOMAINS and bool(substantive)


def _collect_evidence(candidate: dict[str, Any], queries: list[str]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    seed_urls = [url for url in candidate.get("seed_urls", []) if isinstance(url, str)]

    for url in seed_urls[:3]:
        page = fetch_page_evidence(url, "seed_url")
        if page:
            evidence.append(page)

    search_hits: list[dict[str, Any]] = []
    for q in queries:
        hits = web_search(q, max_results=5)
        print(f"      🔍 {q[:70]}: {len(hits)} 条")
        for hit in hits:
            item = {
                "source_type": "search_result",
                "query": q,
                "title": hit.get("title", ""),
                "url": hit.get("url", ""),
                "domain": hostname(hit.get("url", "")),
                "body": hit.get("body", ""),
                "body_type": "search_snippet",
            }
            search_hits.append(item)

    for hit in _dedupe_evidence(search_hits)[:MAX_SEARCH_PAGE_FETCHES]:
        if len([item for item in evidence if item.get("body_type") == "page_text"]) >= MAX_FULLTEXT_EVIDENCE:
            break
        page = fetch_page_evidence(str(hit.get("url") or ""), "search_result", str(hit.get("query") or ""))
        evidence.append(page or hit)

    return _dedupe_evidence(evidence)


def _generate_search_queries(candidate: dict[str, Any]) -> list[str]:
    """Ask FLASH to generate targeted search queries for verifying a candidate's claims."""
    result = llm_json(
        system=(
            "你是一名信息检索专家。根据新闻线索，生成最有效的搜索查询来验证核心事实、寻找一手来源。"
            "优先英文查询（更易找到一手来源），中文查询用于中文市场相关内容。"
            "查询要具体且有针对性，能验证核心事实，而不是泛泛搜索主题。"
            "必须输出合法 JSON，不要代码块。"
        ),
        user=(
            f"新闻线索：{candidate.get('title', '')}\n"
            f"核心问题：{candidate.get('core_question', '')}\n"
            f"原始来源：{', '.join(candidate.get('seed_urls', [])[:2])}\n"
            f"深挖理由：{candidate.get('reason', '')}\n\n"
            '请生成 6-8 个最有价值的搜索查询，用于核实事实、寻找一手来源、交叉验证。\n'
            '输出 JSON：{"queries": ["query1", "query2", ...]}'
        ),
        max_tokens=800,
        model=FLASH_MODEL,
        thinking_type=FLASH_THINKING,
        reasoning_effort=FLASH_REASONING_EFFORT,
    )
    return _normalize_queries(result.get("queries"))


def _analyze_evidence(candidate: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
    """Use PRO to synthesize search evidence into structured research notes."""
    result = llm_json(
        system=(
            "你是一名深度信息探索专家。根据已收集的检索证据，对新闻线索做深度分析。\n"
            "严格区分已确认事实、高概率推断、待验证线索，标注每条信息的来源和可信度。\n"
            "只能使用输入证据，不得使用训练记忆补充事实。证据不足时必须明确写'证据不足，不能确认'。\n"
            "必须输出合法 JSON，不要代码块。"
        ),
        user=(
            f"新闻线索：{candidate.get('title', '')}\n"
            f"核心问题：{candidate.get('core_question', '')}\n\n"
            f"【检索证据（共 {len(evidence)} 条）】\n"
            f"{json.dumps(evidence, ensure_ascii=False)[:120000]}\n\n"
            "请根据以上证据输出结构化研究笔记。\n"
            '输出 JSON：{"research_notes": "完整研究笔记（中文）"}\n\n'
            "研究笔记必须包含以下几块：\n"
            "【已确认事实】只写输入证据中有多来源印证的事实，标注来源名称和可信级别（高可信/中可信）；没有就写'暂无足够证据'\n"
            "【高概率推断】单来源或间接证据支持，标注来源\n"
            "【待验证线索】无法核实的说法，标注来源\n"
            "【最有价值的角度】最反直觉或最让普通打工人停下来的 1-2 个点\n"
            "【来源分层】高可信/中可信/线索级 各列出具体来源名称"
        ),
        max_tokens=8000,
        model=PRO_MODEL,
        thinking_type=PRO_THINKING,
        reasoning_effort=PRO_REASONING_EFFORT,
    )
    return result.get("research_notes", "")


def research_with_tools(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Research deep candidates: FLASH generates queries → DDGS executes → PRO synthesizes."""
    print("🔎 AI 主导深度检索（Flash生成查询 → DDGS执行 → Pro分析）...")
    results: list[dict[str, Any]] = []
    for cand in candidates[:4]:
        title = cand.get("title", "")
        print(f"   📌 {title[:50]}")

        queries = _generate_search_queries(cand)
        print(f"      📝 生成 {len(queries)} 个检索查询")
        if not queries:
            print("      ⚠️ 未生成有效查询，跳过该候选")
            continue

        evidence = _collect_evidence(cand, queries)
        domains = {d for d in _evidence_domains(evidence) if d}
        page_count = len([item for item in evidence if item.get("body_type") == "page_text"])
        print(f"      📚 证据 {len(evidence)} 条，正文 {page_count} 条，独立域名 {len(domains)} 个")
        if not _has_minimum_evidence(evidence):
            print(
                "      ⚠️ 证据不足，跳过该候选 "
                f"（需要≥{MIN_EVIDENCE_ITEMS}条证据、≥{MIN_EVIDENCE_DOMAINS}个域名、至少1条正文）"
            )
            continue

        notes = _analyze_evidence(cand, evidence)
        if not notes.strip():
            print("      ⚠️ 研究笔记为空，跳过该候选")
            continue
        results.append({
            **cand,
            "research_method": "ai-guided-search",
            "evidence_count": len(evidence),
            "evidence_domains": sorted(domains),
            "research_notes": notes,
        })
        print(f"   ✅ 研究完成，笔记 {len(notes)} 字")
    return results


def compose_briefing(filtered: dict[str, Any], persona: str, slot: str) -> dict[str, Any]:
    print("📰 使用 Flash 生成简讯日报...")
    topic_titles = {t.slug: t.title for t in TOPICS}
    return llm_json(
        system=(
            "你是 Easton 的个人情报快编。你会把初筛信息整理成可发布到网站的中文简讯。"
            "必须输出合法 JSON，不要代码块。"
        ),
        user=f"""
当前时间：{bj_now().strftime('%Y-%m-%d %H:%M')} BJT
本次批次：{slot}

【人设】
{persona}

【主题映射】
{json.dumps(topic_titles, ensure_ascii=False)}

【初筛结果】
{json.dumps(filtered, ensure_ascii=False)[:100000]}

请输出 JSON：
{{
  "briefing": {{
    "title": "今日简讯标题",
    "summary": "100字内说明今天最重要的判断",
    "items": [
      {{
        "topic": "主题slug",
        "title": "短标题",
        "source": "来源",
        "url": "链接",
        "credibility": "高|中|线索",
        "why_it_matters": "为什么重要",
        "action": "下一步动作"
      }}
    ]
  }}
}}

简讯要求：
- items 从初筛 briefing_items 中优中择优，保留 10-18 条。
- 只写和人设相关、能指导关注/行动的信息；不要把来源不明的信息写成事实。
- why_it_matters 用人话说明与我有什么关系，action 给一个今天能做的小动作。
""",
        max_tokens=12000,
        model=FLASH_MODEL,
        thinking_type=FLASH_THINKING,
        reasoning_effort=FLASH_REASONING_EFFORT,
    )


# ─── 阶段一：网站深度调查报告 ───────────────────────────────────────────────

def compose_investigation_reports(
    filtered: dict[str, Any],
    researched: list[dict[str, Any]],
    research_method: str,
    slot: str,
    recent_titles: list[str] | None = None,
) -> dict[str, Any]:
    print("📋 阶段一：使用 Pro max 生成深度调查报告（网站版）...")
    topic_titles = {t.slug: t.title for t in TOPICS}
    recent_block = ""
    if recent_titles:
        recent_block = (
            "\n【近7天已发布深度文章（主题高度重合的直接跳过，不要输出）】\n"
            + "\n".join(f"- {t}" for t in recent_titles)
            + "\n"
        )
    return llm_json(
        system=(
            "你是一名专业新闻调查记者，负责撰写供网站发布的中文深度调查报告。"
            "你的读者主要是 Easton 本人，以及特别在意信息溯源、辨别真假、深度分析的读者——他们想看到来源清晰、不确定性明确标注、论据可查的内容，而不是观点的堆砌。"
            "写作标准参照《经济学人》和优质路透社深度报道：事实第一，观点有据，不确定性明确标注，结构清晰但不刻板。"
            "严格按照【信息探索与研究方法论】的证据标准工作。"
            "必须输出合法 JSON，不要代码块。"
        ),
        user=f"""
当前时间：{bj_now().strftime('%Y-%m-%d %H:%M')} BJT
本次批次：{slot}

【信息探索与研究方法论（必须严格遵守）】
{research_method[:40000]}

{recent_block}
【主题映射】
{json.dumps(topic_titles, ensure_ascii=False)}

【初筛结果】
{json.dumps(filtered, ensure_ascii=False)[:80000]}

【已通过证据门槛的深度候选与 AI 引导检索研究笔记】
（每个候选包含 research_notes / evidence_count / evidence_domains 字段：基于 seed URL、DDGS 搜索结果和可抓取正文生成，含已确认事实/推断/来源分层）
{json.dumps(researched, ensure_ascii=False)[:300000]}

请输出 JSON：
{{
  "investigation_reports": [
    {{
      "topic": "ai-tools|side-hustle|overseas|life-signal",
      "title": "调查报告标题",
      "summary": "核心发现摘要，100字内",
      "content_md": "完整调查报告 Markdown 正文",
      "sources": [{{"name": "来源名称", "url": "https://原始链接"}}]
    }}
  ]
}}

【严禁创造新 topic slug】只能使用 ai-tools / side-hustle / overseas / life-signal 之一。

分类决策规则（按优先级）：
1. side-hustle：有明确副业路径，普通人能在一周内验证
2. ai-tools：主角是 AI 工具/能力，今天就能试用
3. overseas：有跨语言/跨地区信息差价值
4. life-signal：影响普通人生活/工作决策（兜底）

调查报告结构（新闻调查格式）：
1. **导言（Lede）**：第一段放最重要/最出人意料的发现，直接抓住读者，不要铺垫背景
2. **核心段（Nutgraf）**：第3-5段交代"这件事为什么现在重要/为什么普通读者应该关心"
3. **证据展开**：按重要性和逻辑展开，而非罗列，每个来源标注可信度（高可信/中可信/线索级）
4. **反驳视角**：主动呈现反方证据和不确定性，不回避，不埋在末尾
5. **影响与悬问**：对读者的实际影响判断，以及最值得继续追的未解疑问

硬性要求：
- 产出 1-3 篇，优中择优，不要凑数。
- 只能围绕【已通过证据门槛的深度候选】写调查报告；如果 researched 为空或证据不足，返回空数组，不要根据初筛结果硬写。
- 直接使用 research_notes 里的已确认事实作为核心论据，不要基于训练知识编造来源。
- 来源在正文引用时标注名称和可信度，禁止在文末单独列"参考来源"一节。
- 严格区分已确认事实、高概率推断、待验证线索——不把推断写成结论。
- 客观调查语气，无第一人称"我"的叙述视角。
- 可使用 H2、H3 标题、表格、引用块等完整 Markdown 格式。
- 有实质深度，不是新闻摘要——字数服从内容需要，不要为凑字数堆废话。
- sources 只收录文章正文中实际引用的高/中可信来源，格式 [{{"name": "来源名", "url": "https://..."}}]，2-8 个，url 必须是完整链接，不得用线索级来源。
""",
        max_tokens=64000,
        model=PRO_MODEL,
        thinking_type=PRO_THINKING,
        reasoning_effort=PRO_REASONING_EFFORT,
    )


# ─── 阶段二：公众号文章（个人口吻改写）─────────────────────────────────────

def compose_wechat_articles(
    investigation_reports: list[dict[str, Any]],
    researched: list[dict[str, Any]],
    persona: str,
    writing_method: str,
    slot: str,
) -> dict[str, Any]:
    print("✍️ 阶段二：使用 Pro 生成公众号文章（个人口吻版）...")
    topic_titles = {t.slug: t.title for t in TOPICS}
    return llm_json(
        system=(
            "你就是 Easton Hua，网名老花。"
            "30多岁，信阳人，IT技术经理，一个人扛着公司的技术方向，日子有点难，压力不小。"
            "你读完了一份关于某个话题的深度调查报告，现在要把你真实的感受和判断写成公众号文章，发给关注你的读者看。"
            "不是把调查报告翻译或压缩成文章，是你读完之后真的被某个点打到了，然后决定写下来这件事。"
            "如果你没有被打到，就不该写这篇。如果被打到了，从那个打到你的地方开始写。"
            "你研究深、实践少，这不是缺点，是真实状态——可以自嘲，但不要假装自己很积极。"
            "你写给大众读者——喜欢你这个人、认同你讲话风格、愿意关注支持你的人。他们不一定要深究信息来源，他们想看到一个真实的、有温度的人认真讲一件打动他的事。"
            "每篇文章结尾必须用固定格式署名：老花 / Easton Hua。"
            "必须输出合法 JSON，不要代码块。"
        ),
        user=f"""
当前时间：{bj_now().strftime('%Y-%m-%d %H:%M')} BJT
本次批次：{slot}

【Easton 人设与写作风格详细说明】
{persona}

【写作方法论】
{writing_method[:40000]}

【主题映射】
{json.dumps(topic_titles, ensure_ascii=False)}

【调查报告原文（改写的素材来源）】
{json.dumps(investigation_reports, ensure_ascii=False)[:150000]}

【补充研究证据（需要细节时参考）】
{json.dumps(researched, ensure_ascii=False)[:80000]}

【写作任务】
共 {len(investigation_reports)} 篇调查报告。每篇报告对应写一篇公众号文章。

先读每份报告，找到那个真正让你（老花）停下来的细节或角度——可能是一个数字、一个反直觉发现、一个和你自己处境直接挂钩的点。从那里开始写。找不到的话宁可不写，不要硬凑一篇空文章。

研究素材只是原料。一篇有感觉的文章用掉的素材通常不超过 30%，其余扔掉。

**不要做的事（写完对照检查）：**
- 开头出现"随着/在当今/本文将"——有就删，从一个具体的时刻或场景切入
- 正文里出现"一、二、三"数字大标题——打散，用口语转场
- 结尾出现"本周/两周内/一个月内"时间轴计划——换成诚实的一句话
- 来源质疑只用括号格式——多样化，可以是"但说真的""——这话来自他们自己的商业报告""我只信一半"
- 同批次多篇文章用同一个开头反应词（"愣住""停下来"轮换用）
- 生活细节强行插入（信阳毛尖/喝酒/英雄联盟/奥乐齐）——贴切的地方才带，不贴切就不带
- 文章里的"我"变成带团队的技术总监或创业者——始终是那个一个人扛技术、日子不容易的 IT 技术经理

**必须做的事：**
- 每篇结尾固定格式署名（见 persona.md 结束语规范）：以上。+互动语+我们下次再聊+老花 / Easton Hua
- 正文引用数据时带个人判断（几成可信、为什么打折）
- "接下来"部分：诚实说，不假装积极
- **文章深度要求（长度是结果，不是目标）**：先把信息源做充分分析，再从多角度论证（含反驳和不确定性），最后把自己的真实处境/生活/感受/判断自然融进去——这个过程做扎实了，有数据、有事实、有分析、有感悟、有分享的文章自然不会短。每个核心观点要展开，不能点到即止；个人角度不是贴标签式的"作为 IT 人我觉得"，是真实生活处境的真实连接

请输出 JSON：
{{
  "wechat_articles": [
    {{
      "topic": "ai-tools|side-hustle|overseas|life-signal",
      "title": "公众号文章标题",
      "summary": "Telegram 摘要，80字内",
      "cover_prompt_en": "英文版封面图提示词，给 Midjourney / DALL-E 使用。详细描述画面构图、色彩、光影、氛围和情绪。必须指定风格（flat vector illustration 或 digital art），构图有明确视觉焦点（左右结构或中心结构），色调与文章基调匹配，氛围有故事感和情绪张力。规格 900x383，2.35:1 横版。【严禁场景描述中出现任何文字/字母/数字/品牌名/logo】",
      "cover_prompt_zh": "中文版封面图提示词，给即梦 / 通义万相使用。与英文版同等细节。900x383，2.35:1 横版构图。【严禁场景描述中出现任何文字/字母/数字/品牌名/logo，无人物面孔】",
      "content_md": "完整公众号正文，含结尾署名。信息分析充分、多角度论证、个人感悟自然融入，深度到位了篇幅自然到位"
    }}
  ]
}}

封面图铁律：场景描述里绝对不能出现任何文字、字母、品牌名（DeepSeek/OpenAI/WhatsApp等）、产品logo——描述物件和氛围，不描述品牌。英文版100字以上，中文版80字以上。
""",
        max_tokens=32000,
        model=PRO_MODEL,
        thinking_type=PRO_THINKING,
        reasoning_effort=PRO_REASONING_EFFORT,
    )


# ─── 邮件发送 ────────────────────────────────────────────────────────────────

_SMTP_PRESETS: dict[str, tuple[str, int, bool]] = {
    "qq.com":      ("smtp.qq.com",          465, True),
    "foxmail.com": ("smtp.qq.com",          465, True),
    "163.com":     ("smtp.163.com",         465, True),
    "126.com":     ("smtp.126.com",         465, True),
    "yeah.net":    ("smtp.yeah.net",        465, True),
    "sina.com":    ("smtp.sina.com",        465, True),
    "outlook.com": ("smtp.office365.com",   587, False),
    "hotmail.com": ("smtp.office365.com",   587, False),
    "live.com":    ("smtp.office365.com",   587, False),
    "gmail.com":   ("smtp.gmail.com",       587, False),
}

def _smtp_settings(email: str) -> tuple[str, int, bool]:
    """返回 (host, port, use_ssl)，优先读环境变量，其次按域名匹配预设。"""
    if EMAIL_SMTP_HOST:
        port = EMAIL_SMTP_PORT or 587
        use_ssl = port == 465
        return EMAIL_SMTP_HOST, port, use_ssl
    domain = email.split("@")[-1].lower()
    return _SMTP_PRESETS.get(domain, ("smtp.office365.com", 587, False))


def email_attachment_name(title: str) -> str:
    safe_title = re.sub(r'[\\/:*?"<>|\r\n]+', "-", title).strip(" .-")
    return f"{safe_title or '公众号文章'}.txt"


def send_email_articles(articles: list[dict[str, str]], slot: str) -> None:
    if not EMAIL_FROM or not EMAIL_PASSWORD:
        print("📭 未配置 EMAIL_FROM / EMAIL_PASSWORD，跳过邮件发送")
        return
    if not articles:
        return

    msg = MIMEMultipart()
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg["Subject"] = f"[公众号] {bj_now().strftime('%Y-%m-%d')} {slot} · {len(articles)} 篇"

    body_parts = [
        f"本批次共 {len(articles)} 篇公众号文章。",
        "正文见附件；每个附件为一篇文章，文件名为文章标题。",
    ]
    for index, article in enumerate(articles, 1):
        body_parts.extend(
            [
                "",
                f"## {index}. {article['title']}",
                "",
                "封面图提示词（英文版，Midjourney / DALL-E）：",
                article["prompt_en"],
                "",
                "封面图提示词（中文版，即梦 / 通义万相）：",
                article["prompt_zh"],
            ]
        )
    msg.attach(MIMEText("\n".join(body_parts), "plain", "utf-8"))

    for article in articles:
        attachment = MIMEBase("text", "plain")
        attachment.set_payload(article["body_txt"].encode("utf-8"))
        encoders.encode_base64(attachment)
        attachment.add_header("Content-Disposition", "attachment", filename=email_attachment_name(article["title"]))
        msg.attach(attachment)

    host, port, use_ssl = _smtp_settings(EMAIL_FROM)
    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port) as server:
                server.login(EMAIL_FROM, EMAIL_PASSWORD)
                server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        else:
            with smtplib.SMTP(host, port) as server:
                server.ehlo()
                server.starttls()
                server.login(EMAIL_FROM, EMAIL_PASSWORD)
                server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"   📧 邮件已发送: {len(articles)} 篇文章，{len(articles)} 个 txt 附件")
    except Exception as exc:
        print(f"   ⚠️ 邮件发送失败: {exc}")


# ─── 文件输出 ─────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9一-鿿]+", "-", text).strip("-").lower()
    if not base:
        base = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return base[:48]


def yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def count_words(text: str) -> int:
    """Count CJK characters + English words for reading-time estimation."""
    cjk   = len(re.findall(r'[一-鿿㐀-䶿豈-﫿]', text))
    latin = len(re.findall(r'\b[A-Za-z]+\b', text))
    return cjk + latin


def write_post(
    category: str,
    filename: str,
    title: str,
    tags: list[str],
    body: str,
    cover: str = "",
    description: str = "",
    sources: list[dict[str, str]] | None = None,
) -> Path:
    path = CONTENT_DIR / category / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    # isoformat() produces "+08:00" (with colon), which is valid ISO-8601 and
    # passes Astro/Zod date parsing without type errors.
    date = bj_now().isoformat(timespec="seconds")
    fm = [
        "---",
        f"title: {yaml_scalar(title)}",
        f"date: {date}",
        f"categories: {json.dumps([category], ensure_ascii=False)}",
        f"tags: {json.dumps(tags, ensure_ascii=False)}",
        f"wordCount: {count_words(body)}",
        "draft: false",
    ]
    if description:
        fm.append(f"description: {yaml_scalar(description)}")
    if cover:
        fm.append(f"cover: {yaml_scalar(cover)}")
    if sources:
        fm.append("sources:")
        for s in sources:
            fm.append(f"  - name: {yaml_scalar(s.get('name', ''))}")
            fm.append(f"    url: {yaml_scalar(s.get('url', ''))}")
    fm.extend(["---", ""])
    path.write_text("\n".join(fm) + "\n" + body.strip() + "\n", encoding="utf-8")
    return path


def render_briefing_md(briefing: dict[str, Any], slot: str) -> str:
    topic_titles = {t.slug: t.title for t in TOPICS}
    lines = [
        f"> {bj_now().strftime('%Y年%m月%d日')} · {slot} · {len(briefing.get('items', []))} 条简讯",
        "",
        briefing.get("summary", ""),
        "",
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in briefing.get("items", []):
        grouped.setdefault(item.get("topic", "life-signal"), []).append(item)
    for slug, items in grouped.items():
        lines.extend([f"## {topic_titles.get(slug, slug)}", ""])
        for item in items:
            url = item.get("url", "")
            title = item.get("title", "无标题")
            source = item.get("source", "未知")
            credibility = item.get("credibility", "")
            lines.extend(
                [
                    f"### {title}",
                    "",
                    f"**来源**：{source} `{credibility}`" + (f"  \n{url}" if url else ""),
                    "",
                    item.get("why_it_matters", ""),
                    "",
                    f"> {item.get('action', '')}",
                    "",
                ]
            )
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def normalize_wechat_body(md: str) -> str:
    """Keep paragraphs and **bold** only for WeChat editor copy/paste."""
    lines: list[str] = []
    for raw in md.splitlines():
        line = raw.strip()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^>\s*", "", line)
        line = re.sub(r"^[-*+]\s+", "", line)
        line = re.sub(r"^\d+[.)]\s+", "", line)
        line = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", line)
        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1（\2）", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        lines.append(line)
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def normalize_cover_prompt(prompt: str, title: str, lang: str = "zh") -> str:
    prompt = re.sub(r"\s+", " ", prompt or "").strip()
    if not prompt:
        if lang == "en":
            prompt = (
                f"Digital art, 2.35:1 landscape format. "
                f"A minimalist scene representing '{title}', flat vector illustration style, "
                "clear focal point, cool blue-purple tones, cinematic lighting, "
                "story-driven atmosphere, no text, no logos, no human faces."
            )
        else:
            prompt = (
                f"扁平矢量插画，2.35:1 横版，以「{title}」为主题，"
                "有明确视觉焦点，冷色调科技感，有故事张力，无文字，无logo，无人物面孔。"
            )
    if lang == "zh":
        suffix_parts = []
        if "900x383" not in prompt and "2.35:1" not in prompt:
            suffix_parts.append("公众号封面图，900x383，2.35:1 横版构图")
        if "无文字" not in prompt:
            suffix_parts.append("无文字")
        if "无logo" not in prompt:
            suffix_parts.append("无logo")
        if "无人物面孔" not in prompt:
            suffix_parts.append("无人物面孔")
        if suffix_parts:
            prompt = f"{prompt}。{', '.join(suffix_parts)}"
    return prompt


def save_website_outputs(
    briefing: dict[str, Any],
    investigation_reports: list[dict[str, Any]],
    slot: str,
) -> list[Path]:
    print("💾 写入网站内容（简讯 + 调查报告）...")
    paths: list[Path] = []
    date_slug = bj_now().strftime("%Y-%m-%d")

    if briefing.get("items"):
        body = render_briefing_md(briefing, slot)
        paths.append(
            write_post(
                "daily-briefing",
                f"briefing-{date_slug}-{slot}.md",
                briefing.get("title") or f"{date_slug} {slot} 简讯",
                ["简讯", slot],
                body,
            )
        )

    valid_topics = {t.slug for t in TOPICS}
    for article in investigation_reports[:3]:
        raw_topic = article.get("topic", "life-signal")
        topic = raw_topic if raw_topic in valid_topics else "life-signal"
        if topic != raw_topic:
            print(f"   ⚠️ 模型返回了未知分类 '{raw_topic}'，已回退到 life-signal")
        title = article.get("title", "深度调查")
        body = article.get("content_md", "")
        summary = article.get("summary", "")
        sources = article.get("sources") or []
        filename_stem = f"investigation-{date_slug}-{slot}-{slugify(title)}"

        cover_path = ""
        try:
            img_prompt = generate_cover_prompt(title, summary)
            cover_path = generate_cover_image(img_prompt, filename_stem)
        except Exception as exc:
            print(f"   ⚠️ 封面图流程异常: {exc}")

        paths.append(
            write_post(
                topic,
                f"{filename_stem}.md",
                title,
                ["深度调查", slot],
                body,
                cover=cover_path,
                description=summary,
                sources=sources,
            )
        )

    for path in paths:
        try:
            display_path = path.relative_to(ROOT)
        except ValueError:
            display_path = path
        print(f"   ✅ {display_path}")
    return paths


def save_wechat_outputs(
    wechat_articles: list[dict[str, Any]],
    slot: str,
) -> list[Path]:
    print("📱 写入公众号文章并发送邮件...")
    paths: list[Path] = []
    email_articles: list[dict[str, str]] = []
    date_slug = bj_now().strftime("%Y-%m-%d")

    for article in wechat_articles[:3]:
        title = article.get("title", "公众号文章")
        prompt_en = normalize_cover_prompt(
            str(article.get("cover_prompt_en") or article.get("gemini_banana_prompt") or ""),
            title, lang="en",
        )
        prompt_zh = normalize_cover_prompt(
            str(article.get("cover_prompt_zh") or article.get("gemini_banana_prompt") or ""),
            title, lang="zh",
        )
        body_md = article.get("content_md", "")
        body_wechat = normalize_wechat_body(body_md)

        path = WECHAT_OUTPUT_DIR / f"{date_slug}-{slot}-{slugify(title)}.md"
        content = (
            "标题\n"
            f"{title}\n\n"
            "封面图提示词（英文版，Midjourney / DALL-E）\n"
            f"{prompt_en}\n\n"
            "封面图提示词（中文版，即梦 / 通义万相）\n"
            f"{prompt_zh}\n\n"
            "正文内容\n"
            f"{body_wechat}\n"
        )
        path.write_text(content, encoding="utf-8")
        paths.append(path)

        email_articles.append(
            {
                "title": title,
                "prompt_en": prompt_en,
                "prompt_zh": prompt_zh,
                "body_txt": body_wechat,
            }
        )

    for path in paths:
        try:
            display_path = path.relative_to(ROOT)
        except ValueError:
            display_path = path
        print(f"   ✅ {display_path}")

    send_email_articles(email_articles, slot)
    return paths


# ─── Telegram 通知 ────────────────────────────────────────────────────────────

def tg_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_telegram(
    briefing: dict[str, Any],
    investigation_reports: list[dict[str, Any]],
    wechat_articles: list[dict[str, Any]],
    slot: str,
) -> None:
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("📭 未配置 Telegram，跳过通知")
        return
    lines = [
        f"<b>{tg_escape(briefing.get('title', '今日简讯'))}</b>",
        f"{bj_now().strftime('%Y-%m-%d')} {slot}",
        "",
    ]
    for item in briefing.get("items", [])[:10]:
        lines.append(f"• {tg_escape(item.get('title', ''))}｜{tg_escape(item.get('source', ''))}")

    if investigation_reports:
        lines.extend(["", "<b>📋 网站调查报告</b>"])
        for article in investigation_reports[:3]:
            lines.append(f"• {tg_escape(article.get('title', ''))}: {tg_escape(article.get('summary', ''))}")

    if wechat_articles:
        lines.extend(["", "<b>📱 公众号文章（已发邮件）</b>"])
        for article in wechat_articles[:3]:
            lines.append(f"• {tg_escape(article.get('title', ''))}: {tg_escape(article.get('summary', ''))}")

    lines.extend(["", SITE_URL])
    payload: dict[str, Any] = {
        "chat_id": TG_CHAT_ID,
        "text": "\n".join(lines)[:3900],
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    if TG_THREAD_BRIEFING:
        payload["message_thread_id"] = int(TG_THREAD_BRIEFING)
    try:
        resp = requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", json=payload, timeout=20)
        if resp.ok:
            print("📨 Telegram 通知已发送")
        else:
            print(f"   ⚠️ Telegram 失败: {resp.status_code} {resp.text[:160]}")
    except Exception as exc:
        print(f"   ⚠️ Telegram 异常: {exc}")


# ─── 入口 ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Easton Radar source-first intelligence pipeline")
    parser.add_argument("--slot", choices=["auto", "morning", "evening"], default="auto", help="日报批次")
    parser.add_argument("--max-age-hours", type=int, default=36, help="RSS 信息最大年龄")
    parser.add_argument("--no-telegram", action="store_true", help="跳过 Telegram 通知")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_runtime()
    now = bj_now()
    slot = detect_slot(now, args.slot)
    persona = load_text_config("PERSONA_PATH", ROOT / "config" / "persona.md", PERSONA_DEFAULT)
    research_method = load_text_config("RESEARCH_SKILL_PATH", ROOT / "config" / "research_skill.md", RESEARCH_METHOD_DEFAULT)
    writing_method = load_text_config("WRITING_SKILL_PATH", ROOT / "config" / "writing_skill.md", WRITING_METHOD_DEFAULT)

    print("🚀 Easton Radar v4")
    print(
        f"   批次: {slot} | 初筛/简讯: {FLASH_MODEL} | "
        f"调查/公众号: {PRO_MODEL}({PRO_THINKING}/{PRO_REASONING_EFFORT}) | 主题: {len(TOPICS)}"
    )

    # 防重复
    recent_titles = load_recent_titles(days=7)

    # 采集 & 初筛
    collected = collect_sources(args.max_age_hours)
    filtered = initial_filter(collected, persona, recent_titles)

    # 简讯
    briefing_report = compose_briefing(filtered, persona, slot)

    # 深度检索
    candidates = filtered.get("deep_candidates", [])
    researched = research_with_tools(candidates)

    # 阶段一：网站调查报告
    if researched:
        inv_result = compose_investigation_reports(filtered, researched, research_method, slot, recent_titles)
        investigation_reports = inv_result.get("investigation_reports", [])
    else:
        print("📋 没有深度候选通过证据门槛，本批次跳过调查报告和公众号长文")
        investigation_reports = []
    save_website_outputs(briefing_report.get("briefing", {}), investigation_reports, slot)

    # 阶段二：公众号文章（个人口吻）+ 发邮件
    if investigation_reports:
        wechat_result = compose_wechat_articles(investigation_reports, researched, persona, writing_method, slot)
        wechat_articles = wechat_result.get("wechat_articles", [])
        save_wechat_outputs(wechat_articles, slot)
    else:
        wechat_articles = []

    # Telegram 通知
    if not args.no_telegram:
        send_telegram(briefing_report.get("briefing", {}), investigation_reports, wechat_articles, slot)

    print("🏁 完成")


if __name__ == "__main__":
    main()
