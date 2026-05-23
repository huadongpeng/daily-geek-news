import argparse
import concurrent.futures
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
ROOT = Path(__file__).resolve().parent
CONTENT_DIR = ROOT / "content" / "posts"
CACHE_DIR = ROOT / ".cache" / "radar"
WECHAT_OUTPUT_DIR = ROOT / "outputs" / "wechat_articles"


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
        slug="ai-tech",
        title="AI 技术雷达",
        category="ai-tech",
        intent=(
            "AI 最新技术资讯，优先官方公告、论文、工程实践、模型能力变化、"
            "开发者能立刻试用的工具。过滤纯融资、营销口水和重复转述。"
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
        search_seeds=("AI model release", "AI coding agent", "AI paper breakthrough"),
    ),
    Topic(
        slug="income-lab",
        title="赚钱副业实验室",
        category="income-lab",
        intent=(
            "个人赚钱渠道、副业、独立产品、低成本验证机会。优先真实抱怨、"
            "需求外溢、工具替代、平台规则变化和可在一周内验证的方向。"
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
        search_seeds=("side project revenue", "micro saas pain point", "freelancer complaint"),
    ),
    Topic(
        slug="world-signals",
        title="社会热点与生活信号",
        category="world-signals",
        intent=(
            "重大社会热点事件，不限 AI。只保留可能影响生活、职业、收入、"
            "政策环境、平台规则、国际局势或普通人风险决策的信息。"
            "优先纳入中外官方/近官方口径，便于交叉对比和识别叙事差异。"
        ),
        feeds=(
            "https://www.federalreserve.gov/feeds/press_all.xml",
            "https://www.sec.gov/news/pressreleases.rss",
            "https://www.ecb.europa.eu/rss/press.html",
            "http://www.chinadaily.com.cn/rss/china_rss.xml",
            "http://www.chinadaily.com.cn/rss/world_rss.xml",
            "http://www.chinadaily.com.cn/rss/bizchina_rss.xml",
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            "https://feeds.bbci.co.uk/news/business/rss.xml",
            "https://www.theguardian.com/world/rss",
            "https://www.theverge.com/rss/index.xml",
            "https://techcrunch.com/feed/",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
            "https://www.wired.com/feed/rss",
            "https://restofworld.org/feed/latest/",
            "https://www.semafor.com/rss.xml",
        ),
        search_seeds=("global regulation platform workers", "social trend affects jobs", "consumer tech policy"),
    ),
    Topic(
        slug="info-gap",
        title="信息差雷达",
        category="info-gap",
        intent=(
            "跨地区、跨语言、跨平台的信息差。优先海外已验证但中文圈少见的模式、"
            "工具、规则变化、用户需求和可迁移到中国或华语市场的机会。"
            "同时对照中外官方/近官方叙事，寻找同一事件在不同语境下的偏差。"
        ),
        feeds=(
            "https://www.federalreserve.gov/feeds/press_monetary.xml",
            "https://www.ecb.europa.eu/rss/statpress.html",
            "http://www.chinadaily.com.cn/rss/world_rss.xml",
            "http://www.chinadaily.com.cn/rss/bizchina_rss.xml",
            "https://restofworld.org/feed/latest/",
            "https://www.wired.com/feed/rss",
            "https://www.producthunt.com/feed",
            "https://news.ycombinator.com/rss",
            "https://www.reddit.com/r/digitalnomad/top/.rss?t=day",
            "https://www.reddit.com/r/InternetIsBeautiful/top/.rss?t=day",
        ),
        search_seeds=("overseas product trend China gap", "emerging market startup pain", "tool alternative demand"),
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


def detect_slot(now: datetime, explicit: str | None) -> str:
    if explicit and explicit != "auto":
        return explicit
    return "morning" if now.hour < 12 else "evening"


def ensure_runtime() -> None:
    if not DEEPSEEK_API_KEY:
        raise SystemExit("❌ 缺少 DEEPSEEK_API_KEY，无法调用 AI 分析。")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    WECHAT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


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
    for category in ("ai-tech", "income-lab", "world-signals", "info-gap"):
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
      "topic": "ai-tech|income-lab|world-signals|info-gap",
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
      "topic": "主题slug",
      "title": "深度选题标题，16字内",
      "core_question": "这篇文章要回答的问题",
      "seed_urls": ["原始链接1", "原始链接2"],
      "reason": "为什么值得深挖"
    }}
  ]
}}

规则：
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


