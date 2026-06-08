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
import struct
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import feedparser
import requests
from ddgs import DDGS


BJT = timezone(timedelta(hours=8))
SITE_URL = os.environ.get("SITE_URL", "https://www.huadongpeng.com").rstrip("/")
FLASH_MODEL = os.environ.get("DEEPSEEK_FLASH_MODEL", os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"))
PRO_MODEL = os.environ.get("DEEPSEEK_PRO_MODEL", "deepseek-v4-pro")
FLASH_THINKING = os.environ.get("DEEPSEEK_FLASH_THINKING", "disabled")
FLASH_REASONING_EFFORT = os.environ.get("DEEPSEEK_FLASH_REASONING_EFFORT", "low")
PRO_THINKING = os.environ.get("DEEPSEEK_PRO_THINKING", os.environ.get("DEEPSEEK_THINKING", "enabled"))
PRO_REASONING_EFFORT = os.environ.get("DEEPSEEK_PRO_REASONING_EFFORT", os.environ.get("DEEPSEEK_REASONING_EFFORT", "max"))
PRO_ARTICLE_MAX_TOKENS = int(os.environ.get("DEEPSEEK_PRO_ARTICLE_MAX_TOKENS", "24000"))
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
TG_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TG_THREAD_BRIEFING = os.environ.get("TG_THREAD_BRIEFING")


def first_env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


TG_THREAD_BY_TOPIC = {
    "daily-briefing": TG_THREAD_BRIEFING,
    "ai-tools": first_env("TG_THREAD_AI_TOOLS", "TG_THREAD_AI", "TG_THREAD_DEV"),
    "side-hustle": first_env("TG_THREAD_SIDE_HUSTLE", "TG_THREAD_ARBITRAGE"),
    "overseas": first_env("TG_THREAD_OVERSEAS", "TG_THREAD_CROSS"),
    "life-signal": first_env("TG_THREAD_LIFE_SIGNAL", "TG_THREAD_MACRO", "TG_THREAD_CHINA"),
}
INDEXNOW_KEY = os.environ.get("INDEXNOW_KEY", "hdop-indexnow-key")
BAIDU_PUSH_TOKEN = os.environ.get("BAIDU_PUSH_TOKEN", "")
ROOT = Path(__file__).resolve().parent
CONTENT_DIR = ROOT / "src" / "content" / "blog"
CACHE_DIR = ROOT / ".cache" / "radar"
WECHAT_OUTPUT_DIR = ROOT / "outputs" / "wechat_articles"
NEW_PUSH_URLS_PATH = CACHE_DIR / "new_push_urls.json"
COVERS_DIR = ROOT / "public" / "images" / "covers"
WECHAT_APP_ID = os.environ.get("WECHAT_APP_ID", "")
WECHAT_APP_SECRET = os.environ.get("WECHAT_APP_SECRET", "")
WECHAT_AUTHOR = os.environ.get("WECHAT_AUTHOR", "老花")
WECHAT_DRAFT_ENABLED = os.environ.get("WECHAT_DRAFT_ENABLED", "true").lower() not in {"0", "false", "no"}
WECHAT_ALLOW_BRIEFING_FALLBACK = os.environ.get("WECHAT_ALLOW_BRIEFING_FALLBACK", "false").lower() not in {"0", "false", "no"}
WECHAT_TITLE_MAX_CHARS = 64
WECHAT_DIGEST_MAX_BYTES = 120
SOURCES_CONFIG_PATH = Path(os.environ.get("SOURCES_CONFIG_PATH", ROOT / "config" / "sources.json"))
SILICONFLOW_API_KEY = os.environ.get("SILICONFLOW_API_KEY")
COVER_IMAGE_MODEL = os.environ.get("COVER_IMAGE_MODEL", "Kwai-Kolors/Kolors")
ALLOW_POLLINATIONS_COVER = os.environ.get("ALLOW_POLLINATIONS_COVER", "true").lower() not in {"0", "false", "no"}
# Reddit IP-blocks datacenter ranges (GitHub Actions) on its public .rss; authenticated OAuth
# (app-only client_credentials) is exempt. Configure a "script" app's id/secret to enable it.
REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "script:easton-radar:4.0 (by /u/easton-radar)")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
MIN_EVIDENCE_ITEMS = 3
MIN_EVIDENCE_DOMAINS = 2
MAX_FULLTEXT_EVIDENCE = 8
MAX_SEARCH_PAGE_FETCHES = 12
MAX_EVIDENCE_TEXT_CHARS = 5000
MIN_COVER_BYTES = 10_000
EXPECTED_COVER_SIZE = (1024, 576)
BAIDU_MAX_PER_PUSH = 10
# Many publishers (Economist, The Hill, NPR, NYT…) 403 a bot UA but serve a browser UA fine.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
BROWSER_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
}
# RSS/Atom providers (esp. Reddit) tolerate a descriptive, identified bot UA but block a
# generic browser UA from datacenter IPs as a scraper signature. Keep feeds on the identified UA;
# only article-page fetching (paywalls) uses BROWSER_HEADERS above.
FEED_HEADERS = {
    "User-Agent": "EastonRadar/4.0 (+https://radar.huadongpeng.com)",
    "Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
}
FORBIDDEN_REPORT_HEADINGS = {
    "导言",
    "核心段",
    "证据展开",
    "反驳视角",
    "影响与悬问",
    "已确认的事实",
    "已确认事实",
    "高概率推断",
    "信息分层结论",
    "证据质量评估",
    "对普通技术经理的现实影响",
    "对 Easton 这类普通技术经理/普通打工人的现实影响",
    "我为什么停下来",
    "我会盯哪 3 个信号",
    "暂时不动的理由",
    "风险评估",
    "风险评估如下",
    "行动建议",
    "行动建议如下",
    "老花我现在怎么做",
    "我现在怎么做",
    "换成我会怎么做",
    "我不是建议你立刻冲",
    "对普通人的启示",
    "这件事给我的思考",
}
FORBIDDEN_TITLE_PATTERNS = (
    "我查了",
    "我查完",
    "我查了一圈",
    "我查了一晚上",
    "我翻了一下午",
    "我翻完",
    "我搜了一圈",
    "水有点深",
    "没那么简单",
    "没那么香",
    "后背一凉",
    "比想象中复杂",
    "让我重新思考",
    "觉得这事儿",
    "发现这事儿",
    "咱们可能想反了",
)
SOURCE_HEALTH_LOCK = threading.Lock()


@dataclass(frozen=True)
class Topic:
    slug: str
    title: str
    category: str
    intent: str
    feeds: tuple[str, ...]
    search_seeds: tuple[str, ...]
    api_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublishedIndex:
    titles: list[str]
    source_urls: set[str]


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


def load_topic_source_overrides(topics: tuple[Topic, ...]) -> tuple[Topic, ...]:
    """Allow RSS feeds/search seeds to be maintained in config/sources.json."""
    if not SOURCES_CONFIG_PATH.exists():
        return topics
    try:
        raw = json.loads(SOURCES_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"   ⚠️ 来源配置读取失败，继续使用内置来源: {exc}")
        return topics
    if not isinstance(raw, dict):
        print("   ⚠️ 来源配置格式错误，继续使用内置来源")
        return topics

    updated: list[Topic] = []
    for topic in topics:
        item = raw.get(topic.slug)
        if not isinstance(item, dict):
            updated.append(topic)
            continue

        feeds = item.get("feeds")
        search_seeds = item.get("search_seeds")
        api_sources = item.get("api_sources")
        new_feeds = tuple(str(v).strip() for v in feeds if str(v).strip()) if isinstance(feeds, list) else topic.feeds
        new_search_seeds = (
            tuple(str(v).strip() for v in search_seeds if str(v).strip())
            if isinstance(search_seeds, list)
            else topic.search_seeds
        )
        new_api_sources = (
            tuple(str(v).strip() for v in api_sources if str(v).strip())
            if isinstance(api_sources, list)
            else topic.api_sources
        )
        updated.append(replace(topic, feeds=new_feeds, search_seeds=new_search_seeds, api_sources=new_api_sources))

    try:
        display_path = SOURCES_CONFIG_PATH.relative_to(ROOT)
    except ValueError:
        display_path = SOURCES_CONFIG_PATH
    print(f"   🧩 已加载来源配置: {display_path}")
    return tuple(updated)


TOPICS = load_topic_source_overrides(TOPICS)


PRIMARY_SOURCE_HOSTS = {
    "openai.com",
    "anthropic.com",
    "deepmind.google",
    "blog.google",
    "github.blog",
    "developers.cloudflare.com",
    "aws.amazon.com",
    "huggingface.co",
    "simonwillison.net",
    "stripe.com",
    "docs.stripe.com",
    "vercel.com",
    "docs.github.com",
}

DEVELOPER_PRACTICE_HOSTS = {
    "news.ycombinator.com",
    "hn.algolia.com",
    "lobste.rs",
    "dev.to",
    "changelog.com",
    "thebootstrappedfounder.com",
    "indiehackers.com",
    "producthunt.com",
    "github.com",
}

CASE_STUDY_HOSTS = {
    "v2ex.com",
    "reddit.com",
    "starterstory.com",
    "nichepursuits.com",
    "sidehustlenation.com",
    "practicalecommerce.com",
}

MACRO_MEDIA_HOSTS = {
    "bbc.co.uk",
    "bbc.com",
    "cnbc.com",
    "bloomberg.com",
    "theguardian.com",
    "axios.com",
    "semafor.com",
    "wired.com",
}


def source_quality(item: dict[str, Any]) -> tuple[int, str]:
    """Return a source-quality score/label used by filtering prompts."""
    url = str(item.get("url") or "")
    host = hostname(url)
    source = str(item.get("source") or "").lower()
    if host in PRIMARY_SOURCE_HOSTS or any(host.endswith(f".{h}") for h in PRIMARY_SOURCE_HOSTS):
        return 5, "一手/官方/文档源"
    if host in DEVELOPER_PRACTICE_HOSTS or any(host.endswith(f".{h}") for h in DEVELOPER_PRACTICE_HOSTS):
        return 4, "开发者实操源"
    if host in CASE_STUDY_HOSTS or any(host.endswith(f".{h}") for h in CASE_STUDY_HOSTS):
        return 3, "真实案例/社区线索"
    if "hacker news" in source:
        return 4, "开发者实操源"
    if "reddit" in source or "v2ex" in source:
        return 3, "真实案例/社区线索"
    if host in MACRO_MEDIA_HOSTS or any(host.endswith(f".{h}") for h in MACRO_MEDIA_HOSTS):
        return 1, "二手媒体/宏观源"
    return 2, "普通来源"


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
读者也包括快毕业/刚毕业的 IT 新人、普通程序员/测试/运维/实施、35 岁前后的大龄程序员、小公司技术负责人、怕失业的人和副业探索者。
他们首先需要事实、依据、分析和判断：发生了什么，为什么发生，和我有什么关系，有什么值得警醒或值得看热闹。能行动的选题再给低成本可验证方案；多数新闻、争议、融资、监管、行业风向和证据不足的选题，不需要行动建议。
不教人成功，只是一个站在门口研究了很久但还没迈进去的人，认真把自己看到的东西写出来。

账号主线：老花首先是程序员，不是泛科技资讯号。核心价值是用程序员视角拆 AI 工具、开发、副业、独立产品、跨境、套利、自动化和普通技术人的搞钱路径。热点、宏观和别人的帖子都可以写，但必须回到开发成本、接单方式、副业路径、工具链、岗位风险、出海机会或信息差套利空间。
"""

RESEARCH_METHOD_DEFAULT = """
信息探索原则：
1. 优先官方公告、原始论文、公司文档、监管文件、当事人原帖；其次主流媒体、行业媒体、开发者讨论。
2. 来源必须分层：高可信 / 中可信 / 线索级，不能混写在一起。
3. 明确区分已确认事实、高概率推断、待验证线索、观点/立场，不把猜测包装成结论。
4. 引用商业公司报告时标注利益动机，对数字打折说明。
5. 不把单个 Reddit/论坛帖子写成确定事实，只当需求线索。
6. 整理结果时：找最重要的 2-3 个有据可查的事实，找最反直觉/最让人停下来的 1-2 个角度。
7. 每个深度选题都要补充：谁最相关、为什么现在看、主要矛盾和警醒点是什么、证据缺口在哪里。只有当普通人确实能低成本验证时，才补充验证路径和停止信号。
"""

WRITING_METHOD_DEFAULT = """
写作原则：
开头必须从一个具体细节切入（时间、价格、页面、报错、聊天句子），绝不用"在当今AI快速发展的时代"。
文章风格是有见识的普通技术人在认真聊一件打动他的事，不是媒体报道，不是知识付费教程。
读者要的不是产品说明书，是买家秀：具体的人在具体处境里留下的攻略、体验、感受和踩坑。产品说明书才论优不优秀，买家秀只论真不真实。
段落必须由写作阶段自然拆短，不依赖发布程序二次截断。一个段落只讲一个意思，普通段落 40-120 个中文字符；需要加重情绪、转场或判断时，可以单句成段。长短句要交替出现，不能连续输出大块长段。
不要追求渊博，不要为了显得全面而堆"行业认为/有研究表明/某某观点"。每段都要问：这是说明书谁都能写，还是只有活过、查过、卡过、犹豫过的我才能写？
面对没有标准答案的问题，不要把 A/B/C 各方观点罗列一遍当全面；要站在 Easton 自己的经历、处境和约束里，给出那个不完整但真实的判断。
反证和不确定性嵌在正文中间出现，不单独开一节。
来源可信度在正文引用时就带出来，不在文章末尾单独开"信息来源与可信度"一节。
标题要短，避免夸张承诺，宁可少写也不要水。
文章内核是闭环：事实、依据、分析、判断、关系和警醒。方案/观察是可选尾巴，不是固定目录；能行动才写方案，不适合行动就写清楚证据缺口、风险、门槛或暂时拆不开。
不要为了凑完整结构强行加入"我会怎么做"。能行动才自然写一两句；不适合行动时，把事情讲透后直接结束。

结构禁令：
- 禁止"一、二、三、四、五、六"数字编号大标题
- 禁止"本周/两周内/一个月内"三段时间轴行动计划
- 禁止工具推荐列满四五个选项，只写自己真正用过或打算用的那一两个
- 禁止引用数据不带个人判断（说明来源动机、说明我信几成）
- 禁止把文章写成全知全能但没有个人经历的产品说明书
- 禁止把"我会怎么做/我现在怎么做/我不是建议你立刻冲"写成固定小标题或固定尾段
"""


def bj_now() -> datetime:
    return datetime.now(BJT)


_BATCH_NOW: datetime | None = None


def set_batch_now(value: datetime) -> None:
    global _BATCH_NOW
    _BATCH_NOW = value.astimezone(BJT)


def batch_now() -> datetime:
    return _BATCH_NOW or bj_now()


def batch_date_slug() -> str:
    return batch_now().strftime("%Y-%m-%d")


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


def batch_datetime(slot: str) -> datetime:
    """Use stable publish times so reruns of the same batch don't change URLs/metadata semantics."""
    now = batch_now()
    hour = 6 if slot == "morning" else 18 if slot == "evening" else now.hour
    return now.replace(hour=hour, minute=0, second=0, microsecond=0)


def improve_markdown_readability(md: str) -> str:
    output: list[str] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph:
            return
        text = " ".join(part.strip() for part in paragraph if part.strip()).strip()
        if text:
            output.append(text)
            output.append("")
        paragraph.clear()

    for raw in clean_unicode_text(md).splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            continue
        if re.match(r"^(#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s*|---+$|!\[)", stripped):
            flush_paragraph()
            output.append(line)
            continue
        paragraph.append(stripped)
    flush_paragraph()
    return re.sub(r"\n{3,}", "\n\n", "\n".join(output)).strip()


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    if data.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 9 < len(data):
            if data[offset] != 0xFF:
                offset += 1
                continue
            marker = data[offset + 1]
            offset += 2
            if marker in {0xD8, 0xD9}:
                continue
            if offset + 2 > len(data):
                return None
            segment_len = int.from_bytes(data[offset:offset + 2], "big")
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                if offset + 7 > len(data):
                    return None
                height = int.from_bytes(data[offset + 3:offset + 5], "big")
                width = int.from_bytes(data[offset + 5:offset + 7], "big")
                return width, height
            offset += segment_len
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return width, height
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        if data[12:16] == b"VP8X" and len(data) >= 30:
            width = int.from_bytes(data[24:27], "little") + 1
            height = int.from_bytes(data[27:30], "little") + 1
            return width, height
        if data[12:16] == b"VP8 " and len(data) >= 30:
            width = int.from_bytes(data[26:28], "little") & 0x3FFF
            height = int.from_bytes(data[28:30], "little") & 0x3FFF
            return width, height
    return None