def research_candidates(candidates: list[dict[str, Any]], method: str) -> list[dict[str, Any]]:
    print("🔎 对深度候选做二次检索和优中择优...")
    researched: list[dict[str, Any]] = []
    for cand in candidates[:4]:
        title = cand.get("title", "")
        question = cand.get("core_question", "")
        queries = [
            f"{title} official announcement source",
            f"{title} analysis evidence",
            f"{question} primary source",
        ]
        evidence: list[dict[str, str]] = []
        for q in queries:
            evidence.extend(web_search(q, max_results=5))
        researched.append({**cand, "research_method": method, "evidence": evidence[:10]})
        print(f"   {title}: {len(evidence[:10])} 条补充证据")
    return researched


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
            "你是一名深度信息探索专家，严格按照【信息探索与研究方法论】的原则工作。"
            "任务：根据已收集的证据，撰写供网站发布的中文深度调查报告。"
            "面向关注 AI、副业、海外市场和信息差的中文读者。"
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

【深度候选与检索证据】
{json.dumps(researched, ensure_ascii=False)[:300000]}

请输出 JSON：
{{
  "investigation_reports": [
    {{
      "topic": "主题slug",
      "title": "调查报告标题",
      "summary": "核心发现摘要，100字内",
      "content_md": "完整调查报告 Markdown 正文"
    }}
  ]
}}

调查报告硬性要求：
- 产出 1-3 篇，优中择优，不要凑数。
- 每篇必须包含：核心发现（有据可查的事实链）、证据来源与可信度分层、多角度分析（含反证和不确定性）、对读者的实际影响判断。
- 来源必须在正文引用时标注来源名称和可信度（高可信 / 中可信 / 线索级）。
- 可使用 H2、H3 标题，表格，引用块等完整 Markdown 格式——这是网站调查文章，格式可以丰富。
- 严格区分已确认事实、高概率推断、待验证线索，不把猜测包装成结论。
- 以客观调查语气写作，不需要个人"我"的叙述视角。
- 所有不确定信息明确标注"线索"或"待验证"。
- 每篇不少于 1500 字，要有实质深度，不是新闻摘要。
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
            "你是 Easton 的公众号代笔作者。"
            "你的任务是把已经写好的调查报告，用 Easton 自己的口吻重新讲一遍，改写成公众号文章。"
            "不是翻译，不是压缩摘要，是 Easton 读完这个研究、自己要跟读者聊这件事的感觉。"
            "Easton 是个 30 多岁的 IT 技术经理，负责公司软件研发，信阳人，"
            "喝信阳毛尖，下班喝小酒，平时逛论坛玩英雄联盟，周末去奥乐齐/河马奥莱或者露营看网络小说。"
            "他研究深、实践少，经常站在要开始动手的门口但没迈进去，这是他可以自嘲的地方。"
            "他写给普通打工人看，不教人成功，只是认真把自己看到的东西讲出来。"
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

【改写任务】
从每篇调查报告中，找到最让 Easton 停下来的那个细节或角度，从那个点开始写公众号文章。
研究素材只是原料——一篇好文章用掉的素材不超过 30%，用不上的就扔掉。

请输出 JSON：
{{
  "wechat_articles": [
    {{
      "topic": "主题slug",
      "title": "公众号文章标题",
      "summary": "Telegram 摘要，80字内",
      "gemini_banana_prompt": "适合 Gemini Banana 生图的公众号封面提示词，中文，900x383，2.35:1，必须无文字、无logo、无人物面孔",
      "content_md": "完整公众号正文"
    }}
  ]
}}