def validate_cover_response(resp: requests.Response, data: bytes, expected_size: tuple[int, int] | None = EXPECTED_COVER_SIZE) -> bool:
    # Trust the magic bytes, not the content-type header: image CDNs (incl. SiliconFlow)
    # commonly serve real JPEG/PNG/WebP as application/octet-stream.
    content_type = resp.headers.get("content-type", "").lower()
    if len(data) < MIN_COVER_BYTES:
        print(f"   ⚠️ 封面文件过小，疑似错误响应: {len(data)} bytes ({content_type or 'unknown'})")
        return False
    dims = image_dimensions(data)
    if not dims:
        print(f"   ⚠️ 封面下载内容不是有效图片 (content-type={content_type or 'unknown'}, {len(data)} bytes)")
        return False
    if expected_size and (abs(dims[0] - expected_size[0]) > 32 or abs(dims[1] - expected_size[1]) > 32):
        print(f"   ⚠️ 封面尺寸 {dims[0]}x{dims[1]}，期望 {expected_size[0]}x{expected_size[1]}")
    return True


def generate_cover_prompt(title: str, summary: str) -> str:
    """Ask Flash to produce a concise English image-generation prompt for a cover."""
    try:
        result = llm_json(
            system=(
                "You are an editorial art director for a Chinese tech-and-society publication. "
                "Generate one specific, image-generator-ready English prompt for an article cover. "
                "Avoid generic AI/technology cliches, abstract glowing networks, random robots, floating orbs, "
                "screens filled with unreadable text, logos, letters, numbers, watermarks, and human faces. "
                " Output only valid JSON, no markdown."
            ),
            user=(
                f"Article title: {title}\n"
                f"Summary: {summary[:300]}\n\n"
                "Generate an English prompt under 55 words for a 16:9 cover image. "
                "Use a concrete visual metaphor tied to the article, with 1 clear focal object, "
                "editorial illustration or realistic product-photo style, clean composition, natural contrast, "
                "no text, no logos, no human faces. "
                'Output JSON: {"prompt": "..."}'
            ),
            max_tokens=200,
            model=FLASH_MODEL,
            thinking_type="disabled",
            reasoning_effort="low",
        )
        prompt = (result.get("prompt") or "").strip()
        return prompt or f"Editorial cover image for '{title[:40]}', one concrete focal object, clean 16:9 composition, no text, no logos, no human faces"
    except Exception as exc:
        print(f"   ⚠️ 封面提示词生成失败: {exc}")
        return "Editorial tech cover image, one concrete focal object, clean 16:9 composition, natural contrast, no text, no logos, no human faces"


def _ratio_to_image_size(size: tuple[int, int]) -> str:
    width, height = size
    return f"{width}x{height}"


def generate_cover_image(prompt: str, filename_stem: str) -> str:
    """Generate article cover via SiliconFlow (Kolors) first; fall back to Pollinations.ai."""
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
                    "model": COVER_IMAGE_MODEL,
                    "prompt": prompt,
                    "negative_prompt": "text, watermark, logo, words, letters, numbers, blurry, low quality, nsfw",
                    "image_size": "1024x576",
                    "num_inference_steps": 20,
                    "guidance_scale": 7.0,
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
                if not validate_cover_response(img_data, img_data.content):
                    return ""
                output_path.write_bytes(img_data.content)
                print(f"   🎨 封面图已生成 (SiliconFlow:{COVER_IMAGE_MODEL}): {output_path.name}")
                return f"/images/covers/{output_path.name}"
        except Exception as exc:
            if ALLOW_POLLINATIONS_COVER:
                print(f"   ⚠️ SiliconFlow 封面生图失败，降级到 Pollinations: {exc}")
            else:
                print(f"   ⚠️ SiliconFlow 封面生图失败，已按配置跳过封面: {exc}")

    if not ALLOW_POLLINATIONS_COVER:
        if not SILICONFLOW_API_KEY:
            print("   📭 未配置 SILICONFLOW_API_KEY，且 ALLOW_POLLINATIONS_COVER=false，跳过封面")
        return ""

    try:
        encoded = quote(prompt, safe="")
        pol_url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            "?width=1024&height=576&nologo=true"
        )
        img_data = requests.get(pol_url, timeout=120, headers={"User-Agent": "EastonRadar/4.0"})
        img_data.raise_for_status()
        if not validate_cover_response(img_data, img_data.content):
            return ""
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


def ensure_output_dirs() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    WECHAT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    COVERS_DIR.mkdir(parents=True, exist_ok=True)


def ensure_runtime() -> None:
    ensure_output_dirs()
    if not DEEPSEEK_API_KEY:
        raise SystemExit("❌ 缺少 DEEPSEEK_API_KEY，无法调用 AI 分析。")


def source_health_path() -> Path:
    return CACHE_DIR / "source_health.json"


def load_source_health() -> dict[str, Any]:
    path = source_health_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def update_source_health(url: str, ok: bool, error: str = "") -> None:
    with SOURCE_HEALTH_LOCK:
        health = load_source_health()
        item = health.get(url) if isinstance(health.get(url), dict) else {}
        now = bj_now().isoformat(timespec="seconds")
        item["last_checked_at"] = now
        if ok:
            item["last_success_at"] = now
            item["consecutive_failures"] = 0
            item.pop("last_error", None)
        else:
            item["last_failure_at"] = now
            item["last_error"] = error[:240]
            item["consecutive_failures"] = int(item.get("consecutive_failures", 0)) + 1
        health[url] = item
        source_health_path().write_text(json.dumps(health, ensure_ascii=False, indent=2), encoding="utf-8")


def print_source_health_warnings() -> None:
    health = load_source_health()
    stale = [
        (url, item)
        for url, item in health.items()
        if isinstance(item, dict) and int(item.get("consecutive_failures", 0)) >= 3
    ]
    if not stale:
        return
    print(f"   🧯 RSS 长期失败源: {len(stale)} 个")
    for url, item in stale[:8]:
        print(f"      - {url} | 连续失败 {item.get('consecutive_failures')} 次 | {item.get('last_error', '')}")


def strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_entry_time(entry: Any) -> datetime | None:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not parsed:
        return None
    return datetime.fromtimestamp(time.mktime(parsed), tz=timezone.utc).astimezone(BJT)


_reddit_token_cache: dict[str, Any] = {"token": "", "expires_at": 0.0}


def is_reddit_feed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "reddit.com" or host.endswith(".reddit.com")


def reddit_access_token() -> str:
    """App-only (client_credentials) OAuth token, cached until shortly before expiry."""
    if not (REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET):
        return ""
    if _reddit_token_cache["token"] and time.time() < _reddit_token_cache["expires_at"]:
        return str(_reddit_token_cache["token"])
    resp = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": REDDIT_USER_AGENT},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    token = str(data.get("access_token") or "")
    expires_in = float(data.get("expires_in") or 3600)
    _reddit_token_cache["token"] = token
    _reddit_token_cache["expires_at"] = time.time() + max(expires_in - 60, 60)
    return token


def reddit_listing_url(feed_url: str) -> str:
    """Map a public .rss feed URL to the OAuth listing endpoint.

    https://www.reddit.com/r/SaaS/top/.rss?t=day -> https://oauth.reddit.com/r/SaaS/top?t=day
    """
    parsed = urlparse(feed_url)
    path = parsed.path.replace("/.rss", "").replace(".rss", "").rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"https://oauth.reddit.com{path}{query}"


def fetch_reddit_feed(url: str, limit: int, max_age_hours: int) -> list[dict[str, Any]]:
    """Fetch a subreddit listing via authenticated OAuth (works from datacenter IPs)."""
    token = reddit_access_token()
    if not token:
        raise RuntimeError("Reddit OAuth 未配置 (REDDIT_CLIENT_ID/SECRET)")
    api_url = reddit_listing_url(url)
    sep = "&" if "?" in api_url else "?"
    resp = requests.get(
        f"{api_url}{sep}limit={limit * 2}&raw_json=1",
        headers={"User-Agent": REDDIT_USER_AGENT, "Authorization": f"bearer {token}"},
        timeout=20,
    )
    resp.raise_for_status()
    children = (resp.json().get("data") or {}).get("children") or []
    cutoff = bj_now() - timedelta(hours=max_age_hours)
    items: list[dict[str, Any]] = []
    for child in children:
        data = child.get("data") or {}
        if data.get("stickied"):
            continue
        title = strip_tags(str(data.get("title") or ""))
        if not title:
            continue
        created = data.get("created_utc")
        published_at = (
            datetime.fromtimestamp(float(created), tz=timezone.utc).astimezone(BJT) if created else None
        )
        if published_at and published_at < cutoff:
            continue
        permalink = str(data.get("permalink") or "")
        link = f"https://www.reddit.com{permalink}" if permalink else str(data.get("url") or "")
        summary = strip_tags(str(data.get("selftext") or ""))[:600]
        items.append(
            {
                "title": title,
                "url": link,
                "summary": summary,
                "published_at": published_at.isoformat() if published_at else "",
                "source": str(data.get("subreddit_name_prefixed") or "Reddit"),
            }
        )
        if len(items) >= limit:
            break
    return items


def fetch_feed(url: str, limit: int, max_age_hours: int) -> list[dict[str, Any]]:
    if is_reddit_feed(url) and REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET:
        try:
            items = fetch_reddit_feed(url, limit, max_age_hours)
            update_source_health(url, True)
            return items
        except Exception as exc:
            print(f"   ⚠️ Reddit API 失败: {url} | {exc}")
            update_source_health(url, False, str(exc))
            return []
    try:
        resp = requests.get(url, timeout=20, headers=FEED_HEADERS)
        if resp.status_code in {403, 429}:
            resp = requests.get(url, timeout=20, headers=BROWSER_HEADERS)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        if getattr(parsed, "bozo", False):
            update_source_health(url, False, str(getattr(parsed, "bozo_exception", "feed parse error")))
        else:
            update_source_health(url, True)
    except Exception as exc:
        print(f"   ⚠️ RSS 失败: {url} | {exc}")
        update_source_health(url, False, str(exc))
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


def parse_api_item_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).astimezone(BJT)
    except Exception:
        return None