公众号文章硬性要求：
- 每篇调查报告对应一篇公众号文章，共 {len(investigation_reports)} 篇。
- 开头从一个具体细节切入，绝不用"在当今AI快速发展的时代"之类的开场。
- 每篇开头反应词只能用一次，且同批次 {len(investigation_reports)} 篇之间不能重复同一个反应词（"愣住"、"停下来"等要轮换）。
- "站在门口"这个比喻整批次最多用一次，其他篇用不同表达。
- 来源可信度在正文引用时带出来，不在末尾单独开"信息来源"一节。
- 来源质疑的表达方式要多样——不要每次都是括号格式，可以是破折号、"但说真的"、问句等。
- "接下来我打算做什么"：诚实说研究深但实践少，可以自嘲但不自我贬低。有真实尝试的明确标注。绝不写成带时间分段或序号的行动清单。
- 生活细节（信阳毛尖/下班喝酒/英雄联盟/奥乐齐/露营看小说）只在真正贴切的地方自然带入，不强行。
- 涉及工作身份只用"IT技术经理"，不提具体公司名。
- 正文只允许使用 **加粗** 格式，不用表格、代码块、引用块、图片语法。
- 禁止"一、二、三、四、五、六"数字编号大标题。
- 禁止"本周/两周内/一个月内"三段时间轴行动计划。
""",
        max_tokens=32000,
        model=PRO_MODEL,
        thinking_type=PRO_THINKING,
        reasoning_effort=PRO_REASONING_EFFORT,
    )


# ─── 邮件发送 ────────────────────────────────────────────────────────────────

def send_email_article(title: str, prompt: str, body_txt: str) -> None:
    if not EMAIL_FROM or not EMAIL_PASSWORD:
        print("📭 未配置 EMAIL_FROM / EMAIL_PASSWORD，跳过邮件发送")
        return
    msg = MIMEMultipart()
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg["Subject"] = f"[公众号] {title}"

    email_body = f"文章标题：{title}\n\n生图提示词：\n{prompt}"
    msg.attach(MIMEText(email_body, "plain", "utf-8"))

    safe_title = re.sub(r"[^\w一-鿿\-]", "-", title)[:40]
    attachment = MIMEBase("application", "octet-stream")
    attachment.set_payload(body_txt.encode("utf-8"))
    encoders.encode_base64(attachment)
    attachment.add_header("Content-Disposition", f'attachment; filename="{safe_title}.txt"')
    msg.attach(attachment)

    try:
        with smtplib.SMTP("smtp.office365.com", 587) as server:
            server.ehlo()
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"   📧 邮件已发送: {title}")
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


def write_post(
    category: str,
    filename: str,
    title: str,
    tags: list[str],
    body: str,
) -> Path:
    path = CONTENT_DIR / category / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    date = bj_now().strftime("%Y-%m-%dT%H:%M:%S%z")
    fm = [
        "---",
        f"title: {yaml_scalar(title)}",
        f"date: {date}",
        f"categories: {json.dumps([category], ensure_ascii=False)}",
        f"tags: {json.dumps(tags, ensure_ascii=False)}",
        "draft: false",
    ]
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
        grouped.setdefault(item.get("topic", "info-gap"), []).append(item)
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


def normalize_gemini_banana_prompt(prompt: str, title: str) -> str:
    prompt = re.sub(r"\s+", " ", prompt or "").strip()
    if not prompt:
        prompt = f"以「{title}」为主题的数字艺术封面，有明确视觉焦点和故事感。"
    required = "公众号封面图，900x383，2.35:1 横版构图，无文字，无logo，无人物面孔。"
    if "900x383" not in prompt and "2.35:1" not in prompt:
        prompt = f"{required}{prompt}"
    elif "无文字" not in prompt or "无logo" not in prompt:
        prompt = f"{prompt}，无文字，无logo，无人物面孔"
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

    for article in investigation_reports[:3]:
        topic = article.get("topic", "info-gap")
        title = article.get("title", "深度调查")
        body = article.get("content_md", "")
        paths.append(
            write_post(
                topic,
                f"investigation-{date_slug}-{slot}-{slugify(title)}.md",
                title,
                ["深度调查", slot],
                body,
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
    date_slug = bj_now().strftime("%Y-%m-%d")

    for article in wechat_articles[:3]:
        title = article.get("title", "公众号文章")
        raw_prompt = article.get("gemini_banana_prompt") or (
            f"公众号封面图，900x383，2.35:1，主题是「{title}」，无文字，无logo，无人物面孔，"
            "数字艺术风格，有明确视觉焦点。"
        )
        prompt = normalize_gemini_banana_prompt(str(raw_prompt), title)
        body_md = article.get("content_md", "")
        body_wechat = normalize_wechat_body(body_md)

        path = WECHAT_OUTPUT_DIR / f"{date_slug}-{slot}-{slugify(title)}.md"
        content = (
            "标题\n"
            f"{title}\n\n"
            "Gemini Banana 生图提示词（公众号封面图适配）\n"
            f"{prompt}\n\n"
            "正文内容\n"
            f"{body_wechat}\n"
        )
        path.write_text(content, encoding="utf-8")
        paths.append(path)

        send_email_article(title, prompt, body_wechat)

    for path in paths:
        try:
            display_path = path.relative_to(ROOT)
        except ValueError:
            display_path = path
        print(f"   ✅ {display_path}")
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
    researched = research_candidates(candidates, research_method)

    # 阶段一：网站调查报告
    inv_result = compose_investigation_reports(filtered, researched, research_method, slot, recent_titles)
    investigation_reports = inv_result.get("investigation_reports", [])
    save_website_outputs(briefing_report.get("briefing", {}), investigation_reports, slot)

    # 阶段二：公众号文章（个人口吻）+ 发邮件
    wechat_result = compose_wechat_articles(investigation_reports, researched, persona, writing_method, slot)
    wechat_articles = wechat_result.get("wechat_articles", [])
    save_wechat_outputs(wechat_articles, slot)

    # Telegram 通知
    if not args.no_telegram:
        send_telegram(briefing_report.get("briefing", {}), investigation_reports, wechat_articles, slot)

    print("🏁 完成")


if __name__ == "__main__":
    main()