def fetch_api_source(url: str, limit: int, max_age_hours: int) -> list[dict[str, Any]]:
    try:
        resp = requests.get(url, timeout=20, headers=BROWSER_HEADERS)
        resp.raise_for_status()
        data = resp.json()
        update_source_health(url, True)
    except Exception as exc:
        print(f"   ⚠️ API 源失败: {url} | {exc}")
        update_source_health(url, False, str(exc))
        return []

    is_algolia = "hn.algolia.com" in url
    if isinstance(data, dict):
        raw_items = data.get("items") or data.get("hits")
    else:
        raw_items = data
    if not isinstance(raw_items, list):
        return []
    cutoff = bj_now() - timedelta(hours=max_age_hours)
    items: list[dict[str, Any]] = []
    for entry in raw_items[: limit * 2]:
        if not isinstance(entry, dict):
            continue
        title = strip_tags(str(entry.get("title") or entry.get("story_title") or entry.get("title_en") or ""))
        if not title:
            continue
        published_at = parse_api_item_time(
            entry.get("publishedAt") or entry.get("published_at") or
            entry.get("date") or entry.get("created_at")
        )
        if published_at and published_at < cutoff:
            continue
        item_url = str(entry.get("url") or "")
        if not item_url and is_algolia:
            obj_id = str(entry.get("objectID") or "")
            if obj_id:
                item_url = f"https://news.ycombinator.com/item?id={obj_id}"
        summary = strip_tags(str(
            entry.get("summary") or entry.get("description") or
            entry.get("story_text") or entry.get("comment_text") or ""
        ))[:600]
        source = str(entry.get("source") or hostname(item_url) or "API Source")
        category = str(entry.get("category") or "")
        if is_algolia:
            source_label = "Hacker News"
        elif "aihot.virxact.com" in url:
            source_label = f"AI HOT · {source}"
        else:
            source_label = source
        if category:
            source_label = f"{source_label} · {category}"
        items.append(
            {
                "title": title,
                "url": item_url,
                "summary": summary,
                "published_at": published_at.isoformat() if published_at else "",
                "source": source_label,
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
            for api_source in topic.api_sources:
                tasks[pool.submit(fetch_api_source, api_source, 12, max_age_hours)] = topic
        for future in concurrent.futures.as_completed(tasks):
            topic = tasks[future]
            collected[topic.slug].extend(future.result())

    for topic in TOPICS:
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        ranked_items = sorted(
            collected[topic.slug],
            key=lambda item: (
                source_quality(item)[0],
                bool(item.get("summary")),
                item.get("published_at") or "",
            ),
            reverse=True,
        )
        for item in ranked_items:
            key = item.get("url") or item["title"].lower()
            if key in seen:
                continue
            seen.add(key)
            score, label = source_quality(item)
            item["source_quality_score"] = score
            item["source_quality"] = label
            unique.append(item)
        collected[topic.slug] = unique[:30]
        print(f"   {topic.title}: {len(collected[topic.slug])} 条")
    print_source_health_warnings()
    return collected


def llm_json(
    system: str,
    user: str,
    max_tokens: int = 8192,
    model: str | None = None,
    thinking_type: str | None = None,
    reasoning_effort: str | None = None,
    raise_on_length: bool = False,
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
    max_attempts = 3
    downgraded_reasoning = False
    capped_max_tokens = max_tokens
    for attempt in range(max_attempts):
        chosen_model = model or FLASH_MODEL
        chosen_thinking = FLASH_THINKING if thinking_type is None else thinking_type
        chosen_effort = FLASH_REASONING_EFFORT if reasoning_effort is None else reasoning_effort
        if downgraded_reasoning and chosen_effort == "max":
            chosen_effort = "high"
        user_content = user
        if attempt:
            user_content = (
                "上一次请求失败或输出不是可解析 JSON。请只返回一个完整、合法、未截断的 JSON object。"
                "不要代码块，不要解释文字，字符串里的换行必须正确转义。\n\n"
                + user
            )
        payload: dict[str, Any] = {
            "model": chosen_model,
            "max_tokens": capped_max_tokens,
            "response_format": {"type": "json_object"},
            "thinking": {"type": chosen_thinking},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_content}],
        }
        if chosen_thinking == "enabled":
            payload["reasoning_effort"] = chosen_effort
        else:
            payload["temperature"] = 0.2
        try:
            resp = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json=payload,
                timeout=300,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.HTTPError as exc:
            last_error = exc
            status_code = exc.response.status_code if exc.response is not None else None
            response_text = ""
            if exc.response is not None:
                try:
                    response_text = exc.response.text[:1200]
                except Exception:
                    response_text = ""
            print(
                "   ⚠️ DeepSeek HTTP error: "
                f"status={status_code} model={chosen_model} thinking={chosen_thinking} "
                f"effort={chosen_effort} max_tokens={capped_max_tokens} "
                f"prompt_chars={len(system) + len(user_content)} response={response_text}"
            )
            if (
                status_code == 400
                and chosen_thinking == "enabled"
                and chosen_effort == "max"
                and not downgraded_reasoning
                and attempt < max_attempts - 1
            ):
                downgraded_reasoning = True
                print("   ↪️ Pro max 请求被拒，改用 Pro high 重试一次")
                continue
            if status_code == 400 and capped_max_tokens > 16000 and attempt < max_attempts - 1:
                capped_max_tokens = 16000
                print("   ↪️ 请求仍被拒，临时将 max_tokens 降到 16000 后重试")
                continue
            if status_code and status_code >= 500 and attempt < max_attempts - 1:
                wait_s = 5 * (attempt + 1)
                print(f"   ⚠️ DeepSeek HTTP {status_code}，第 {attempt + 1}/{max_attempts} 次失败，{wait_s}s 后重试")
                time.sleep(wait_s)
                continue
            raise
        except (
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ConnectionError,
            requests.exceptions.ReadTimeout,
            requests.exceptions.Timeout,
        ) as exc:
            last_error = exc
            if attempt < max_attempts - 1:
                wait_s = 5 * (attempt + 1)
                print(f"   ⚠️ DeepSeek 请求中断，第 {attempt + 1}/{max_attempts} 次失败，{wait_s}s 后重试: {exc}")
                time.sleep(wait_s)
                continue
            raise ValueError(f"DeepSeek request failed after {max_attempts} attempts: {exc}") from exc
        choice = data["choices"][0]
        finish_reason = choice.get("finish_reason")
        text = choice.get("message", {}).get("content") or ""
        if finish_reason == "length":
            last_error = ValueError("DeepSeek response was truncated because finish_reason=length")
            if raise_on_length:
                raise last_error
            print(f"   ⚠️ DeepSeek JSON 第 {attempt + 1}/{max_attempts} 次被截断，准备重试")
            continue
        if not text.strip():
            last_error = ValueError("DeepSeek returned empty content")
            print(f"   ⚠️ DeepSeek JSON 第 {attempt + 1}/{max_attempts} 次返回空内容，准备重试")
            continue
        try:
            return parse_json_object(text)
        except Exception as exc:
            last_error = exc
            debug_path = CACHE_DIR / f"bad-json-{bj_now().strftime('%Y%m%d-%H%M%S')}-try{attempt + 1}.txt"
            debug_path.write_text(text, encoding="utf-8")
            print(
                f"   ⚠️ DeepSeek JSON 第 {attempt + 1}/{max_attempts} 次解析失败，"
                f"长度 {len(text)} 字符，已保存 {debug_path.name}: {exc}"
            )

    raise ValueError(f"LLM JSON parse failed after {max_attempts} attempts: {last_error}") from last_error


def source_digest(collected: dict[str, list[dict[str, Any]]]) -> str:
    blocks: list[str] = []
    topic_map = {t.slug: t for t in TOPICS}
    for slug, items in collected.items():
        topic = topic_map[slug]
        blocks.append(f"\n## {topic.title}\n关注目标：{topic.intent}")
        for i, item in enumerate(items, 1):
            pub = item.get('published_at', '')
            time_str = pub if pub else "⚠️ 无发布日期（时效性未知，谨慎选为deep_candidate）"
            blocks.append(
                f"{i}. {item['title']}\n"
                f"source={item.get('source','')}\n"
                f"source_quality={item.get('source_quality','普通来源')}\n"
                f"url={item.get('url','')}\n"
                f"time={time_str}\n"
                f"summary={item.get('summary','')}"
            )
    return "\n".join(blocks)


def load_recent_published_index(days: int = 7) -> PublishedIndex:
    """扫描 src/content/blog/ 下近 N 天内生成的深度文章标题和来源 URL，用于防重复。"""
    cutoff = bj_now() - timedelta(days=days)
    titles: list[str] = []
    source_urls: set[str] = set()
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
                for url in re.findall(r'^\s*url:\s*"([^"]+)"', text, re.MULTILINE):
                    normalized = normalize_url_for_dedupe(url)
                    if normalized:
                        source_urls.add(normalized)
            except Exception:
                continue
    if titles or source_urls:
        print(
            f"   📚 近 {days} 天已发布深度文章: {len(titles)} 篇，"
            f"来源 URL: {len(source_urls)} 个，用于防重复选题"
        )
    return PublishedIndex(titles=titles, source_urls=source_urls)


def initial_filter(
    collected: dict[str, list[dict[str, Any]]],
    persona: str,
    recent_index: PublishedIndex,
) -> dict[str, Any]:
    print("🧭 初筛符合人设和关注方向的信息...")
    topics = "\n".join(f"- {t.title}: {t.intent}" for t in TOPICS)
    recent_block = ""
    if recent_index.titles:
        recent_block = (
            "\n【近7天已发布深度文章（选 deep_candidates 时不要简单重复；如果有实质新信息，可作为延续/纠偏/更新判断继续写）】\n"
            + "\n".join(f"- {t}" for t in recent_index.titles)
        )
    if recent_index.source_urls:
        recent_block += (
            "\n【近7天已使用过的深度来源 URL（相同来源或同一事件换标题时跳过；除非这次有新事实、新证据或新判断）】\n"
            + "\n".join(f"- {u}" for u in sorted(recent_index.source_urls)[:80])
        )
    return llm_json(
        system=(
            "你是 Easton 的个人情报编辑。任务是从源头信息中筛出真正值得进入日报的内容。"
            "你必须输出合法 JSON，不要 Markdown。"
        ),
        user=f"""
当前时间：{batch_now().strftime('%Y-%m-%d %H:%M')} BJT

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
      "action": "今天能核查/尝试/观察的一个动作，60字内；不适合行动时写清楚看什么证据"
    }}
  ],
  "deep_candidates": [
    {{
      "topic": "ai-tools|side-hustle|overseas|life-signal",
      "title": "深度选题标题，16字内",
      "core_question": "这篇文章要回答的问题",
      "value_lane": "技术搞钱|工具账本|案例拆解|跨境套利|职场现金流|热点观察",
      "developer_angle": "程序员/IT人可以从哪里拆技术、成本、工具链、路径或风险",
      "seed_urls": ["原始链接1", "原始链接2"],
      "reason": "为什么值得深挖"
    }}
  ]
}}

账号定位与选题优先级（优先级高于分类规则）：
1. 第一优先：程序员可直接下场的技术/副业/搞钱选题。包括工具站、AI 编程、自动化、爬虫、SEO、跨境收款、联盟营销、开源项目变现、API 成本、云服务成本、独立开发、套利链路。
2. 第二优先：程序员技术视角的一手拆解。优先价格页、文档、开源仓库、官方公告、API、部署成本、使用限制、真实工作流、替代方案。
3. 第三优先：别人的真实案例深挖。V2EX/Reddit/HN/GitHub/独立开发者帖子可以用，但要能拆为什么成、为什么败、我能不能复制。
4. 第四优先：热点借题发挥。OpenAI、微软、腾讯、政策、监管、大厂新闻都可以写，但必须回到开发成本、接单方式、副业路径、工具链、岗位风险、出海机会或信息差套利空间。
5. 最低优先：感悟、趋势、理想、宏观判断。只能进简讯或兜底，除非有硬证据能落回普通程序员的现金流、工具链或风险决策。

源头质量规则（源头不行，后面全废）：
- deep_candidates 优先选择 source_quality 为“一手/官方/文档源”“开发者实操源”“真实案例/社区线索”的内容。
- “二手媒体/宏观源”只能作为背景或简讯；除非它能引出可核查的一手材料、具体产品、具体价格、具体案例或具体平台规则，否则不要选为 deep_candidate。
- 每个 deep_candidate 至少要有 1 个原始链接或近源链接。只有媒体转述、没有原始材料的候选，不要进深度。
- 论坛/社区帖子可以进深度，但必须是具体案例、具体失败、具体收入/成本/路径/工具，而不是单纯情绪帖。
- 宁可 deep_candidates 少于 3 个，也不要用泛概念、宏观趋势、假大空热点凑数。

分类决策规则（按优先级顺序，选第一个匹配的）：
1. side-hustle：有明确副业路径，普通人或程序员能在一周内开始验证 → 最高优先级
2. ai-tools：主角是一个 AI 工具/能力，开发者/普通用户今天就能试用，且能拆出工具链、成本或工作流影响
3. overseas：以下任一情形均属于此类：
   - 有跨语言/跨地区信息差价值，中文圈读者大概率没看到
   - 出海/跨境机会：国内开发者/创业者能利用的海外平台、市场、政策或套利空间（跨境电商、海外接单、SaaS出海、数字游民收入、海外平台政策变化等）
   - 中国视角观察海外：虎嗅/36氪等中文媒体报道的国际趋势，给中文读者提供外部视角
   注意：overseas 侧重"信息不对称"和"跨越边界的机会"，不是国际新闻的搬运
4. life-signal：不符合以上三项，但会影响普通人的工作/收入/生活决策 → 兜底

【严禁创造新 slug】topic 字段只能是上面 4 个值之一，不得自创任何其他分类名。

其他规则：
- briefing_items 总数 12-20 条，宁缺毋滥。
- deep_candidates 选择 2-4 个，必须能通过进一步检索验证。近7天已发布的主题优先跳过；如果有实质性新进展，可以继续写，但 reason 必须说明它和旧文的关系：延续、纠偏、补证据，还是更新判断。
- 优先官方、论文、原始帖、当事公司博客、权威媒体；少用二手转述。
- deep_candidates 的 reason 必须说明“源头为什么够好”和“程序员视角能拆什么”；只写“值得关注”“释放信号”“行业趋势”不合格。

【副业选题强制配额】
side-hustle 是本账号的核心内容，不是兜底分类。规则如下：
1. 只要 briefing_items 中出现了任何 side-hustle 条目，deep_candidates 里必须至少包含 1 个 side-hustle 类候选。
2. 如果候选池里没有 side-hustle 条目，在 reason 字段里说明原因（"本批次无可用副业线索"），此时才允许 deep_candidates 全为其他分类。
3. 副业类选题的可信度门槛适当放宽——"有真实案例、有可查收入数字、有操作路径"即可进入 deep_candidates，不要求多方官方来源印证。
4. side-hustle 候选优先选：程序员可做的工具站/自动化/接单/SEO/联盟营销/跨境/独立开发，有收入数字的案例、有具体操作路径的工具或平台、有失败/踩坑教训的真实故事、有信息差的海外副业玩法。禁止选：无路径的成功学口号、无数字支撑的"某人赚了很多钱"、纯工具介绍（那属于 ai-tools）。

【ai-tools 深度候选配额上限】
单批次 deep_candidates 中 ai-tools 类候选最多 1 个（除非当天有重大模型/平台发布且具有真实的普通人可用影响）。严禁用 AI 工具/模型的发布公告凑满 deep_candidates。
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


def normalize_url_for_dedupe(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower().removeprefix('www.')}{path}"


def web_search(query: str, max_results: int = 6) -> list[dict[str, str]]:
    cache = search_cache_key(query)
    if cache.exists() and time.time() - cache.stat().st_mtime < 60 * 60 * 12:
        return json.loads(cache.read_text(encoding="utf-8"))
    results: list[dict[str, str]] = []
    if TAVILY_API_KEY:
        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": TAVILY_API_KEY,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                    "include_answer": False,
                    "include_raw_content": False,
                },
                timeout=20,
            )
            resp.raise_for_status()
            results = [
                {"title": r.get("title", ""), "url": r.get("url", ""), "body": r.get("content", "")}
                for r in resp.json().get("results", [])
            ]
        except Exception as exc:
            print(f"   ⚠️ Tavily 检索失败，降级到 DDGS: {exc}")
    if not results:
        try:
            results = [
                {"title": r.get("title", ""), "url": r.get("href", ""), "body": r.get("body", "")}
                for r in DDGS().text(query, max_results=max_results)
            ]
        except Exception as exc:
            print(f"   ⚠️ 检索失败: {query[:80]} | {exc}")
    cache.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


WEATHER_CODE_LABELS = {
    0: "晴",
    1: "大部晴朗",
    2: "多云",
    3: "阴",
    45: "有雾",
    48: "有雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "较强毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    80: "阵雨",
    81: "较强阵雨",
    82: "强阵雨",
    95: "雷雨",
}


def fetch_shanghai_weather_context() -> str:
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": 31.2304,
                "longitude": 121.4737,
                "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
                "timezone": "Asia/Shanghai",
                "forecast_days": 1,
            },
            timeout=12,
        )
        resp.raise_for_status()
        current = resp.json().get("current") or {}
        temp = current.get("temperature_2m")
        humidity = current.get("relative_humidity_2m")
        rain = current.get("precipitation")
        wind = current.get("wind_speed_10m")
        code = current.get("weather_code")
        label = WEATHER_CODE_LABELS.get(int(code), f"天气代码 {code}") if code is not None else "天气未知"
        parts = [f"上海当前天气：{label}"]
        if temp is not None:
            parts.append(f"{temp}℃")
        if humidity is not None:
            parts.append(f"湿度 {humidity}%")
        if rain is not None:
            parts.append(f"降水 {rain}mm")
        if wind is not None:
            parts.append(f"风速 {wind}km/h")
        return "，".join(parts)
    except Exception as exc:
        print(f"   ⚠️ 上海天气上下文获取失败: {exc}")
        return ""


def fetch_shanghai_hot_context(slot: str) -> list[str]:
    date_text = batch_now().strftime("%Y-%m-%d")
    if slot == "morning":
        queries = [
            f"{date_text} 上海 早间 热点 通勤 地铁",
            f"{date_text} 上海 天气 早上 出行 新闻",
        ]
    else:
        queries = [
            f"{date_text} 上海 晚间 热点 生活",
            f"{date_text} 上海 天气 傍晚 出行 新闻",
        ]
    items: list[str] = []
    seen: set[str] = set()
    for query in queries:
        for hit in web_search(query, max_results=4):
            title = clean_unicode_text(str(hit.get("title") or "")).strip()
            body = clean_unicode_text(str(hit.get("body") or "")).strip()
            url = str(hit.get("url") or "").strip()
            key = normalize_url_for_dedupe(url) or title
            if not title or key in seen:
                continue
            seen.add(key)
            text = title
            if body:
                text += f" — {body[:90]}"
            items.append(text)
            if len(items) >= 5:
                return items
    return items


def build_local_context(slot: str) -> str:
    weather = fetch_shanghai_weather_context()
    hot_items = fetch_shanghai_hot_context(slot)
    lines = [
        "【上海当天轻量上下文（可选素材，不得硬蹭）】",
        "用途：只在能自然增强开头或转场时使用；如果和选题无关，宁可不用。",
        "禁止：不能把天气/热点写成文章主角，不能每篇都用“兄弟们，上海最近……”开头，不能编造自己亲历热点事件。",
    ]
    if weather:
        lines.append(f"- {weather}")
    if hot_items:
        lines.append("- 当天上海/生活/出行检索片段：")
        lines.extend(f"  - {item}" for item in hot_items)
    if len(lines) == 3:
        lines.append("- 本次未获取到可靠本地上下文；请不要编造天气或城市热点。")
    return "\n".join(lines)


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
        resp = requests.get(url, timeout=20, headers=BROWSER_HEADERS)
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


def _evidence_failure_reasons(evidence: list[dict[str, Any]]) -> list[str]:
    substantive = [item for item in evidence if item.get("body_type") == "page_text" and len(str(item.get("body") or "")) >= 500]
    domains = {d for d in _evidence_domains(evidence) if d}
    reasons: list[str] = []
    if len(evidence) < MIN_EVIDENCE_ITEMS:
        reasons.append(f"证据条数 {len(evidence)}/{MIN_EVIDENCE_ITEMS}")
    if len(domains) < MIN_EVIDENCE_DOMAINS:
        reasons.append(f"独立域名 {len(domains)}/{MIN_EVIDENCE_DOMAINS}")
    if not substantive:
        reasons.append("缺少可抓取正文")
    return reasons


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


def _plan_missing_evidence(candidate: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """Ask PRO to audit current evidence and request targeted follow-up searches before writing."""
    result = llm_json(
        system=(
            "你是一名懂技术、懂商业风险的审稿型研究编辑。"
            "你的任务不是写文章，而是在正文生成前检查证据够不够、基础概念会不会被懂行人挑刺，"
            "并输出下一轮必须补充检索的查询。必须输出合法 JSON，不要代码块。"
        ),
        user=(
            f"当前日期：{batch_now().strftime('%Y-%m-%d')}\n"
            f"新闻线索：{candidate.get('title', '')}\n"
            f"选题分类：{candidate.get('topic', 'unknown')}\n"
            f"核心问题：{candidate.get('core_question', '')}\n"
            f"价值线：{candidate.get('value_lane', '')}\n"
            f"程序员拆解角度：{candidate.get('developer_angle', '')}\n"
            f"原始来源：{', '.join(candidate.get('seed_urls', [])[:3])}\n\n"
            f"【第一轮已收集证据（共 {len(evidence)} 条）】\n"
            f"{json.dumps(evidence, ensure_ascii=False)[:80000]}\n\n"
            "请先判断：如果现在直接写深度文章，最容易在哪些地方翻车？\n"
            "重点检查：事实真伪、来源闭环、基础概念、技术实现、成本估算、平台规则、法律/税务/合规、国内适用性、普通人可复制性。\n\n"
            "输出 JSON：\n"
            "{\n"
            '  "quality_risks": ["最容易被懂行人挑刺的问题"],\n'
            '  "required_evidence": ["成文前必须补的证据类型"],\n'
            '  "followup_queries": ["用于补证的搜索查询，4-8条，尽量具体"],\n'
            '  "must_not_claim": ["当前证据不足，正文禁止写成结论的说法"],\n'
            '  "can_write_if_missing": false\n'
            "}\n\n"
            "要求：\n"
            "- followup_queries 必须能直接交给搜索引擎执行，不要写抽象任务。\n"
            "- 如果某些证据不补就不适合写深度文章，can_write_if_missing=false。\n"
            "- 如果是副业/变现选题，必须优先补真实收入、失败案例、平台规则、启动成本、普通人可复制性。\n"
            "- 如果是技术选题，必须优先补官方文档、API/SDK、GitHub/真实实现、限制条款和反驳视角。\n"
            "- 如果是支付/金融/合规选题，必须优先补权威规则、地区差异、主体差异和完整成本链路。\n"
            "- 不要为了凑数生成泛查询。"
        ),
        max_tokens=3000,
        model=PRO_MODEL,
        thinking_type=PRO_THINKING,
        reasoning_effort="high" if PRO_REASONING_EFFORT == "max" else PRO_REASONING_EFFORT,
    )
    return {
        "quality_risks": [str(v).strip() for v in result.get("quality_risks", []) if str(v).strip()][:8],
        "required_evidence": [str(v).strip() for v in result.get("required_evidence", []) if str(v).strip()][:8],
        "followup_queries": _normalize_queries(result.get("followup_queries"))[:8],
        "must_not_claim": [str(v).strip() for v in result.get("must_not_claim", []) if str(v).strip()][:8],
        "can_write_if_missing": bool(result.get("can_write_if_missing", False)),
    }


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
            f"选题分类：{candidate.get('topic', 'unknown')}\n"
            f"核心问题：{candidate.get('core_question', '')}\n"
            f"价值线：{candidate.get('value_lane', '')}\n"
            f"程序员拆解角度：{candidate.get('developer_angle', '')}\n"
            f"原始来源：{', '.join(candidate.get('seed_urls', [])[:2])}\n"
            f"深挖理由：{candidate.get('reason', '')}\n\n"
            + (
            "这是一个【副业/变现】类选题，查询必须专门验证机会的真实性和可操作性。\n"
            "请生成 7-9 个搜索查询，必须覆盖以下几类：\n"
            "① 真实收入核实：找实际操作者（非官方宣传）的收入数字/MRR/月收入截图或报告\n"
            "② 操作路径验证：找具体教程、step-by-step案例、'how to start'类一手内容\n"
            "③ 启动门槛：时间/资金/技能要求，'time to first dollar'，最低可行尝试\n"
            "④ 失败案例：谁做了这件事但失败了，失败原因是什么（'failed', 'not worth it', 'stopped'）\n"
            "⑤ 平台/政策风险：平台是否封号/限流，收款是否有障碍，规则是否稳定\n"
            "⑥ 中国市场适用性：国内能做吗，用什么平台，人民币收款怎么解决\n"
            "⑦ 竞争程度：现在还有机会吗，市场是否饱和，新入者的成功率\n"
            '输出 JSON：{"queries": ["query1", "query2", ...]}'
            if candidate.get("topic") == "side-hustle"
            else
            "请生成 6-8 个最有价值的搜索查询，用于核实事实、寻找一手来源、交叉验证。\n"
            "必须覆盖以下几类（按照选题类型取舍）：\n"
            "① 核实核心事实：验证最关键的数字/声明是否属实\n"
            "② 一手来源溯源：找到官方公告/论文/原始报告\n"
            "③ 程序员实操材料：价格页、API/SDK 文档、GitHub 仓库、部署教程、真实工作流、限制条款\n"
            "④ 竞品/同类横向对比：谁还在做这件事？有哪些替代方案？先发者/领先者是谁？（产品/公司类选题必须包含）\n"
            "⑤ 反驳视角检索：有没有人说这个结论是错的/夸大的/有条件的？\n"
            "⑥ 中国市场/中文视角：国内同类产品、政策环境、用户反馈、人民币收款/访问/部署限制\n"
            '输出 JSON：{"queries": ["query1", "query2", ...]}'
            )
        ),
        max_tokens=800,
        model=FLASH_MODEL,
        thinking_type=FLASH_THINKING,
        reasoning_effort=FLASH_REASONING_EFFORT,
    )
    return _normalize_queries(result.get("queries"))


def _analyze_evidence_full(
    candidate: dict[str, Any],
    evidence: list[dict[str, Any]],
    evidence_plan: dict[str, Any] | None = None,
) -> str:
    """Use PRO to synthesize search evidence into structured research notes."""
    result = llm_json(
        system=(
            "你是一名深度信息探索专家。根据已收集的检索证据，对新闻线索做深度分析。\n"
            "严格区分已确认事实、高概率推断、待验证线索，标注每条信息的来源和可信度。\n"
            "只能使用输入证据，不得使用训练记忆补充事实。证据不足时必须明确写'证据不足，不能确认'。\n"
            "必须输出合法 JSON，不要代码块。"
        ),
        user=(
            f"当前日期：{batch_now().strftime('%Y-%m-%d')}\n"
            f"新闻线索：{candidate.get('title', '')}\n"
            f"核心问题：{candidate.get('core_question', '')}\n\n"
            f"价值线：{candidate.get('value_lane', '')}\n"
            f"程序员拆解角度：{candidate.get('developer_angle', '')}\n\n"
            f"【检索证据（共 {len(evidence)} 条）】\n"
            f"{json.dumps(evidence, ensure_ascii=False)[:120000]}\n\n"
            f"【成文前证据缺口审查】\n"
            f"{json.dumps(evidence_plan or {}, ensure_ascii=False)[:20000]}\n\n"
            "请根据以上证据输出结构化研究笔记。\n"
            '输出 JSON：{"research_notes": "完整研究笔记（中文）"}\n\n'
            "研究笔记必须包含以下几块：\n"
            "【事件时效性】列出证据中各核心事件/数据的发布或发生日期。"
            f"若任何核心事件发生在距今超过 60 天（即早于 {(batch_now() - __import__('datetime').timedelta(days=60)).strftime('%Y-%m-%d')}），"
            "必须在此节开头加注：⚠️ 核心事件已超60天，文章须注明时效或重新评估是否适合写成当期报道。\n"
            "【已确认事实】只写输入证据中有多来源印证的事实，标注来源名称和可信级别（高可信/中可信）；没有就写'暂无足够证据'\n"
            "【高概率推断】单来源或间接证据支持，标注来源\n"
            "【待验证线索】无法核实的说法，标注来源\n"
            "【证据缺口处理】逐条回应【成文前证据缺口审查】中的 required_evidence 和 must_not_claim：哪些已经被补证支持，哪些仍然缺证据，正文必须如何降级表达或跳过。\n"
            "【竞品/同类横向对比】这件事/产品/现象，同类还有谁在做？领先者是谁？差距在哪里？"
            "如果线索声称'唯一''首创''行业第一'，必须主动核查：证据支持吗？还是营销话术？"
            "如果是产品类选题（工具/平台/功能），必须对比国内外主要竞品的功能深度、开放程度、用户规模、生态成熟度。"
            "没有对比证据就写'检索未发现竞品对比数据，以下为已知信息'，不得跳过此节。\n"
            "【最有价值的角度】最反直觉或最让普通打工人停下来的 1-2 个点\n"
            "【程序员视角的可拆价值】必须回答：这件事能从开发成本、工具链、API/文档、部署、获客、收款、自动化、开源、岗位风险或副业路径中的哪一项切入？如果没有，就写'缺少程序员视角，不适合写主线深度文章'。\n"
            "【基础概念风险/懂行人挑刺】必须列出这篇文章最容易被专业读者挑刺的基础概念问题，并给出写作避坑方式。"
            "技术/AI Agent/自动化类要区分确定性工程和 AI 能力：证书日期、HTTP 状态码、DNS/WHOIS 字段、接口返回值等应由代码/协议/SDK 处理，AI 只适合摘要、解释、报告、告警文案、归因。"
            "支付/稳定币/跨境收款类要区分链上费、平台提现费、点差、汇率、出入金、账户风控、税务凭证和合规路径；必须区分雇员工资、承包商付款、B2B 服务费、个人转账、国内主体和海外主体。"
            "SEO/工具站类要区分收录、曝光、点击和转化，不得用一周自然搜索点击直接判定关键词价值。"
            "如果没有证据支撑具体数字、技术栈判断、成本比例或合规结论，必须写'证据不足/只能作为假设'。\n"
            "【读者相关性】分别说明快毕业/刚毕业 IT 人、普通程序员/测试/运维/实施、35 岁前后大龄程序员、小公司技术负责人、副业探索者中，谁最相关，为什么\n"
            "【主要关系和警醒点】说明这件事和普通 IT 人/副业探索者/信息差读者有什么关系，最该警醒的误读、门槛、风险或利益动机是什么\n"
            "【可选低成本验证】只有普通人确实能试时，才给 1-3 个 0-2 小时或 0-200 元以内的第一步；如果不适合试，就写'不适合行动建议'并说明原因\n"
            "【主要风险与证据缺口】列出最可能亏在哪里、哪些关键事实还缺证据；只有涉及尝试、购买、投入或副业验证时才写停止信号\n"
            "【后续判断依据】列出 1-3 个未来会改变判断的具体证据；如果没有，就写清楚目前只能停在分析/吃瓜/警醒，不要硬凑观察指标\n"
            "【来源分层】高可信/中可信/线索级 各列出具体来源名称\n"
            + (
            "\n【副业五要素验证（side-hustle 专属，必须逐项回答）】\n"
            "① 市场真实性：证据里有没有非官方的真实收入数字？多少人做了？收入范围是多少？如果只有'有人赚了X万'但没具体来源，标注'未经核实的数字'。\n"
            "② 可复制性：普通人（非行业专家、非有大量粉丝基础）能否复制？需要哪些前置条件？证据中有无'普通人从零开始'的案例？\n"
            "③ 启动门槛：最低启动成本（时间/金钱/技能）？第一步具体是什么？到第一笔收入大概需要多长时间？\n"
            "④ 风险与天花板：平台依赖风险、封号/限流风险、市场饱和度、收入天花板大概在哪里？\n"
            "⑤ 中国市场适用性：国内是否可行？需要哪些平台/工具？人民币收款如何解决？有没有政策合规问题？如果证据只有英文来源，明确标注'中国适用性未经验证'。\n"
            "每项回答结尾标注依据来源和可信级别。没有证据的项直接写'证据不足'，不得编造。"
            if candidate.get("topic") == "side-hustle"
            else ""
            )
        ),
        max_tokens=8000,
        model=PRO_MODEL,
        thinking_type=PRO_THINKING,
        reasoning_effort=PRO_REASONING_EFFORT,
        raise_on_length=True,
    )
    return result.get("research_notes", "")


def _compact_evidence_for_notes(evidence: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in evidence[:limit]:
        compact.append(
            {
                "source_type": item.get("source_type", ""),
                "title": str(item.get("title") or "")[:160],
                "url": item.get("url", ""),
                "domain": item.get("domain") or hostname(str(item.get("url") or "")),
                "query": str(item.get("query") or "")[:120],
                "body": str(item.get("body") or "")[:900],
                "body_type": item.get("body_type", ""),
            }
        )
    return compact


def _analyze_evidence_compact(
    candidate: dict[str, Any],
    evidence: list[dict[str, Any]],
    evidence_plan: dict[str, Any] | None = None,
) -> str:
    """Fallback only when full research-note JSON overflows or repeatedly fails parsing."""
    compact_evidence = _compact_evidence_for_notes(evidence)
    result = llm_json(
        system=(
            "你是审稿型研究编辑。上一次完整研究笔记因为输出过长或 JSON 解析失败，"
            "现在改为输出短研究卡片。只使用输入证据，不得补充训练知识。必须输出合法 JSON。"
        ),
        user=(
            f"当前日期：{batch_now().strftime('%Y-%m-%d')}\n"
            f"新闻线索：{candidate.get('title', '')}\n"
            f"核心问题：{candidate.get('core_question', '')}\n"
            f"价值线：{candidate.get('value_lane', '')}\n"
            f"程序员拆解角度：{candidate.get('developer_angle', '')}\n\n"
            f"【压缩证据（共 {len(compact_evidence)} 条）】\n"
            f"{json.dumps(compact_evidence, ensure_ascii=False)[:26000]}\n\n"
            f"【成文前证据缺口审查】\n"
            f"{json.dumps(evidence_plan or {}, ensure_ascii=False)[:8000]}\n\n"
            "输出 JSON：\n"
            "{\n"
            '  "research_notes": "短研究卡片，必须包含：【事件时效性】【已确认事实】最多5条；'
            '【高概率推断】最多4条；【待验证线索】最多4条；【证据缺口处理】逐条回应 must_not_claim；'
            '【基础概念风险/懂行人挑刺】最多5条；【程序员视角的可拆价值】1-3条；'
            '【主要风险与写作约束】最多5条；【来源分层】列出高可信/中可信/线索级来源。'
            '所有条目都要短句，不要展开成长文。"\n'
            "}\n"
        ),
        max_tokens=3500,
        model=PRO_MODEL,
        thinking_type=PRO_THINKING,
        reasoning_effort="high" if PRO_REASONING_EFFORT == "max" else PRO_REASONING_EFFORT,
    )
    return result.get("research_notes", "")


def _should_fallback_compact_notes(exc: Exception) -> bool:
    text = str(exc)
    return (
        "finish_reason=length" in text
        or "response was truncated" in text
        or "JSON parse failed after" in text
        or "Unterminated string" in text
        or "Expecting" in text
    )


def _analyze_evidence(
    candidate: dict[str, Any],
    evidence: list[dict[str, Any]],
    evidence_plan: dict[str, Any] | None = None,
) -> str:
    try:
        return _analyze_evidence_full(candidate, evidence, evidence_plan)
    except Exception as exc:
        if not _should_fallback_compact_notes(exc):
            raise
        print(f"      ⚠️ 完整研究笔记生成失败，降级为短研究卡片: {exc}")
        return _analyze_evidence_compact(candidate, evidence, evidence_plan)


def _research_candidate(cand: dict[str, Any]) -> dict[str, Any] | None:
    """Research one deep candidate; returns enriched dict or None if skipped."""
    title = cand.get("title", "")
    print(f"   📌 {title[:50]}")
    queries = _generate_search_queries(cand)
    print(f"      📝 第一轮生成 {len(queries)} 个检索查询")
    if not queries:
        print("      ⚠️ 未生成有效查询，跳过该候选")
        return None
    evidence = _collect_evidence(cand, queries)
    print(f"      🧪 Pro 质检第一轮证据并提出补证需求")
    evidence_plan = _plan_missing_evidence(cand, evidence)
    followup_queries = [
        query for query in evidence_plan.get("followup_queries", [])
        if query not in queries
    ]
    if followup_queries:
        print(f"      🧭 追加 {len(followup_queries)} 个补证查询")
        extra_evidence = _collect_evidence({**cand, "seed_urls": []}, followup_queries)
        evidence = _dedupe_evidence(evidence + extra_evidence)
    else:
        print("      🧭 Pro 未要求追加查询")
    domains = {d for d in _evidence_domains(evidence) if d}
    page_count = len([item for item in evidence if item.get("body_type") == "page_text"])
    print(f"      📚 补证后证据 {len(evidence)} 条，正文 {page_count} 条，独立域名 {len(domains)} 个")
    if not _has_minimum_evidence(evidence):
        reasons = "；".join(_evidence_failure_reasons(evidence))
        print(
            "      ⚠️ 证据不足，跳过该候选 "
            f"（{reasons or '未达到门槛'}；需要≥{MIN_EVIDENCE_ITEMS}条证据、"
            f"≥{MIN_EVIDENCE_DOMAINS}个域名、至少1条正文）"
        )
        return None
    notes = _analyze_evidence(cand, evidence, evidence_plan)
    if not notes.strip():
        print("      ⚠️ 研究笔记为空，跳过该候选")
        return None
    print(f"   ✅ 研究完成，笔记 {len(notes)} 字")
    return {
        **cand,
        "research_method": "ai-guided-search",
        "evidence_count": len(evidence),
        "evidence_domains": sorted(domains),
        "evidence_plan": evidence_plan,
        "research_notes": notes,
    }


def assign_candidate_ids(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    assigned: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        item = dict(candidate)
        item["candidate_id"] = str(item.get("candidate_id") or f"cand-{index}")
        assigned.append(item)
    return assigned


def research_with_tools(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Research deep candidates in parallel: FLASH generates queries → DDGS executes → PRO synthesizes."""
    print("🔎 AI 主导深度检索（Flash生成查询 → DDGS执行 → Pro分析，候选并行）...")
    target = candidates[:4]
    if not target:
        return []
    results: list[tuple[int, dict[str, Any]]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(target)) as pool:
        futures = {pool.submit(_research_candidate, cand): index for index, cand in enumerate(target)}
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            try:
                result = future.result()
                if result is not None:
                    result["_candidate_order"] = index
                    results.append((index, result))
            except Exception as exc:
                print(f"   ⚠️ 候选研究异常: {exc}")
    return [result for _, result in sorted(results, key=lambda item: item[0])]


def filter_recent_source_duplicates(
    candidates: list[dict[str, Any]],
    recent_index: PublishedIndex,
) -> list[dict[str, Any]]:
    if not recent_index.source_urls:
        return candidates
    kept: list[dict[str, Any]] = []
    for cand in candidates:
        seed_urls = [normalize_url_for_dedupe(url) for url in cand.get("seed_urls", []) if isinstance(url, str)]
        duplicate_urls = [url for url in seed_urls if url and url in recent_index.source_urls]
        if duplicate_urls:
            print(
                f"   ⏭️ 跳过近期重复来源: {cand.get('title', '')[:50]} "
                f"({duplicate_urls[0]})"
            )
            continue
        kept.append(cand)
    return kept


def compose_briefing(filtered: dict[str, Any], persona: str, slot: str) -> dict[str, Any]:
    print("📰 使用 Flash 生成简讯日报...")
    topic_titles = {t.slug: t.title for t in TOPICS}
    return llm_json(
        system=(
            "你是 Easton 的个人情报快编。你会把初筛信息整理成可发布到网站的中文简讯。"
            "必须输出合法 JSON，不要代码块。"
        ),
        user=f"""
当前时间：{batch_now().strftime('%Y-%m-%d %H:%M')} BJT
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
        "action": "低成本动作/核查点/观察证据"
      }}
    ]
  }}
}}

简讯要求：
- items 从初筛 briefing_items 中优中择优，保留 10-18 条。
- 只写和人设相关、能指导关注/行动的信息；不要把来源不明的信息写成事实。
- why_it_matters 用人话说明与我有什么关系，优先落到开发成本、工具链、副业路径、岗位风险、跨境机会或信息差。
- action 不一定是行动建议。能试的写低成本动作；不能试的写核查点、证据缺口或观察什么。不要每条都写"去注册/去部署/去关注"。
- why_it_matters 和 action 都要短，像给朋友发消息，不要写成新闻稿或报告段落。
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
    writing_method: str,
    slot: str,
    recent_index: PublishedIndex | None = None,
) -> dict[str, Any]:
    print("📋 阶段一：使用 Pro max 生成深度调查文章（网站版）...")
    topic_titles = {t.slug: t.title for t in TOPICS}
    recent_block = ""
    if recent_index and recent_index.titles:
        recent_block = (
            "\n【近7天已发布深度文章（主题高度重合的直接跳过，不要输出）】\n"
            + "\n".join(f"- {t}" for t in recent_index.titles)
            + "\n"
        )
    if recent_index and recent_index.source_urls:
        recent_block += (
            "\n【近7天已使用过的深度来源 URL（相同来源或同一事件换标题时直接跳过，不要输出）】\n"
            + "\n".join(f"- {u}" for u in sorted(recent_index.source_urls)[:80])
            + "\n"
        )
    local_context = build_local_context(slot)
    return llm_json(
        system=(
            "你是一名专业中文深度作者，负责撰写供网站和公众号复用的老花式信息追踪文章。"
            "你的读者包括 Easton 本人，也包括快毕业/刚毕业的 IT 新人、普通程序员/测试/运维/实施、35 岁前后的大龄程序员、小公司技术负责人、副业探索者，以及关心信息差的普通读者。"
            "他们想看到来源清晰、不确定性明确标注、论据可查的内容，也想看到一个真实的人如何怀疑、查证、拆条件、算成本、判断这事和自己有什么关系。"
            "多数读者不是来听建议的，而是想知道发生了什么、为什么发生、有哪些主要关系和警醒点，也想喜闻乐见地看懂一些有意思的事。"
            "写作标准是：事实第一、观点有据、不确定性明确标注，但外形必须像老花把一次真实的信息追踪过程讲给同路人听。"
            "文章不是替老花下结论，而是把老花查一件事、怀疑一件事、拆一件事、判断一件事的过程讲出来。"
            "严格按照【信息探索与研究方法论】的证据标准工作。"
            "必须输出合法 JSON，不要代码块。"
        ),
        user=f"""
当前时间：{batch_now().strftime('%Y-%m-%d %H:%M')} BJT
本次批次：{slot}

【当前写作现场约束（优先级高于风格化表达）】
- 如果不知道 Easton 看到某条消息时的真实地点，不要编造具体生活场景；优先从线索本身切入：标题、数字、截图文字、产品页、价格、评论或公告措辞。
- 不要机械使用"昨天""前几天""上周"。只有材料明确发生时间或当前批次能支撑时才使用；不确定时写"最新刷到""这两天看到""整理今天线索时看到"。
- 工作日白天 Easton 通常在公司上班，不能写成下午在奥乐齐/河马奥莱排队、露营、喝酒或长时间闲逛。
- 可用但不能滥用的合理生活场景：早晚通勤、上海地铁二号线长距离单程接近两小时、等车换乘、午休短暂刷手机、下班骑小电驴回家、晚饭后散步、做饭或洗碗时想起线索。
- 同一批文章不要都以生活场景开头；如果没有真实必要，直接从"一个反直觉数字/一句原帖标题/一个产品页面"开始。

【账号主线约束（优先级最高）】
- 老花首先是程序员，不是泛科技资讯号、宏观趋势号或职场情绪号。
- 核心价值是用程序员视角拆 AI 工具、开发、副业、独立产品、跨境、套利、自动化和普通技术人的搞钱路径。
- 每篇深度文章都必须能回答：如果去掉"老花是程序员"这个身份，这篇文章还成立吗？如果仍然成立，说明太泛，应该跳过或重写。
- 优先写技术搞钱、工具账本、案例拆解、跨境套利、职场现金流。热点观察只能作为配菜，不能成为主线。
- 宏观趋势、政策、行业新闻只有在能落到开发成本、接单方式、副业路径、工具链、岗位风险、出海机会或信息差套利空间时，才允许写成深度文章。
- 如果 research_notes 的【程序员视角的可拆价值】写的是"缺少程序员视角，不适合写主线深度文章"，必须跳过，不要输出文章。

{local_context}

【信息探索与研究方法论（必须严格遵守）】
{research_method[:40000]}

【老花文章可读性约束（吸收风格规则；严谨调查内核，真实追踪过程外形）】
{writing_method[:24000]}

{recent_block}
【主题映射】
{json.dumps(topic_titles, ensure_ascii=False)}

【初筛上下文（只用于理解本批次信息，不得作为成文证据）】
{json.dumps({"briefing_items": filtered.get("briefing_items", [])[:12]}, ensure_ascii=False)[:20000]}

【已通过证据门槛的深度候选与 AI 引导检索研究笔记】
（每个候选包含 research_notes / evidence_plan / evidence_count / evidence_domains 字段：基于 seed URL、第一轮搜索、Pro 证据缺口审查、追加补证搜索和可抓取正文生成，含已确认事实/推断/来源分层）
{json.dumps(researched, ensure_ascii=False)[:300000]}

请输出 JSON：
{{
  "investigation_reports": [
    {{
      "candidate_id": "必须原样复制已研究候选里的 candidate_id",
      "topic": "ai-tools|side-hustle|overseas|life-signal",
      "title": "网站文章标题",
      "summary": "核心发现摘要，100字内",
      "content_md": "完整网站文章 Markdown 正文",
      "sources": [{{"name": "来源名称", "url": "https://原始链接"}}]
    }}
  ]
}}

【严禁创造新 topic slug】只能使用 ai-tools / side-hustle / overseas / life-signal 之一。

分类决策规则（按优先级）：
1. side-hustle：有明确副业路径，普通人能在一周内验证
2. ai-tools：主角是 AI 工具/能力，今天就能试用
3. overseas：以下任一情形均属于此类：①有跨语言/跨地区信息差，中文圈读者大概率没看到；②出海/跨境机会：跨境电商、海外接单、SaaS出海、数字游民收入、海外平台政策；③中文媒体（虎嗅/36氪）报道的国际趋势，对中文读者有信息差价值。**严格排除：国内产品（微信/腾讯/飞书等）、国内政策、国内市场分析，即使该产品有海外版本。**
4. life-signal：影响普通人生活/工作决策（兜底）

文章结构（根据对象类型自适应，禁止套用固定模板）：

先判断这个对象是什么类型——事件、产品发布、趋势现象、政策变化、人物动向、数据报告还是争议说法——再决定如何展开。不同类型对象的展开重点不同，不得一律用同一套结构。

标题规则（优先级很高）：
- 标题不设死格式，但必须有具体对象、具体矛盾、具体成本、具体门槛或具体读者关系中的至少一个。
- 标题不要再写成"我查了/我查完/我查了一圈/我查了一晚上/我翻了一下午/我搜了一圈 + 情绪反转"。
- 标题避免这些套话尾巴："水有点深"、"没那么简单"、"没那么香"、"后背一凉"、"比想象中复杂"、"让我重新思考"、"觉得这事儿"、"发现这事儿"、"咱们可能想反了"。
- 标题尽量少用"正在改写""释放信号""趋势来了""时代开始了""对 IT 人意味着什么"这类泛概念表达；如果用了，正文必须有硬证据和具体路径承接。
- 标题里的主角应该是线索本身、关键数字、隐藏成本、门槛变化、普通人关系，而不是老花查资料的动作。
- 优先写具体矛盾：谁得到了什么能力、代价藏在哪里、普通人容易误判什么、哪条门槛真正卡人。
- 可以有第一人称，但必须承载具体判断；不能把"我查了"当真人感。
- 生成标题前先想 5 个不同方向：关键数字型、隐藏代价型、门槛反差型、普通人关系型、对象直指型。最后只选最具体、最少套话的一条。

阅读原则：
- 开头不要用宏大背景开场（"在当今AI快速发展的时代……"这类一律禁止）。入口必须选【老花文章可读性约束】里的某一种：具体细节/数字/报错切入、日常情绪铺垫（3-4句后转入正题）、直接点名读者（"兄弟们，不知道你们刷到了没"）、随手一查发现（做事→闪念→搜→发现）、读者/朋友触发型。每种都合法，但不能编造不合理场景，情绪铺垫不能超过4句。同一批文章不要都用同一种入口。
- 每段必须短。普通段落 40-120 个中文字符为主，尽量不要超过 150 个中文字符；这是写作要求，不是后处理要求。你必须在生成时按语义自然分段，一个段落只讲一个意思，禁止一段塞满多个事实、多个转折、多个判断。
- 长短句要交替。重要判断、情绪反应、转场可以单独成段；信息密度高的段落后面，必须接一个短句或短段落让读者喘口气。
- 段落之间必须有递进：先让读者看见一个具体细节，再写我为什么起疑或被打到，然后写我顺着哪里查，查到什么地方情绪变了，最后再收束成判断。不要一上来就完整总结。
- 情绪要有层次，但不能空喊。可以有困惑、兴奋、怀疑、破防、冷静下来、算账、收住这些变化；每一次情绪都要被一个具体事实触发。
- 文章要像真人在讲一件刚追完的事：允许短句单独成段，允许一句话转场，允许承认"这里我还没完全想明白"。不要写成平铺直叙的大段说明。
- 文章必须呈现一次真实的信息追踪过程，不是直接给结论。要让读者看见老花如何起疑、如何查源头、如何拆隐藏条件、如何算成本和风险、如何判断这事和咱们有什么关系。
- 文章必须是买家秀，不是产品说明书。读者要看的是 Easton 这个具体的人如何理解、卡住、取舍和判断，不是全知全能地复述资料。
- 不要为了显得渊博而把掌握的材料全塞进去。研究素材只取真正服务文章主线的部分；能不用就不用。
- 面对没有标准答案的问题，不要中立罗列 A/B/C 各方观点当全面。可以理解对立面，但最后要站在 Easton 自己的经历、现实约束和风险偏好里，给出不完整但真实的判断。
- 先把读者最该知道的核心矛盾讲出来，再自然展开证据；不要把证据按目录机械排队。
- 每个 H2 标题必须像文章小标题，不要叫"导言"、"核心段"、"证据展开"、"反驳视角"、"影响与悬问"、"信息分层结论"、"证据质量评估"。
- 可以使用少量 H2/H3，但不要过度 Markdown 化；如果只是两个短点，用自然段讲，不要列表。
- 来源可信度要嵌在正文里，例如"这是官方公告，可信度高，但它没有披露价格"。不要在正文末尾单独开"信息来源与可信度"。
- 反证、不确定性、商业动机和利益偏向必须出现，但要随着论证出现，不要集中堆成模板章节。
- 文章内核要有事实、依据、分析和判断；外形要像一个真实的人边查边讲。不能写成"先结论、再证据、最后建议"。
- 对机会类内容可以拆成一种判断：垃圾局、脏机会、老花可试、兄弟可冲、先拆不开。重点是为什么这么判断、哪里值得警醒；不要直接写"风险评估如下"或"行动建议如下"。
- 文章外形绝不能固定模板。允许顺着思路发散：从一个细节写到行业旧账，再跳回普通人的处境；允许吃瓜、分析、判断、探索并存。天马行空可以，事实边界不能乱。
- 正文主体可以自然使用"我""老花我""咱""咱们""我感觉""我觉得""咱就是说""我就说呢""我真 tama""也是牛掰呀""so tama what"等口语，但不要机械堆词。它们只在判断、破防、转场、号召处出现。
- 不要写"对普通技术经理的现实影响"、"对于多数像 Easton 这样的普通技术经理来说"这种不明觉厉的话。这里要换成更像账号本人会说的话：咱们这些快毕业/刚毕业的 IT 打工人、35 岁门槛前后的程序员、大龄程序员、被裁过或怕失业的人、一个人扛技术方向的小公司 IT 人。
- 如果需要谈读者关系，可以自然写这事和咱们这些 IT 打工人、35 岁门槛前后的程序员、小公司 IT 人有什么关系；不要为了显得完整硬开"启示"或"建议"小节。如果文章更适合吃瓜或事实拆解，就把瓜和逻辑讲好。
- 个人判断里可以使用"我"和"咱们"，但不要自我煽情。要把事实拉回现实处境：负债逾期过、时间少、本金少、试错空间小、怕踩坑、怕失业、怕被新工具甩开、想找一点能验证的方向。负债经历只作为判断力来源，不连续卖惨。
- 行动建议降级。只有选题天然适合低成本验证时，才给真实可行的小方案，说明适合谁、第一步、成本边界、主要风险、停止信号。多数新闻、争议、融资、监管、行业风向、政策变化、证据不足的线索，不写行动步骤也完全可以。
- "怎么做"不是必选栏目，也不是好文章的标准。先把事情分析好、讲好、逻辑讲清、情绪讲自然；如果到这里已经够了，就直接收住，不要为了完整感硬加操作建议。
- 不要把个人动作写成 H2/H3 小标题，例如"老花我现在怎么做""我不是建议你立刻冲""换成我会怎么做"。真有必要写，就并进自然段里，像聊天时顺手补一句。
- 正文最后必须追加一个简短账号介绍和署名，格式不要像硬广告。可以参考但不必逐字照抄："我是老花，一个跌过坑、还在小公司打工维生的十年老程序员。这里不教成功，只记录我追过的信号、踩过的坑，和我拆出来的一点路。"
- 结尾不要写"综上所述"。

内容素材池（根据选题自由取用，不要求全部出现，更不能按这个顺序当目录）：
- 这件事到底是什么，容易误解在哪里。
- 哪些事实已经确认，依据来自哪里。
- 哪些是高概率推断，为什么只能写成推断。
- 哪些只是待验证线索，不能当事实。
- 来源有没有商业动机、立场偏向或缺失数据。
- 这事老花我能不能做；如果不能，是机会不行，还是我没本钱、没时间、良心不舒服、风险吃不下。
- 哪些兄弟可以试，前提是什么；哪些人别硬冲。
- 如果适合行动，最多给 1-3 个低成本动作，并说明适合谁、今天怎么做、最多投入多少时间/钱、什么情况应该停止。
- 如果不适合行动，写清楚目前还缺哪块证据、卡在什么条件上、主要警醒是什么，然后自然结束。不要写"观察 3 个信号"这种 AI 味表达。
- 如果这里没有新的信息量，允许一句话带过，不要硬凑一节。

硬性要求：
- 产出 1-3 篇，优中择优，不要凑数。每篇必须带 candidate_id，且 candidate_id 必须来自【已通过证据门槛的深度候选】。
- 如果本批候选都只剩泛热点、宏观判断、媒体转述或缺少程序员可拆价值，返回空数组；不要为了更新频率硬写。
- 只能围绕【已通过证据门槛的深度候选】写调查报告；如果 researched 为空或证据不足，返回空数组，不要根据初筛结果硬写。
- 证据缺口不等于必须跳过。只要候选有明确程序员可拆价值，且核心事实不是完全站不住，就可以写成"我查到这里，哪些能确认，哪些只能当线索，哪些结论现在不能下"的谨慎调查文章。不要因为不能证明赚钱、不能证明可复制、不能证明平台规则稳定，就直接空输出；这些恰恰可以成为文章的核心判断。
- 【初筛上下文】只能帮助理解当天信息流，不得据此补写未研究候选，不得把 briefing item 改造成深度文章。
- 【事件时效性强制检查】写每篇文章前，先读 research_notes 里的【事件时效性】节。若该节标注了"⚠️ 核心事件已超60天"，则：(a) 如果文章的核心价值是"这件事现在才发生/值得现在追"，直接跳过，不要输出这篇；(b) 如果核心价值是"这件事虽然发生在过去，但今天依然有新的判断/新的数据/新的影响需要说"，则在文章开头明确交代时间背景（例如"这是 N 个月前的事，但我最近重新追了一遍，因为……"），不能把旧事包装成当期新闻。
- 直接使用 research_notes 里的已确认事实作为核心论据，不要基于训练知识编造来源。
- 写正文前必须先读 evidence_plan 和 research_notes 的【证据缺口处理】。evidence_plan.required_evidence 是成文前模型主动要求补的材料；evidence_plan.must_not_claim 是当前证据不足时禁止写成结论的说法。除非 research_notes 明确说明补证已经支持，否则正文必须降级表达或跳过该结论。
- 每篇正文必须自然出现至少一个程序员视角的硬拆解：价格/额度/API/文档/仓库/部署/获客/收款/自动化/技术门槛/岗位现金流/停止信号。不是每项都写，但不能一项都没有。
- 【基础概念审查】写作前必须先根据 research_notes 的【基础概念风险/懂行人挑刺】做内部自检；正文不能把基础概念写错来换取爽感。技术/AI Agent/自动化类必须区分确定性工程和 AI 能力：证书日期、HTTP 状态码、DNS/WHOIS 字段、接口返回值等由代码/协议/SDK 处理，AI 只负责摘要、解释、归因、报告、告警文案。支付/稳定币/跨境收款类必须区分链上费、平台费、点差、汇率、出入金、账户风控、税务凭证和合规路径；必须区分雇员、承包商、B2B、个人转账、国内主体和海外主体。SEO/工具站类必须区分收录、曝光、点击、转化和订阅，不得用一周自然搜索点击直接判定关键词价值。
- 【来源闭环】正文里点名引用的第三方来源（报告、博客、媒体、法规、平台规则、文档）必须出现在 sources 数组中；如果没有 research_notes 里的真实 URL，就不要点名当证据写进正文。sources 不是装饰字段，必须覆盖正文核心证据。
- 【免费/0成本边界】"0 成本""免费""一晚上能搞定""代码量少一半"这类判断必须有来源、公式或明确前提。DALL·E、付费 API、需要账号额度或地区限制的工具，不得写成无条件免费。没有证据时改成"低成本试一小步"或说明主要成本是时间。
- 【口吻禁用】禁止写"输不起""我这种输不起的人""我卡住了""我不敢上头了"这类 AI 模拟口吻。可以写"我试错空间小""我没本钱乱试""我现在不适合冲"，但不要像套出来的自嘲台词。
- 【经验模拟试跑】如果选题属于工具站、副业、开源项目变现、SaaS、AI 工作流或接单外包，正文必须自然写出一段"如果是我，我会怎么低成本跑一遍"的打样：先做什么最小版本、看什么反馈、什么结果继续、什么结果停止。没有亲测就明确写成经验方案，禁止伪装成实操战报。
- 【经验模拟试跑对象绑定】经验试跑必须只围绕当前候选的对象、用户、关键词、技术栈和来源材料展开。禁止把提示词示例或其他文章里的 PDF 转图片、健康助手、简历优化、公众号选题助手等无关项目搬进正文。当前候选是 SSL/域名/WHOIS，就只能围绕 SSL/域名/WHOIS 做最小验证；当前候选是接单，就只能围绕接单需求做最小验证。
- 【工具账本/成本类】如果文章主题是模型价格、API 成本、工具订阅、云服务账单，不要写"我今晚打算去算"或"如果让我来查"；必须直接给一个普通场景的粗算过程和结论，例如日请求量、单次 token、月 tokens、不同模型价格差、隐藏成本。省钱办法必须写接入代价，不要只列名词。
- 【成本估算边界】成本估算必须区分来源材料里的数字和老花自己的假设；自估数字必须写清前提、范围或公式，不能装成已验证结论。工具站、AI Worker、监控、爬虫、批处理类项目不能只算 AI API，还要考虑请求量、并发/重试、队列/cron、存储/日志、部署/域名、人工维护和风控/合规。
- 【AI 编程/工作流类】禁止写"技能平权运动""体力陷阱""如虎添翼"这类大词。重点写清楚：能不能把需求讲清楚、任务拆开、结果验出来、烂代码拦住。AI 像一个很快但需要盯着的初级程序员，不是让人少动脑子的外挂。
- 来源在正文引用时标注名称和可信度，禁止在文末单独列"参考来源"一节。
- 严格区分已确认事实、高概率推断、待验证线索——不把推断写成结论。
- 【竞品/唯一性核验】如果 research_notes 的【竞品/同类横向对比】节列出了同类产品或竞争者，文章不得写成"独家""唯一""首创""国内仅此一家"；必须在正文中交代同类竞品的存在和差异。忽略竞品信息、只渲染单一产品是严重事实错误。
- 【结论必须从证据推导，禁止跳跃】写任何行动建议或结论前，先在心里检查：这个结论能从 research_notes 中的已确认事实直接推出吗？如果研究说"A 现象对 B 群体有 C 影响"，结论只能是"B 群体需要警惕 C"，不能跳跃成"B 群体应该停止做 A"。影响≠应该停止；风险存在≠一定会发生；有问题≠无价值。
- 【研究结论边界强制检查】写完行动建议后自检：这个建议是研究本身支持的，还是我自己加戏？研究的样本、范围、条件是否支持这个结论？如果研究只针对特定人群（如美国应届生），结论不能泛化成"所有人"。
- 【side-hustle 专属写作要求】topic 为 side-hustle 的文章必须在正文中回答以下问题（不用标题罗列，但必须自然融入）：(a) 这条路有没有普通人真实做成功的案例，大概收入范围是多少；(b) 第一步怎么开始，最低时间/金钱成本是多少；(c) 主要风险在哪里，什么情况应该停止；(d) 中国用户能做吗，如果不能直接用，有没有替代方案。四点中有证据的写，没有证据的必须明确说"老花没找到中国用户的实测数据"之类的话，不得跳过或编造。
- 文章主体是客观网站文章语气；个人判断部分可以自然使用第一人称"我"或"咱们"，位置服从文章节奏。
- 可使用 H2、H3 标题、表格、引用块等 Markdown 格式，但只在真正帮助阅读时使用。
- 禁止输出固定模板标题："导言"、"核心段"、"证据展开"、"反驳视角"、"影响与悬问"、"已确认的事实"、"高概率推断"、"对普通技术经理的现实影响"。
- 禁止写"我为什么停下来""我会盯哪 3 个信号""暂时不动的理由""风险评估如下""行动建议如下""对普通人的启示""这件事给我的思考"这类套话。
- 禁止写"老花我现在怎么做""我现在怎么做""换成我会怎么做""我不是建议你立刻冲"这类固定小标题；相关内容只能自然并入正文，且没有新信息量时不要写。
- 禁止把行动建议写成成功学口号；如果给行动建议，必须说明成本、边界和停止条件。不要为了显得有用而硬凑建议。
- 生成后自检一次：这是一份具体人的买家秀，还是一份没有人生经历的产品说明书？如果更像产品说明书，必须重写。
- 生成后自检一次：有没有连续 2 段都像新闻摘要或资料说明？有就改成"我看到什么 -> 我怎么反应 -> 我去查什么 -> 查完怎么判断"。
- 生成后自检一次：有没有超过 150 个中文字符的正文段落？有就按语义重写成 2-3 个自然段，不能只机械断句或按标点硬切。
- 生成后自检一次：开头是否编造了 Easton 的地点、动作、购物、喝酒、露营场景？如果没有证据支撑，必须改成线索本身开头。
- 生成后自检一次：是否把工作日白天写成超市排队、露营、喝酒等不合理场景？如果有，必须重写。
- 生成后自检一次：是否机械使用"昨天""前几天""上周"？如果时间不确定，改成"最新刷到""这两天看到""整理今天线索时看到"。
- 有实质深度，不是新闻摘要——字数服从内容需要，不要为凑字数堆废话。
- sources 只收录文章正文中实际引用的高/中可信来源，格式 [{{"name": "来源名", "url": "https://..."}}]，2-8 个，url 必须是完整链接，不得用线索级来源。url 字段只能使用 research_notes 中实际出现的原始 URL；严禁构造或猜测 URL（包括任何含 /12345、-jun2026 等占位符路径）；找不到真实 URL 的来源直接删掉，不要用假链接补充。
- 文章正文是纯 Markdown 文字，封面图由系统单独生成；禁止在正文任何位置写"图片，说明……"这样的图片占位符文字。
""",
        max_tokens=PRO_ARTICLE_MAX_TOKENS,
        model=PRO_MODEL,
        thinking_type=PRO_THINKING,
        reasoning_effort=PRO_REASONING_EFFORT,
    )


def compose_investigation_reports_per_candidate(
    researched: list[dict[str, Any]],
    research_method: str,
    writing_method: str,
    slot: str,
    recent_index: PublishedIndex | None = None,
) -> dict[str, Any]:
    """Fallback path: generate articles one candidate at a time with full per-candidate evidence."""
    print("📋 批量成文失败，降级为逐候选多次成文...")
    topic_titles = {t.slug: t.title for t in TOPICS}
    recent_titles = recent_index.titles if recent_index else []
    reports: list[dict[str, Any]] = []
    for index, candidate in enumerate(researched[:3], start=1):
        title = str(candidate.get("title") or candidate.get("core_question") or "")[:80]
        print(f"   ✍️ 逐篇生成 {index}/{min(len(researched), 3)}: {title}")
        try:
            result = llm_json(
                system=(
                    "你是一名专业中文深度作者，负责把单个已完成研究的候选写成网站文章。"
                    "只能使用输入里的研究笔记和证据，不得补训练记忆。"
                    "必须输出合法 JSON，不要代码块。"
                ),
                user=f"""
当前时间：{batch_now().strftime('%Y-%m-%d %H:%M')} BJT
本次批次：{slot}

【主题映射】
{json.dumps(topic_titles, ensure_ascii=False)}

【近7天已发布深度文章，主题重复时不要输出】
{json.dumps(recent_titles[:80], ensure_ascii=False)}

【信息探索与研究方法论】
{research_method[:24000]}

【老花文章可读性约束】
{writing_method[:18000]}

【单个深度候选完整研究材料】
{json.dumps(candidate, ensure_ascii=False)[:180000]}

请输出 JSON：
{{
  "investigation_reports": [
    {{
      "candidate_id": "必须原样复制单个深度候选里的 candidate_id",
      "topic": "ai-tools|side-hustle|overseas|life-signal",
      "title": "网站文章标题",
      "summary": "核心发现摘要，100字内",
      "content_md": "完整网站文章 Markdown 正文",
      "sources": [{{"name": "来源名称", "url": "https://原始链接"}}]
    }}
  ]
}}

硬性要求：
- 只围绕这个候选写 0 或 1 篇；证据不足或主题重复就返回空数组。输出文章时必须带 candidate_id，且 candidate_id 必须原样复制单个深度候选里的值。
- 老花首先是程序员，不是泛科技资讯号。文章必须能用程序员视角拆出开发成本、工具链、API/文档、部署、获客、收款、自动化、开源、岗位风险或副业路径中的至少一项；如果 research_notes 显示缺少程序员可拆价值，返回空数组。
- 证据缺口不等于必须跳过。只要核心线索有价值，就可以写成谨慎调查文章：哪些确认了，哪些只是线索，哪些结论现在不能下，为什么普通人别急着冲。只有核心事实站不住、主题重复、没有程序员可拆价值时才返回空数组。
- 直接使用 research_notes 里的已确认事实作为核心论据，不要基于训练知识编造来源。
- 严格区分已确认事实、高概率推断、待验证线索。
- 写正文前必须先读 evidence_plan 和 research_notes 的【证据缺口处理】。evidence_plan.must_not_claim 中仍未被补证支持的说法，正文禁止写成结论。
- 来源可信度嵌入正文，不要在文末单独列参考来源。
- 普通段落 40-120 个中文字符为主，一个段落只讲一个意思；长短句交替，不要靠程序后处理拆段。
- 写作前必须根据 research_notes 的【基础概念风险/懂行人挑刺】做内部自检；正文不能把基础概念写错来换取爽感。技术/AI Agent/自动化类必须区分确定性工程和 AI 能力；支付/稳定币/跨境收款类必须区分链上费、平台费、点差、汇率、出入金、账户风控、税务凭证、雇员/承包商/B2B/个人转账和地区主体；SEO/工具站类必须区分收录、曝光、点击、转化和订阅。
- 正文里点名引用的第三方来源必须出现在 sources 数组中；没有 research_notes 里的真实 URL 就不要点名当证据写进正文。
- "0 成本""免费""一晚上能搞定"等判断必须有来源、公式或明确前提；没有证据时降级。
- 禁止写"输不起""我这种输不起的人""我卡住了""我不敢上头了"这类 AI 模拟口吻。
- 如果选题属于工具站、副业、开源项目变现、SaaS、AI 工作流或接单外包，正文必须自然写出一段经验模拟试跑：先做什么最小版本、看什么反馈、什么结果继续、什么结果停止。没有亲测就明确写成经验方案，禁止伪装成实操战报。
- 经验模拟试跑必须绑定当前候选对象，禁止把提示词示例或其他文章里的 PDF 转图片、健康助手、简历优化、公众号选题助手等无关项目搬进正文。
- 如果选题属于工具账本/成本类，必须直接给一个普通场景的粗算过程和结论，不要写未来打算去算；省钱办法必须写接入代价。
- 成本估算必须区分来源材料里的数字和老花自己的假设；自估数字必须写清前提、范围或公式。工具站、AI Worker、监控、爬虫、批处理类项目不能只算 AI API，还要考虑请求量、并发/重试、队列/cron、存储/日志、部署/域名、人工维护和风控/合规。
- 如果选题属于 AI 编程/工作流类，重点写需求拆解、验收、维护和拦住烂代码，禁止用"技能平权运动""如虎添翼"这类泛化大词收束。
- 标题不设死格式，但必须有具体对象、具体矛盾、具体成本、具体门槛或具体读者关系中的至少一个。
- 标题禁止写成"我查了/我查完/我查了一圈/我查了一晚上/我翻了一下午/我搜了一圈 + 情绪反转"；少用"水有点深"、"没那么简单"、"没那么香"、"后背一凉"、"比想象中复杂"、"发现这事儿"这类尾巴。
- 标题尽量少用"正在改写""释放信号""趋势来了""时代开始了""对 IT 人意味着什么"这类泛概念表达；如果用了，正文必须有硬证据和具体路径承接。
- 标题优先写具体矛盾、关键数字、隐藏成本、门槛变化或普通人关系，不要把查资料动作当标题钩子。
- 不要写固定栏目："我会盯哪 3 个信号"、"行动建议如下"、"老花我现在怎么做"、"我不是建议你立刻冲"。
- 行动建议不是必选。先把发生了什么、为什么发生、和咱们有什么关系、哪里值得警醒讲清楚；只有选题天然适合低成本验证时，才自然并入一两句动作。没有新信息量就不写。
- sources 只收录正文实际引用的高/中可信来源，2-8 个；url 字段只能使用 research_notes 中实际出现的原始 URL，严禁构造或猜测 URL（含任何 -jun2026、/12345 等占位路径）；找不到真实 URL 就删掉该条来源。
- 文章正文是纯 Markdown 文字；禁止在正文任何位置写"图片，说明……"这样的图片占位符文字。
- overseas 分类仅限于有真实跨语言/跨地区信息差价值的选题；国内产品、国内政策、国内市场分析不得归入 overseas。
""",
                max_tokens=min(PRO_ARTICLE_MAX_TOKENS, 18000),
                model=PRO_MODEL,
                thinking_type=PRO_THINKING,
                reasoning_effort="high" if PRO_REASONING_EFFORT == "max" else PRO_REASONING_EFFORT,
            )
        except Exception as exc:
            print(f"   ⚠️ 逐篇生成失败，跳过该候选: {title} - {exc}")
            continue
        item_reports = result.get("investigation_reports") or []
        if item_reports:
            reports.append(item_reports[0])
    return {"investigation_reports": reports}


def filter_reports_to_researched(
    reports: list[dict[str, Any]],
    researched: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    allowed_ids = {str(item.get("candidate_id") or "") for item in researched if item.get("candidate_id")}
    if not allowed_ids:
        return []
    kept: list[dict[str, Any]] = []
    single_candidate_id = next(iter(allowed_ids)) if len(allowed_ids) == 1 else ""
    for report in reports:
        candidate_id = str(report.get("candidate_id") or "")
        if candidate_id in allowed_ids:
            kept.append(report)
            continue
        if not candidate_id and single_candidate_id:
            report["candidate_id"] = single_candidate_id
            kept.append(report)
            continue
        title = str(report.get("title") or "")[:60]
        print(f"   ⚠️ 跳过未绑定已研究候选的文章: {title or '无标题'}")
    return kept


def absolute_site_url(path_or_url: str) -> str:
    value = (path_or_url or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    if not value.startswith("/"):
        value = f"/{value}"
    return f"{SITE_URL}{value}"


# ─── 文件输出 ─────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    text = clean_unicode_text(text)
    # Keep generated URLs portable for sharing: ASCII letters, numbers and dashes only.
    base = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    base = re.sub(r"-{2,}", "-", base)
    if not base:
        base = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:6]
    if len(base) < 12:
        return f"{base}-{digest}" if base else digest
    if len(base) <= 42:
        return base
    return f"{base[:36].strip('-')}-{digest}"


def yaml_scalar(value: str) -> str:
    return json.dumps(clean_unicode_text(value), ensure_ascii=False)


def clean_unicode_text(value: Any) -> str:
    return str(value or "").encode("utf-8", "replace").decode("utf-8")


def clean_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return clean_unicode_text(value)
    if isinstance(value, dict):
        return {clean_unicode_text(key): clean_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_json_value(item) for item in value]
    return value


def truncate_by_bytes(text: str, max_bytes: int) -> str:
    text = clean_unicode_text(text)
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    ellipsis = "..."
    budget = max_bytes - len(ellipsis.encode("utf-8"))
    out: list[str] = []
    total = 0
    for ch in text:
        size = len(ch.encode("utf-8"))
        if total + size > budget:
            break
        out.append(ch)
        total += size
    return "".join(out).rstrip() + ellipsis


def truncate_by_chars(text: str, max_chars: int) -> str:
    text = clean_unicode_text(text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def wechat_safe_title(title: str, summary: str = "") -> str:
    """Keep the WeChat title aligned with the website title unless the API limit forces a cut."""
    raw = re.sub(r"\s+", " ", clean_unicode_text(title).strip())
    if not raw:
        raw = re.sub(r"\s+", " ", clean_unicode_text(summary).strip()) or "老花今天追到的新信号"
    return truncate_by_chars(raw, WECHAT_TITLE_MAX_CHARS)


def wechat_safe_digest(summary: str, content_md: str = "") -> str:
    raw = re.sub(r"\s+", " ", clean_unicode_text(summary).strip())
    if not raw:
        raw = strip_tags(clean_unicode_text(content_md)).strip()
    return truncate_by_bytes(raw, WECHAT_DIGEST_MAX_BYTES)


def optimize_wechat_metadata(
    wechat_articles: list[dict[str, Any]],
    persona: str,
) -> list[dict[str, str]]:
    _ = persona
    # Keep draft titles aligned with site titles. The VPS push script also applies
    # the same 64-character guard, so this only changes titles when the API requires it.
    return [
        {
            "wechat_title": wechat_safe_title(str(article.get("title") or ""), str(article.get("summary") or "")),
            "wechat_digest": wechat_safe_digest(
                str(article.get("summary") or ""),
                str(article.get("content_md") or ""),
            ),
        }
        for article in wechat_articles
    ]


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
    published_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> Path:
    path = CONTENT_DIR / category / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    body = improve_markdown_readability(body)
    # isoformat() produces "+08:00" (with colon), which is valid ISO-8601 and
    # passes Astro/Zod date parsing without type errors.
    publish_time = published_at or bj_now()
    update_time = updated_at or publish_time
    date = publish_time.isoformat(timespec="seconds")
    updated = update_time.isoformat(timespec="seconds")
    fm = [
        "---",
        f"title: {yaml_scalar(title)}",
        f"date: {date}",
        f"updated: {updated}",
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


def save_new_push_urls(urls: list[str]) -> None:
    unique = list(dict.fromkeys(url for url in urls if url.startswith("http")))
    if not unique:
        if NEW_PUSH_URLS_PATH.exists():
            NEW_PUSH_URLS_PATH.unlink()
        return
    NEW_PUSH_URLS_PATH.write_text(json.dumps(unique, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   🧾 已记录待部署后推送 URL: {len(unique)} 条")


def site_url_for_post_path(path: Path) -> str:
    rel = path.relative_to(CONTENT_DIR)
    url_path = "/blog/" + "/".join(rel.with_suffix("").parts) + "/"
    return SITE_URL + url_path


def render_briefing_md(briefing: dict[str, Any], slot: str) -> str:
    topic_titles = {t.slug: t.title for t in TOPICS}
    lines = [
        f"> {batch_now().strftime('%Y年%m月%d日')} · {slot} · {len(briefing.get('items', []))} 条简讯",
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
    for raw in clean_unicode_text(md).splitlines():
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


def inline_markdown_to_wechat_html(text: str) -> str:
    escaped = html.escape(clean_unicode_text(text).strip())
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def markdown_to_wechat_html(md: str) -> str:
    """Convert article Markdown into conservative WeChat draft HTML."""
    blocks: list[str] = []
    list_items: list[str] = []

    def flush_list() -> None:
        nonlocal list_items
        if not list_items:
            return
        blocks.append(
            '<ul style="margin: 0 0 16px 1.2em; padding: 0;">'
            + "".join(f'<li style="margin: 0 0 6px 0;">{item}</li>' for item in list_items)
            + "</ul>"
        )
        list_items = []

    for raw in clean_unicode_text(md).splitlines():
        line = raw.strip()
        if not line:
            flush_list()
            continue
        if line.startswith("!["):
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            flush_list()
            level = len(heading.group(1))
            text = inline_markdown_to_wechat_html(heading.group(2))
            if level <= 2:
                blocks.append(f'<h2 style="font-size: 18px; font-weight: 700; margin: 28px 0 12px;">{text}</h2>')
            else:
                blocks.append(f'<p style="font-weight: 700; margin: 22px 0 10px;">{text}</p>')
            continue
        bullet = re.match(r"^[-*+]\s+(.+)$", line)
        if bullet:
            list_items.append(inline_markdown_to_wechat_html(bullet.group(1)))
            continue
        ordered = re.match(r"^\d+[.)]\s+(.+)$", line)
        if ordered:
            list_items.append(inline_markdown_to_wechat_html(ordered.group(1)))
            continue
        quote = re.match(r"^>\s*(.+)$", line)
        if quote:
            flush_list()
            text = inline_markdown_to_wechat_html(quote.group(1))
            blocks.append(
                '<blockquote style="margin: 18px 0; padding: 10px 14px; '
                f'border-left: 3px solid #d0d7de; color: #57606a;">{text}</blockquote>'
            )
            continue
        flush_list()
        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        blocks.append(f'<p style="margin: 0 0 18px; line-height: 1.9;">{inline_markdown_to_wechat_html(line)}</p>')

    flush_list()
    return "\n".join(blocks)


def local_cover_path(cover: str) -> Path | None:
    cover = (cover or "").strip()
    if not cover or cover.startswith(("http://", "https://")):
        return None
    if cover.startswith("/images/covers/"):
        path = ROOT / "public" / cover.lstrip("/")
        return path if path.exists() else None
    return None


def get_wechat_access_token() -> str:
    resp = requests.get(
        "https://api.weixin.qq.com/cgi-bin/token",
        params={"grant_type": "client_credential", "appid": WECHAT_APP_ID, "secret": WECHAT_APP_SECRET},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"获取微信 access_token 失败: {data}")
    return str(token)


def upload_wechat_cover(access_token: str, cover_path: Path) -> str:
    with cover_path.open("rb") as file_obj:
        resp = requests.post(
            "https://api.weixin.qq.com/cgi-bin/material/add_material",
            params={"access_token": access_token, "type": "image"},
            files={"media": (cover_path.name, file_obj, "image/jpeg")},
            timeout=60,
        )
    resp.raise_for_status()
    data = resp.json()
    media_id = data.get("media_id")
    if not media_id:
        raise RuntimeError(f"上传微信封面素材失败: {data}")
    return str(media_id)


def build_wechat_draft_article(article: dict[str, Any], thumb_media_id: str) -> dict[str, Any]:
    article = clean_json_value(article)
    title = clean_unicode_text(article.get("wechat_title") or article.get("title") or "公众号文章")
    summary = clean_unicode_text(article.get("wechat_digest") or article.get("summary") or "")
    safe_title = truncate_by_chars(title.strip(), WECHAT_TITLE_MAX_CHARS)
    safe_digest = truncate_by_bytes(summary.strip(), WECHAT_DIGEST_MAX_BYTES)
    return {
        "title": safe_title,
        "author": clean_unicode_text(article.get("author") or WECHAT_AUTHOR),
        "digest": safe_digest,
        "content": markdown_to_wechat_html(article.get("content_md") or ""),
        "content_source_url": clean_unicode_text(article.get("site_url") or ""),
        "thumb_media_id": thumb_media_id,
        "show_cover_pic": 1,
        "need_open_comment": 1,
    }


def add_wechat_draft_articles(access_token: str, articles: list[dict[str, Any]]) -> str:
    payload = {
        "articles": articles
    }
    resp = requests.post(
        "https://api.weixin.qq.com/cgi-bin/draft/add",
        params={"access_token": access_token},
        data=json.dumps(clean_json_value(payload), ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    media_id = data.get("media_id")
    if not media_id:
        raise RuntimeError(f"创建微信草稿失败: {data}")
    return str(media_id)


def add_wechat_draft(access_token: str, article: dict[str, Any], thumb_media_id: str) -> str:
    return add_wechat_draft_articles(access_token, [build_wechat_draft_article(article, thumb_media_id)])


def publish_wechat_drafts(wechat_articles: list[dict[str, Any]], slot: str) -> list[dict[str, str]]:
    if not WECHAT_DRAFT_ENABLED:
        print("📭 WECHAT_DRAFT_ENABLED=false，跳过公众号草稿推送")
        return []
    if not WECHAT_APP_ID or not WECHAT_APP_SECRET:
        print("📭 未配置 WECHAT_APP_ID / WECHAT_APP_SECRET，跳过公众号草稿推送")
        return []
    print("📝 推送公众号草稿...")
    results: list[dict[str, str]] = []
    try:
        access_token = get_wechat_access_token()
    except Exception as exc:
        print(f"   ⚠️ 获取微信 access_token 失败，跳过草稿推送: {exc}")
        return results

    draft_articles: list[dict[str, Any]] = []
    grouped_items: list[tuple[str, dict[str, Any]]] = []
    for article in wechat_articles[:8]:
        title = str(article.get("title") or "公众号文章")
        cover_path = local_cover_path(str(article.get("cover") or ""))
        if not cover_path:
            print(f"   ⚠️ 缺少本地封面图，跳过草稿: {title[:40]}")
            continue
        try:
            thumb_media_id = upload_wechat_cover(access_token, cover_path)
            draft_articles.append(build_wechat_draft_article(article, thumb_media_id))
            grouped_items.append((title, article))
        except Exception as exc:
            print(f"   ⚠️ 草稿文章准备失败: {title[:40]} - {exc}")
    if not draft_articles:
        return results
    try:
        draft_media_id = add_wechat_draft_articles(access_token, draft_articles)
        for title, article in grouped_items:
            article["wechat_draft_media_id"] = draft_media_id
            results.append({"title": title, "draft_media_id": draft_media_id})
        print(f"   ✅ 多图文草稿已创建: {len(draft_articles)} 篇 ({draft_media_id})")
    except Exception as exc:
        print(f"   ⚠️ 多图文草稿推送失败: {exc}")
    return results


def write_wechat_archive_record(articles: list[dict[str, Any]], slot: str) -> None:
    if not articles:
        return
    date_slug = batch_date_slug()
    record = {
        "date": date_slug,
        "slot": slot,
        "created_at": bj_now().isoformat(timespec="seconds"),
        "articles": [
            {
                "title": article.get("title", ""),
                "has_cover": bool(article.get("cover")),
                "site_url": article.get("site_url", ""),
            }
            for article in articles
        ],
    }
    path = WECHAT_OUTPUT_DIR / f"{date_slug}-{slot}-archive.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   🗂️ 公众号归档记录: {path.relative_to(ROOT)}")


def personal_article_footer() -> str:
    return (
        "我是老花，一个 30 多岁、还在一线摸爬滚打的小公司 IT 技术经理。"
        "这里不教成功，只记录我追过的信号、踩过的坑，和我暂时想明白的一点判断。\n\n"
        "以上。\n\n"
        "既然看到这里了，觉得有点用的话，点个赞或者转发一下，让更多朋友看到。\n\n"
        "我们下次再聊。\n\n"
        "老花 / Easton Hua"
    )


def ensure_personal_footer(md: str) -> str:
    body = (md or "").strip()
    if "老花 / Easton Hua" in body or "老花/Easton Hua" in body:
        return body
    return f"{body}\n\n{personal_article_footer()}".strip()


def detect_forbidden_report_headings(md: str) -> list[str]:
    found: list[str] = []
    for line in md.splitlines():
        match = re.match(r"^#{2,4}\s+(.+?)\s*$", line.strip())
        if not match:
            continue
        heading = match.group(1).strip().strip("：:")
        if heading in FORBIDDEN_REPORT_HEADINGS:
            found.append(heading)
    return found


def soften_report_template_headings(md: str) -> str:
    """Demote rigid report headings into prose warnings instead of preserving AI-template structure."""
    lines: list[str] = []
    for line in md.splitlines():
        match = re.match(r"^(#{2,4})\s+(.+?)\s*$", line.strip())
        if match:
            heading = match.group(2).strip().strip("：:")
            if heading in FORBIDDEN_REPORT_HEADINGS:
                lines.append(f"**{heading}。**")
                continue
        lines.append(line)
    return "\n".join(lines)


def detect_forbidden_title_patterns(title: str) -> list[str]:
    normalized = re.sub(r"\s+", "", clean_unicode_text(title))
    return [pattern for pattern in FORBIDDEN_TITLE_PATTERNS if pattern in normalized]


def warn_if_action_advice_unbounded(md: str, title: str) -> None:
    text = md or ""
    has_advice = any(word in text for word in ("建议", "可以试", "先试", "先查", "先注册", "先跑", "第一步", "如果你想试"))
    if not has_advice:
        return
    has_cost = any(word in text for word in ("0-2 小时", "2 小时", "200 元", "免费", "成本", "最多投入", "时间"))
    has_stop = any(word in text for word in ("停止信号", "该停", "别继续", "不要继续", "先别投", "停止投入"))
    if not (has_cost and has_stop):
        missing = []
        if not has_cost:
            missing.append("成本边界")
        if not has_stop:
            missing.append("停止信号")
        print(f"   ⚠️ 文章包含行动建议但边界偏弱: {title[:40]} 缺少 {', '.join(missing)}")


_IMAGE_PLACEHOLDER_RE = re.compile(
    r"^(?:图片[，,，]?\s*说明[：:：]?.*|!\[.*?\]\(\)|!\[图片\]\(.*?\))\s*$",
    re.MULTILINE,
)


def _strip_image_placeholders(md: str) -> str:
    """Remove lines the model emits as image placeholders despite prompt prohibition."""
    cleaned = _IMAGE_PLACEHOLDER_RE.sub("", md)
    # Collapse runs of 3+ blank lines down to 2
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def save_website_outputs(
    briefing: dict[str, Any],
    investigation_reports: list[dict[str, Any]],
    slot: str,
) -> list[Path]:
    print("💾 写入网站内容（简讯 + 调查报告）...")
    paths: list[Path] = []
    date_slug = batch_date_slug()
    publish_time = batch_datetime(slot)
    update_time = bj_now()

    briefing_stem = f"briefing-{date_slug}-{slot}"
    briefing_title = briefing.get("title") or f"{date_slug} {slot} 简讯"
    briefing_summary = briefing.get("summary", "")

    # Pre-process articles (cheap, sequential)
    valid_topics = {t.slug for t in TOPICS}
    preprocessed: list[dict[str, Any]] = []
    article_stems: list[str] = []
    for article in investigation_reports[:3]:
        raw_topic = article.get("topic", "life-signal")
        topic = raw_topic if raw_topic in valid_topics else "life-signal"
        if topic != raw_topic:
            print(f"   ⚠️ 模型返回了未知分类 '{raw_topic}'，已回退到 life-signal")
        title = article.get("title", "深度调查")
        body = article.get("content_md", "")
        forbidden_headings = detect_forbidden_report_headings(body)
        if forbidden_headings:
            print(f"   ⚠️ 模型返回固定报告标题，已降级处理: {', '.join(sorted(set(forbidden_headings)))}")
            body = soften_report_template_headings(body)
        body = ensure_personal_footer(body)
        body = improve_markdown_readability(body)
        # Strip image placeholder lines the model sometimes emits despite the prompt prohibition
        body = _strip_image_placeholders(body)
        title_patterns = detect_forbidden_title_patterns(title)
        if title_patterns:
            print(f"   ⚠️ 文章标题撞到套话，建议重生成: {title[:40]} -> {', '.join(title_patterns)}")
        warn_if_action_advice_unbounded(body, title)
        # Validate overseas category — must have a genuine cross-border angle
        if topic == "overseas":
            overseas_signals = ["海外", "跨境", "跨地区", "境外", "信息差", "国际", "全球", "海外版", "出海",
                                "海外市场", "overseas", "cross-border", "global", "international"]
            body_lower = body.lower()
            if not any(s in body or s in body_lower for s in overseas_signals):
                print(f"   ⚠️ 文章归类为 overseas 但正文未见跨境信号，已回退到 ai-tools")
                topic = "ai-tools"
        # Strip fabricated source URLs (patterns: -junYYYY, /12345, placeholder paths)
        import re as _re
        _fake_url_pat = _re.compile(
            r"([-/]\d{4,}(?:[^/\s]*)$|[-]\w{3}\d{4}(?:[^/\s]*)?$)", _re.IGNORECASE
        )
        raw_sources = article.get("sources") or []
        clean_sources = []
        for s in raw_sources:
            url = str(s.get("url") or "")
            if not url.startswith("http"):
                continue
            path_part = url.split("?")[0].split("#")[0]
            last_segment = path_part.rstrip("/").rsplit("/", 1)[-1]
            if _fake_url_pat.search(last_segment):
                print(f"   ⚠️ 移除疑似伪造来源 URL: {url[:80]}")
                continue
            clean_sources.append(s)
        article["sources"] = clean_sources
        article["content_md"] = body
        article["topic"] = topic
        stem = f"investigation-{date_slug}-{slot}-{slugify(title)}"
        article_stems.append(stem)
        preprocessed.append(article)

    # Generate all covers in parallel (Flash prompt + image API)
    def _gen_cover(title: str, summary: str, stem: str) -> tuple[str, str, str]:
        try:
            prompt = generate_cover_prompt(title, summary)
            path = generate_cover_image(prompt, stem)
            return stem, prompt, path
        except Exception as exc:
            print(f"   ⚠️ 封面图流程异常: {exc}")
            return stem, "", ""

    cover_tasks: list[tuple[str, str, str]] = []
    if briefing.get("items"):
        cover_tasks.append((briefing_title, briefing_summary, briefing_stem))
    for article, stem in zip(preprocessed, article_stems):
        cover_tasks.append((article.get("title", "深度调查"), article.get("summary", ""), stem))

    cover_map: dict[str, tuple[str, str]] = {}  # stem -> (prompt, path)
    if cover_tasks:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(cover_tasks)) as pool:
            fmap = {pool.submit(_gen_cover, t, s, stem): stem for t, s, stem in cover_tasks}
            for future in concurrent.futures.as_completed(fmap):
                stem_key, prompt, cpath = future.result()
                cover_map[stem_key] = (prompt, cpath)

    # Write briefing
    briefing_cover = ""
    if briefing.get("items"):
        body = render_briefing_md(briefing, slot)
        _, briefing_cover = cover_map.get(briefing_stem, ("", ""))
        briefing_path = write_post(
            "daily-briefing",
            f"{briefing_stem}.md",
            briefing_title,
            ["简讯", slot],
            body,
            cover=briefing_cover,
            description=briefing_summary,
            published_at=publish_time,
            updated_at=update_time,
        )
        briefing["site_url"] = site_url_for_post_path(briefing_path)
        briefing["cover"] = briefing_cover
        briefing["content_md"] = body
        briefing["summary"] = briefing_summary
        briefing["title"] = briefing_title
        paths.append(briefing_path)

    # Write articles
    for article, stem in zip(preprocessed, article_stems):
        topic = str(article.get("topic", "life-signal"))
        title = article.get("title", "深度调查")
        body = article.get("content_md", "")
        summary = article.get("summary", "")
        sources = article.get("sources") or []
        cover_prompt, cover_path = cover_map.get(stem, ("", ""))
        if not cover_path and briefing_cover:
            print(f"   ⚠️ 文章封面生成失败，复用本批简讯封面: {title[:40]}")
            cover_path = briefing_cover
        article["cover_prompt_en"] = cover_prompt
        article["cover_prompt_zh"] = article.get("cover_prompt_zh") or ""
        article["cover"] = cover_path
        article_path = write_post(
            topic,
            f"{stem}.md",
            title,
            ["深度调查", slot],
            body,
            cover=cover_path,
            description=summary,
            sources=sources,
            published_at=publish_time,
            updated_at=update_time,
        )
        article["site_url"] = site_url_for_post_path(article_path)
        paths.append(article_path)

    for path in paths:
        try:
            display_path = path.relative_to(ROOT)
        except ValueError:
            display_path = path
        print(f"   ✅ {display_path}")

    # Search-engine push happens after deployment, when the URLs are live.
    new_urls = []
    for path in paths:
        try:
            new_urls.append(site_url_for_post_path(path))
        except ValueError:
            pass
    save_new_push_urls(new_urls)
    return paths


def save_wechat_outputs(
    wechat_articles: list[dict[str, Any]],
    slot: str,
    persona: str,
) -> list[Path]:
    print("📱 写入公众号文章...")
    paths: list[Path] = []
    date_slug = batch_date_slug()
    wechat_metadata = optimize_wechat_metadata(wechat_articles[:3], persona)

    for index, article in enumerate(wechat_articles[:3]):
        title = clean_unicode_text(article.get("title", "公众号文章"))
        summary = clean_unicode_text(article.get("summary") or "")
        cover = clean_unicode_text(article.get("cover") or "")
        if not cover:
            fallback_cover = f"/images/covers/briefing-{date_slug}-{slot}.jpg"
            fallback_path = ROOT / "public" / fallback_cover.lstrip("/")
            if fallback_path.exists():
                print(f"   ⚠️ 公众号文章缺少封面，复用本批简讯封面: {title[:40]}")
                cover = fallback_cover
                article["cover"] = cover
        cover_url = absolute_site_url(cover)
        site_url = clean_unicode_text(article.get("site_url") or "")
        body_md = improve_markdown_readability(clean_unicode_text(article.get("content_md", "")))
        article["content_md"] = body_md
        body_wechat = normalize_wechat_body(body_md)
        meta = wechat_metadata[index] if index < len(wechat_metadata) else {}
        wechat_title = clean_unicode_text(meta.get("wechat_title") or wechat_safe_title(title, summary))
        wechat_digest = clean_unicode_text(meta.get("wechat_digest") or wechat_safe_digest(summary, body_md))
        article["wechat_title"] = wechat_title
        article["wechat_digest"] = wechat_digest

        path = WECHAT_OUTPUT_DIR / f"{date_slug}-{slot}-{slugify(title)}.md"
        content_parts = ["标题", str(title), ""]
        if wechat_title != title:
            content_parts.extend(["公众号标题", wechat_title, ""])
        if wechat_digest:
            content_parts.extend(["公众号摘要", wechat_digest, ""])
        if cover_url:
            content_parts.extend(["封面图", cover_url, ""])
        if site_url:
            content_parts.extend(["网站链接", site_url, ""])
        content_parts.extend(["正文内容", body_wechat])
        content = "\n".join(content_parts).rstrip() + "\n"
        path.write_text(content, encoding="utf-8")
        paths.append(path)

        draft_payload_path = WECHAT_OUTPUT_DIR / f"{date_slug}-{slot}-{slugify(title)}-draft.json"
        draft_payload = {
            "candidate_id": clean_unicode_text(article.get("candidate_id") or ""),
            "title": title,
            "summary": summary,
            "wechat_title": wechat_title,
            "wechat_digest": wechat_digest,
            "cover": clean_unicode_text(article.get("cover") or ""),
            "cover_url": cover_url,
            "site_url": site_url,
            "sources": article.get("sources") or [],
            "content_md": body_md,
            "need_open_comment": 1,
        }
        draft_payload_path.write_text(
            json.dumps(clean_json_value(draft_payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        paths.append(draft_payload_path)

    for path in paths:
        try:
            display_path = path.relative_to(ROOT)
        except ValueError:
            display_path = path
        print(f"   ✅ {display_path}")

    write_wechat_archive_record(wechat_articles[:3], slot)
    return paths


def build_wechat_articles_from_reports(investigation_reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    for report in investigation_reports[:3]:
        title = str(report.get("title") or "公众号文章")
        summary = str(report.get("summary") or "")
        content_md = ensure_personal_footer(str(report.get("content_md") or ""))
        articles.append(
            {
                "candidate_id": str(report.get("candidate_id") or ""),
                "topic": report.get("topic", "life-signal"),
                "title": title,
                "summary": summary,
                "cover_prompt_en": str(report.get("cover_prompt_en") or report.get("prompt_en") or ""),
                "cover_prompt_zh": str(report.get("cover_prompt_zh") or ""),
                "cover": str(report.get("cover") or ""),
                "content_md": content_md,
                "site_url": str(report.get("site_url") or ""),
                "sources": report.get("sources") or [],
            }
        )
    return articles


def build_wechat_articles_from_briefing(briefing: dict[str, Any]) -> list[dict[str, Any]]:
    if not briefing.get("items"):
        return []
    title = str(briefing.get("title") or "每日简讯")
    summary = str(briefing.get("summary") or "")
    content_md = ensure_personal_footer(str(briefing.get("content_md") or ""))
    return [
        {
            "topic": "daily-briefing",
            "title": title,
            "summary": summary,
            "cover_prompt_en": "",
            "cover_prompt_zh": "",
            "cover": str(briefing.get("cover") or ""),
            "content_md": content_md,
            "site_url": str(briefing.get("site_url") or ""),
        }
    ]


def parse_frontmatter_post(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not match:
        return None
    fm_raw, body = match.groups()
    data: dict[str, Any] = {}
    sources: list[dict[str, str]] = []
    current_source: dict[str, str] | None = None
    for line in fm_raw.splitlines():
        if line.startswith("  - name:"):
            current_source = {"name": parse_frontmatter_scalar(line.split(":", 1)[1].strip())}
            sources.append(current_source)
            continue
        if line.startswith("    url:") and current_source is not None:
            current_source["url"] = parse_frontmatter_scalar(line.split(":", 1)[1].strip())
            continue
        if ":" not in line or line.startswith(" "):
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = parse_frontmatter_scalar(value.strip())
    if sources:
        data["sources"] = sources
    title = str(data.get("title") or path.stem)
    category = path.parent.name
    return {
        "topic": category,
        "title": title,
        "summary": str(data.get("description") or ""),
        "cover": str(data.get("cover") or ""),
        "content_md": body.strip(),
        "site_url": site_url_for_post_path(path),
        "sources": data.get("sources") or [],
        "published_at": str(data.get("date") or ""),
        "path": str(path.relative_to(ROOT)),
    }


def parse_frontmatter_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    try:
        return json.loads(value)
    except Exception:
        return value


def tg_escape(value: Any) -> str:
    return html.escape(clean_unicode_text(value), quote=False)


def send_telegram_message(lines: list[str], thread_id: str | None = None) -> bool:
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return False
    text = "\n".join(line for line in lines if line is not None).strip()
    if not text:
        return False

    thread_payload: dict[str, int] = {}
    if thread_id:
        try:
            thread_payload["message_thread_id"] = int(thread_id)
        except (TypeError, ValueError):
            print(f"   ⚠️ Telegram topic id 无效，改发到默认会话: {thread_id}")

    chunks: list[str] = []
    current = ""
    for line in text.splitlines():
        next_text = f"{current}\n{line}".strip() if current else line
        if current and len(next_text) > 3900:
            chunks.append(current)
            current = line
        else:
            current = next_text
    if current:
        chunks.append(current)

    ok = True
    for chunk in chunks:
        payload: dict[str, Any] = {
            "chat_id": TG_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            **thread_payload,
        }
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                print(f"   ⚠️ Telegram 发送失败: {data}")
                ok = False
        except Exception as exc:
            print(f"   ⚠️ Telegram 发送失败: {exc}")
            ok = False
    return ok


def _send_telegram_summary(
    briefing: dict[str, Any],
    investigation_reports: list[dict[str, Any]],
    slot: str,
) -> None:
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("📭 未配置 Telegram，跳过通知")
        return

    topic_titles = {t.slug: t.title for t in TOPICS}
    briefing_items_by_topic: dict[str, list[dict[str, Any]]] = {}
    for item in briefing.get("items", []):
        topic = item.get("topic", "life-signal")
        briefing_items_by_topic.setdefault(topic, []).append(item)

    reports_by_topic: dict[str, list[dict[str, Any]]] = {}
    for article in investigation_reports[:3]:
        topic = article.get("topic", "life-signal")
        reports_by_topic.setdefault(topic, []).append(article)

    sent = 0
    for topic in [t.slug for t in TOPICS]:
        items = briefing_items_by_topic.get(topic, [])[:10]
        reports = reports_by_topic.get(topic, [])
        if not items and not reports:
            continue
        lines: list[str] = [
            f"<b>{tg_escape(topic_titles.get(topic, topic))}</b>",
            f"{batch_date_slug()} {slot}",
            "",
        ]
        if items:
            lines.append("<b>简讯</b>")
            for item in items:
                lines.append(f"• {tg_escape(item.get('title', ''))}｜{tg_escape(item.get('source', ''))}")
                if item.get("url"):
                    lines.append(tg_escape(item["url"]))
        if reports:
            if items:
                lines.append("")
            lines.append("<b>深度文章</b>")
            for article in reports:
                lines.append(f"• {tg_escape(article.get('title', ''))}")
                if article.get("summary"):
                    lines.append(tg_escape(article["summary"]))
                if article.get("site_url"):
                    lines.append(tg_escape(article["site_url"]))
        if briefing.get("site_url"):
            lines.extend(["", f"本批简讯：{tg_escape(briefing['site_url'])}"])
        if send_telegram_message(lines, TG_THREAD_BY_TOPIC.get(topic) or TG_THREAD_BRIEFING):
            sent += 1

    if sent:
        print(f"📨 Telegram 分类通知已发送: {sent} 条")
    else:
        print("📭 Telegram 通知发送失败或无内容")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Easton Radar source-first intelligence pipeline")
    parser.add_argument("--slot", choices=["auto", "morning", "evening"], default="auto", help="日报批次")
    parser.add_argument("--max-age-hours", type=int, default=36, help="RSS 信息最大年龄")
    parser.add_argument("--no-telegram", action="store_true", help="跳过 Telegram 通知")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    now = bj_now()
    set_batch_now(now)
    slot = detect_slot(now, args.slot)
    persona = load_text_config("PERSONA_PATH", ROOT / "config" / "persona.md", PERSONA_DEFAULT)

    ensure_runtime()
    research_method = load_text_config("RESEARCH_SKILL_PATH", ROOT / "config" / "research_skill.md", RESEARCH_METHOD_DEFAULT)
    writing_method = load_text_config("WRITING_SKILL_PATH", ROOT / "config" / "writing_skill.md", WRITING_METHOD_DEFAULT)

    print("🚀 Easton Radar v4")
    print(
        f"   批次: {slot} | 初筛/简讯: {FLASH_MODEL} | "
        f"调查/写作: {PRO_MODEL}({PRO_THINKING}/{PRO_REASONING_EFFORT}) | 主题: {len(TOPICS)}"
    )

    recent_index = load_recent_published_index(days=7)

    collected = collect_sources(args.max_age_hours)
    filtered = initial_filter(collected, persona, recent_index)

    candidates = filtered.get("deep_candidates", [])
    candidates = filter_recent_source_duplicates(candidates, recent_index)
    candidates = assign_candidate_ids(candidates)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        briefing_future = pool.submit(compose_briefing, filtered, persona, slot)
        research_future = pool.submit(research_with_tools, candidates)
        briefing_report = briefing_future.result()
        researched = research_future.result()

    # 阶段一：网站调查报告
    if researched:
        try:
            inv_result = compose_investigation_reports(filtered, researched, research_method, writing_method, slot, recent_index)
        except Exception as exc:
            print(f"   ⚠️ 批量深度文章生成失败，启动逐候选降级: {exc}")
            inv_result = compose_investigation_reports_per_candidate(
                researched, research_method, writing_method, slot, recent_index,
            )
        investigation_reports = filter_reports_to_researched(
            inv_result.get("investigation_reports", []),
            researched,
        )
        if not investigation_reports:
            print("   ⚠️ 批量成文返回空结果，启动逐候选降级")
            inv_result = compose_investigation_reports_per_candidate(
                researched, research_method, writing_method, slot, recent_index,
            )
            investigation_reports = filter_reports_to_researched(
                inv_result.get("investigation_reports", []),
                researched,
            )
    else:
        print("📋 没有深度候选通过证据门槛，本批次跳过调查报告")
        investigation_reports = []

    briefing = briefing_report.get("briefing", {})
    save_website_outputs(briefing, investigation_reports, slot)

    # 阶段二：微信公众号文章
    if investigation_reports:
        wechat_articles = build_wechat_articles_from_reports(investigation_reports)
    elif WECHAT_ALLOW_BRIEFING_FALLBACK:
        print("📭 未生成深度文章，按 WECHAT_ALLOW_BRIEFING_FALLBACK 使用简讯兜底生成公众号草稿")
        wechat_articles = build_wechat_articles_from_briefing(briefing)
    else:
        print("📭 未生成深度文章，默认不使用简讯兜底生成公众号草稿")
        wechat_articles = []
    if wechat_articles:
        save_wechat_outputs(wechat_articles, slot, persona)
        if WECHAT_DRAFT_ENABLED:
            publish_wechat_drafts(wechat_articles, slot)
    else:
        print("📭 没有可用文章，跳过微信公众号输出")

    # Telegram 通知
    if not args.no_telegram:
        _send_telegram_summary(briefing, investigation_reports, slot)

    print("🏁 完成")


if __name__ == "__main__":
    main()
