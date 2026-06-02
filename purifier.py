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
import struct
import threading
import time
from dataclasses import dataclass, replace
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
SITE_URL = os.environ.get("SITE_URL", "https://www.huadongpeng.com").rstrip("/")
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
EMAIL_FROM = os.environ.get("EMAIL_FROM", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "huadongpeng@outlook.com")
EMAIL_SMTP_HOST = os.environ.get("EMAIL_SMTP_HOST", "")
EMAIL_SMTP_PORT = int(os.environ.get("EMAIL_SMTP_PORT", "0"))
INDEXNOW_KEY = os.environ.get("INDEXNOW_KEY", "hdop-indexnow-key")
BAIDU_PUSH_TOKEN = os.environ.get("BAIDU_PUSH_TOKEN", "")
ROOT = Path(__file__).resolve().parent
CONTENT_DIR = ROOT / "src" / "content" / "blog"
CACHE_DIR = ROOT / ".cache" / "radar"
WECHAT_OUTPUT_DIR = ROOT / "outputs" / "wechat_articles"
COVERS_DIR = ROOT / "public" / "images" / "covers"
WECHAT_APP_ID = os.environ.get("WECHAT_APP_ID", "")
WECHAT_APP_SECRET = os.environ.get("WECHAT_APP_SECRET", "")
WECHAT_AUTHOR = os.environ.get("WECHAT_AUTHOR", "老花")
WECHAT_DRAFT_ENABLED = os.environ.get("WECHAT_DRAFT_ENABLED", "true").lower() not in {"0", "false", "no"}
WECHAT_TITLE_MAX_BYTES = 48
WECHAT_DIGEST_MAX_BYTES = 120
SOURCES_CONFIG_PATH = Path(os.environ.get("SOURCES_CONFIG_PATH", ROOT / "config" / "sources.json"))
SILICONFLOW_API_KEY = os.environ.get("SILICONFLOW_API_KEY")
ALLOW_POLLINATIONS_COVER = os.environ.get("ALLOW_POLLINATIONS_COVER", "true").lower() not in {"0", "false", "no"}
# Reddit IP-blocks datacenter ranges (GitHub Actions) on its public .rss; authenticated OAuth
# (app-only client_credentials) is exempt. Configure a "script" app's id/secret to enable it.
REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "script:easton-radar:4.0 (by /u/easton-radar)")
MIN_EVIDENCE_ITEMS = 3
MIN_EVIDENCE_DOMAINS = 2
MAX_FULLTEXT_EVIDENCE = 8
MAX_SEARCH_PAGE_FETCHES = 12
MAX_EVIDENCE_TEXT_CHARS = 5000
MIN_COVER_BYTES = 10_000
EXPECTED_COVER_SIZE = (1024, 576)
BAIDU_MAX_PER_PUSH = 10  # 百度普通收录免费每日配额很小，单次推送上限，避免积压一次性超配额被整批拒绝
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
    "对普通人的启示",
    "这件事给我的思考",
}
SOURCE_HEALTH_LOCK = threading.Lock()


@dataclass(frozen=True)
class Topic:
    slug: str
    title: str
    category: str
    intent: str
    feeds: tuple[str, ...]
    search_seeds: tuple[str, ...]


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
        new_feeds = tuple(str(v).strip() for v in feeds if str(v).strip()) if isinstance(feeds, list) else topic.feeds
        new_search_seeds = (
            tuple(str(v).strip() for v in search_seeds if str(v).strip())
            if isinstance(search_seeds, list)
            else topic.search_seeds
        )
        updated.append(replace(topic, feeds=new_feeds, search_seeds=new_search_seeds))

    try:
        display_path = SOURCES_CONFIG_PATH.relative_to(ROOT)
    except ValueError:
        display_path = SOURCES_CONFIG_PATH
    print(f"   🧩 已加载来源配置: {display_path}")
    return tuple(updated)


TOPICS = load_topic_source_overrides(TOPICS)


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
他们需要事实、依据、分析和判断；能行动的选题再给低成本可验证方案，不适合行动的选题就给观察指标或证据缺口，不需要成功学。
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
7. 每个深度选题都要补充：谁最相关、为什么现在看、能否低成本验证或只适合观察、最大风险、必要时的停止信号、后续观察指标。
"""

WRITING_METHOD_DEFAULT = """
写作原则：
开头必须从一个具体细节切入（时间、价格、页面、报错、聊天句子），绝不用"在当今AI快速发展的时代"。
文章风格是有见识的普通技术人在认真聊一件打动他的事，不是媒体报道，不是知识付费教程。
读者要的不是产品说明书，是买家秀：具体的人在具体处境里留下的攻略、体验、感受和踩坑。产品说明书才论优不优秀，买家秀只论真不真实。
不要追求渊博，不要为了显得全面而堆"行业认为/有研究表明/某某观点"。每段都要问：这是说明书谁都能写，还是只有活过、查过、卡过、犹豫过的我才能写？
面对没有标准答案的问题，不要把 A/B/C 各方观点罗列一遍当全面；要站在 Easton 自己的经历、处境和约束里，给出那个不完整但真实的判断。
反证和不确定性嵌在正文中间出现，不单独开一节。
来源可信度在正文引用时就带出来，不在文章末尾单独开"信息来源与可信度"一节。
标题要短，避免夸张承诺，宁可少写也不要水。
文章内核是闭环：事实、依据、分析、判断、方案/观察。但这不是固定目录；能行动才写方案，不适合行动就写观察指标、证据缺口或暂时不动的理由。

结构禁令：
- 禁止"一、二、三、四、五、六"数字编号大标题
- 禁止"本周/两周内/一个月内"三段时间轴行动计划
- 禁止工具推荐列满四五个选项，只写自己真正用过或打算用的那一两个
- 禁止引用数据不带个人判断（说明来源动机、说明我信几成）
- 禁止把文章写成全知全能但没有个人经历的产品说明书
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


def batch_datetime(slot: str) -> datetime:
    """Use stable publish times so reruns of the same batch don't change URLs/metadata semantics."""
    now = bj_now()
    hour = 6 if slot == "morning" else 18 if slot == "evening" else now.hour
    return now.replace(hour=hour, minute=0, second=0, microsecond=0)


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


def validate_cover_response(resp: requests.Response, data: bytes) -> bool:
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
    if dims != EXPECTED_COVER_SIZE:
        print(f"   ⚠️ 封面尺寸 {dims[0]}x{dims[1]}，期望 {EXPECTED_COVER_SIZE[0]}x{EXPECTED_COVER_SIZE[1]}")
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
                    "model": "Kwai-Kolors/Kolors",
                    "prompt": prompt,
                    "negative_prompt": "text, watermark, logo, words, letters, numbers, blurry, low quality, nsfw",
                    "image_size": "1024x576",
                    "num_inference_steps": 20,
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
                print(f"   🎨 封面图已生成 (SiliconFlow): {output_path.name}")
                return f"/images/covers/{output_path.name}"
        except Exception as exc:
            if ALLOW_POLLINATIONS_COVER:
                print(f"   ⚠️ SiliconFlow 生图失败，降级到 Pollinations: {exc}")
            else:
                print(f"   ⚠️ SiliconFlow 生图失败，已按配置跳过封面: {exc}")

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


def ensure_runtime() -> None:
    if not DEEPSEEK_API_KEY:
        raise SystemExit("❌ 缺少 DEEPSEEK_API_KEY，无法调用 AI 分析。")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    WECHAT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    COVERS_DIR.mkdir(parents=True, exist_ok=True)


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
    print_source_health_warnings()
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
    max_attempts = 3
    for attempt in range(max_attempts):
        chosen_model = model or FLASH_MODEL
        chosen_thinking = FLASH_THINKING if thinking_type is None else thinking_type
        chosen_effort = FLASH_REASONING_EFFORT if reasoning_effort is None else reasoning_effort
        user_content = user
        if attempt:
            user_content = (
                "上一次请求失败或输出不是可解析 JSON。请只返回一个完整、合法、未截断的 JSON object。"
                "不要代码块，不要解释文字，字符串里的换行必须正确转义。\n\n"
                + user
            )
        payload: dict[str, Any] = {
            "model": chosen_model,
            "max_tokens": max_tokens,
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
            blocks.append(
                f"{i}. {item['title']}\n"
                f"source={item.get('source','')}\n"
                f"url={item.get('url','')}\n"
                f"time={item.get('published_at','')}\n"
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
- deep_candidates 选择 2-4 个，必须能通过进一步检索验证。近7天已发布的主题优先跳过；如果有实质性新进展，可以继续写，但 reason 必须说明它和旧文的关系：延续、纠偏、补证据，还是更新判断。
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
            "【读者相关性】分别说明快毕业/刚毕业 IT 人、普通程序员/测试/运维/实施、35 岁前后大龄程序员、小公司技术负责人、副业探索者中，谁最相关，为什么\n"
            "【低成本验证/观察路径】如果普通人能试，给出 1-3 个 0-2 小时或 0-200 元以内的第一步；如果不适合试，说明只适合观察什么、为什么暂时不能下手\n"
            "【主要风险与停止信号】列出最可能亏在哪里；只有涉及尝试、购买、投入或副业验证时才写停止信号\n"
            "【后续观察指标】列出 1-3 个具体可观察指标；如果只能'持续关注'，必须说清楚关注什么信号会改变判断\n"
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
            reasons = "；".join(_evidence_failure_reasons(evidence))
            print(
                "      ⚠️ 证据不足，跳过该候选 "
                f"（{reasons or '未达到门槛'}；需要≥{MIN_EVIDENCE_ITEMS}条证据、"
                f"≥{MIN_EVIDENCE_DOMAINS}个域名、至少1条正文）"
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
    return llm_json(
        system=(
            "你是一名专业中文深度作者，负责撰写供网站和公众号复用的老花式信息追踪文章。"
            "你的读者包括 Easton 本人，也包括快毕业/刚毕业的 IT 新人、普通程序员/测试/运维/实施、35 岁前后的大龄程序员、小公司技术负责人、副业探索者，以及关心信息差的普通读者。"
            "他们想看到来源清晰、不确定性明确标注、论据可查的内容，也想看到一个真实的人如何怀疑、查证、拆条件、算成本、判断自己和读者能不能下场。"
            "写作标准是：事实第一、观点有据、不确定性明确标注，但外形必须像老花把一次真实的信息追踪过程讲给同路人听。"
            "文章不是替老花下结论，而是把老花查一件事、怀疑一件事、拆一件事、判断一件事的过程讲出来。"
            "严格按照【信息探索与研究方法论】的证据标准工作。"
            "必须输出合法 JSON，不要代码块。"
        ),
        user=f"""
当前时间：{bj_now().strftime('%Y-%m-%d %H:%M')} BJT
本次批次：{slot}

【信息探索与研究方法论（必须严格遵守）】
{research_method[:40000]}

【老花文章可读性约束（吸收风格规则；严谨调查内核，真实追踪过程外形）】
{writing_method[:24000]}

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
3. overseas：有跨语言/跨地区信息差价值
4. life-signal：影响普通人生活/工作决策（兜底）

文章结构（根据对象类型自适应，禁止套用固定模板）：

先判断这个对象是什么类型——事件、产品发布、趋势现象、政策变化、人物动向、数据报告还是争议说法——再决定如何展开。不同类型对象的展开重点不同，不得一律用同一套结构。

阅读原则：
- 开头 2-4 段必须从一个具体细节切入：一个日期、金额、产品页面、公告措辞、论坛帖子、功能按钮、价格、限制条件或反直觉数字。不要用宏大背景开场。
- 文章必须呈现一次真实的信息追踪过程，不是直接给结论。要让读者看见老花如何起疑、如何查源头、如何拆隐藏条件、如何算成本和风险、如何判断自己能不能做以及哪些兄弟能做。
- 文章必须是买家秀，不是产品说明书。读者要看的是 Easton 这个具体的人如何理解、卡住、取舍和判断，不是全知全能地复述资料。
- 不要为了显得渊博而把掌握的材料全塞进去。研究素材只取真正服务文章主线的部分；能不用就不用。
- 面对没有标准答案的问题，不要中立罗列 A/B/C 各方观点当全面。可以理解对立面，但最后要站在 Easton 自己的经历、现实约束和风险偏好里，给出不完整但真实的判断。
- 先把读者最该知道的核心矛盾讲出来，再自然展开证据；不要把证据按目录机械排队。
- 每个 H2 标题必须像文章小标题，不要叫"导言"、"核心段"、"证据展开"、"反驳视角"、"影响与悬问"、"信息分层结论"、"证据质量评估"。
- 可以使用少量 H2/H3，但不要过度 Markdown 化；如果只是两个短点，用自然段讲，不要列表。
- 来源可信度要嵌在正文里，例如"这是官方公告，可信度高，但它没有披露价格"。不要在正文末尾单独开"信息来源与可信度"。
- 反证、不确定性、商业动机和利益偏向必须出现，但要随着论证出现，不要集中堆成模板章节。
- 文章内核要有事实、依据、分析和判断；外形要像一个真实的人边查边讲。不能写成"先结论、再证据、最后建议"。
- 对机会类内容必须拆成一种判断：垃圾局、脏机会、老花可试、兄弟可冲、先拆不开。不要直接写"风险评估如下"或"行动建议如下"。
- 文章外形绝不能固定模板。允许顺着思路发散：从一个细节写到行业旧账，再跳回普通人的处境；允许吃瓜、分析、判断、探索并存。天马行空可以，事实边界不能乱。
- 正文主体可以自然使用"我""老花我""咱""咱们""我感觉""我觉得""咱就是说""我就说呢""我真 tama""也是牛掰呀""so tama what"等口语，但不要机械堆词。它们只在判断、破防、转场、号召处出现。
- 不要写"对普通技术经理的现实影响"、"对于多数像 Easton 这样的普通技术经理来说"这种不明觉厉的话。这里要换成更像账号本人会说的话：咱们这些快毕业/刚毕业的 IT 打工人、35 岁门槛前后的程序员、大龄程序员、被裁过或怕失业的人、一个人扛技术方向的小公司 IT 人。
- 如果需要谈读者启示，可以用口语化小标题，例如"这事对咱们这些 IT 打工人有什么用"、"站在 35 岁门槛前后看这件事"；如果文章更适合吃瓜或事实拆解，也可以不单独开这一节。
- 个人判断里可以使用"我"和"咱们"，但不要自我煽情。要把事实拉回现实处境：负债逾期过、输不起、时间少、本金少、怕踩坑、怕失业、怕被新工具甩开、想找一点能验证的方向。负债经历只作为判断力来源，不连续卖惨。
- 如果选题适合行动，给真实可行的小方案，说明适合谁、第一步、成本边界、主要风险、停止信号，以及老花自己能不能做；如果不适合行动，不要硬凑方案，写清楚卡在钱、时间、良心、合规、资源还是执行门槛。
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
- 如果适合行动，给 1-3 个低成本动作，并说明适合谁、今天怎么做、最多投入多少时间/钱、什么情况应该停止。
- 如果不适合行动，写清楚目前还缺哪块证据，或者卡在什么条件上。不要写"观察 3 个信号"这种 AI 味表达。

硬性要求：
- 产出 1-3 篇，优中择优，不要凑数。
- 只能围绕【已通过证据门槛的深度候选】写调查报告；如果 researched 为空或证据不足，返回空数组，不要根据初筛结果硬写。
- 直接使用 research_notes 里的已确认事实作为核心论据，不要基于训练知识编造来源。
- 来源在正文引用时标注名称和可信度，禁止在文末单独列"参考来源"一节。
- 严格区分已确认事实、高概率推断、待验证线索——不把推断写成结论。
- 文章主体是客观网站文章语气；个人判断部分可以自然使用第一人称"我"或"咱们"，位置服从文章节奏。
- 可使用 H2、H3 标题、表格、引用块等 Markdown 格式，但只在真正帮助阅读时使用。
- 禁止输出固定模板标题："导言"、"核心段"、"证据展开"、"反驳视角"、"影响与悬问"、"已确认的事实"、"高概率推断"、"对普通技术经理的现实影响"。
- 禁止写"我为什么停下来""我会盯哪 3 个信号""暂时不动的理由""风险评估如下""行动建议如下""对普通人的启示""这件事给我的思考"这类套话。
- 禁止把行动建议写成成功学口号；如果给行动建议，必须说明成本、边界和停止条件。不要为了显得有用而硬凑建议。
- 生成后自检一次：这是一份具体人的买家秀，还是一份没有人生经历的产品说明书？如果更像产品说明书，必须重写。
- 有实质深度，不是新闻摘要——字数服从内容需要，不要为凑字数堆废话。
- sources 只收录文章正文中实际引用的高/中可信来源，格式 [{{"name": "来源名", "url": "https://..."}}]，2-8 个，url 必须是完整链接，不得用线索级来源。
""",
        max_tokens=64000,
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


def absolute_site_url(path_or_url: str) -> str:
    value = (path_or_url or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    if not value.startswith("/"):
        value = f"/{value}"
    return f"{SITE_URL}{value}"


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
        "封面图已在内容生成流程中生成，下面直接给出图片链接，不再附图片提示词。",
    ]
    for index, article in enumerate(articles, 1):
        cover_url = article.get("cover_url", "")
        site_url = article.get("site_url", "")
        body_parts.extend(
            [
                "",
                f"## {index}. {article['title']}",
            ]
        )
        if cover_url:
            body_parts.append(f"封面图：{cover_url}")
        if site_url:
            body_parts.append(f"网站链接：{site_url}")
    msg.attach(MIMEText("\n".join(body_parts), "plain", "utf-8"))

    for article in articles:
        attachment = MIMEBase("text", "plain")
        attachment.set_payload(article["attachment_txt"].encode("utf-8"))
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
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:6]
    if len(base) <= 42:
        return base
    return f"{base[:36].strip('-')}-{digest}"


def yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def truncate_by_bytes(text: str, max_bytes: int) -> str:
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


def wechat_safe_title(title: str, summary: str = "") -> str:
    """Create a readable WeChat-only title without changing the website title."""
    raw = re.sub(r"\s+", " ", (title or "").strip())
    if not raw:
        raw = re.sub(r"\s+", " ", (summary or "").strip()) or "老花今天追到的新信号"

    candidates = [raw]
    for pattern in (r"[：:，,。！？!?；;]", r"\s+-\s+", r"\s+—\s+"):
        head = re.split(pattern, raw, maxsplit=1)[0].strip()
        if head and head != raw:
            candidates.append(head)

    # Long generated titles often start with a personal action scene. Keep that hook,
    # but remove the trailing explanatory clause that usually breaks the byte limit.
    hook = re.match(r"^(我[^，,。！？!?；;]{4,24})", raw)
    if hook:
        candidates.append(hook.group(1).strip())

    # Prefer the longest candidate that fits; it reads better than a hard cut.
    fitting = [c for c in candidates if len(c.encode("utf-8")) <= WECHAT_TITLE_MAX_BYTES]
    if fitting:
        return max(fitting, key=lambda value: len(value.encode("utf-8")))
    return truncate_by_bytes(raw, WECHAT_TITLE_MAX_BYTES)


def wechat_safe_digest(summary: str, content_md: str = "") -> str:
    raw = re.sub(r"\s+", " ", (summary or "").strip())
    if not raw:
        raw = strip_tags(content_md).strip()
    return truncate_by_bytes(raw, WECHAT_DIGEST_MAX_BYTES)


def optimize_wechat_metadata(
    wechat_articles: list[dict[str, Any]],
    persona: str,
) -> list[dict[str, str]]:
    fallback = [
        {
            "wechat_title": wechat_safe_title(str(article.get("title") or ""), str(article.get("summary") or "")),
            "wechat_digest": wechat_safe_digest(
                str(article.get("summary") or ""),
                str(article.get("content_md") or ""),
            ),
        }
        for article in wechat_articles
    ]
    if not wechat_articles:
        return fallback

    items = []
    for index, article in enumerate(wechat_articles):
        items.append(
            {
                "index": index,
                "topic": str(article.get("topic") or ""),
                "site_title": str(article.get("title") or ""),
                "summary": str(article.get("summary") or ""),
                "content_preview": strip_tags(str(article.get("content_md") or ""))[:900],
            }
        )

    try:
        result = llm_json(
            system=(
                "你是老花公众号的标题编辑，专门把网站文章标题改写成适合微信公众号草稿的标题和摘要。"
                "必须输出合法 JSON，不要 Markdown。"
            ),
            user=f"""
【人设】
{persona[:6000]}

【硬性限制】
- 只优化微信公众号草稿字段，不改网站标题。
- 标题要像老花：第一人称、有追线索/怕踩坑/输不起的真实感；可以有钩子，但不能编造事实。
- 爆款元素只能来自真实材料：具体数字、反差、风险、隐藏条件、我查了一圈后的警觉、普通人能不能试。
- 可以用钩子，但钩子必须求真：让人想点开是因为“这里有坑/有反差/有新判断”，不是因为夸张许诺。
- 标题不要像媒体标题，不要成功学，不要夸张承诺，不要“震惊/必看/爆赚/月入/稳赚/逆袭/封神”。
- 标题必须适合 UTF-8 byte 限制：纯中文控制在 14-16 个汉字左右，混合英文也必须短。
- 摘要必须 1 句话，讲清“这事是什么 + 我为什么警觉/为什么值得看”，不要超过约 40 个汉字。
- 禁止使用第三人称“老花能不能试/老花怎么看”，可用“我/咱们”。
- 每篇先在脑子里生成 3 类标题：具体动作型、风险反差型、普通人关系型；最后只输出你判断最适合公众号的一条。

【待优化文章】
{json.dumps(items, ensure_ascii=False, indent=2)}

请输出 JSON：
{{
  "items": [
    {{
      "index": 0,
      "wechat_title": "公众号标题，尽量短，有钩子但不标题党",
      "wechat_digest": "公众号摘要，一句话"
    }}
  ]
}}
""",
            max_tokens=1200,
            model=FLASH_MODEL,
            thinking_type="disabled",
            reasoning_effort="low",
        )
        optimized = fallback[:]
        for item in result.get("items", []):
            try:
                index = int(item.get("index"))
            except Exception:
                continue
            if not (0 <= index < len(optimized)):
                continue
            title = str(item.get("wechat_title") or "").strip()
            digest = str(item.get("wechat_digest") or "").strip()
            if title:
                optimized[index]["wechat_title"] = truncate_by_bytes(title, WECHAT_TITLE_MAX_BYTES)
            if digest:
                optimized[index]["wechat_digest"] = truncate_by_bytes(digest, WECHAT_DIGEST_MAX_BYTES)
        return optimized
    except Exception as exc:
        print(f"   ⚠️ 微信标题 Flash 优化失败，回退规则标题: {exc}")
        return fallback


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


def site_url_for_post_path(path: Path) -> str:
    rel = path.relative_to(CONTENT_DIR)
    url_path = "/blog/" + "/".join(rel.with_suffix("").parts) + "/"
    return SITE_URL + url_path


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


def inline_markdown_to_wechat_html(text: str) -> str:
    escaped = html.escape(text.strip())
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

    for raw in (md or "").splitlines():
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
        blocks.append(f'<p style="margin: 0 0 16px; line-height: 1.8;">{inline_markdown_to_wechat_html(line)}</p>')

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


def add_wechat_draft(access_token: str, article: dict[str, Any], thumb_media_id: str) -> str:
    title = str(article.get("wechat_title") or article.get("title") or "公众号文章")
    summary = str(article.get("wechat_digest") or article.get("summary") or "")
    safe_title = truncate_by_bytes(title.strip(), WECHAT_TITLE_MAX_BYTES)
    safe_digest = truncate_by_bytes(summary.strip(), WECHAT_DIGEST_MAX_BYTES)
    content_html = markdown_to_wechat_html(str(article.get("content_md") or ""))
    payload = {
        "articles": [
            {
                "title": safe_title,
                "author": WECHAT_AUTHOR,
                "digest": safe_digest,
                "content": content_html,
                "content_source_url": str(article.get("site_url") or ""),
                "thumb_media_id": thumb_media_id,
                "show_cover_pic": 1,
                "need_open_comment": 0,
                "only_fans_can_comment": 0,
            }
        ]
    }
    resp = requests.post(
        "https://api.weixin.qq.com/cgi-bin/draft/add",
        params={"access_token": access_token},
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    media_id = data.get("media_id")
    if not media_id:
        raise RuntimeError(f"创建微信草稿失败: {data}")
    return str(media_id)


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

    for article in wechat_articles[:3]:
        title = str(article.get("title") or "公众号文章")
        cover_path = local_cover_path(str(article.get("cover") or ""))
        if not cover_path:
            print(f"   ⚠️ 缺少本地封面图，跳过草稿: {title[:40]}")
            continue
        try:
            thumb_media_id = upload_wechat_cover(access_token, cover_path)
            draft_media_id = add_wechat_draft(access_token, article, thumb_media_id)
            article["wechat_draft_media_id"] = draft_media_id
            results.append({"title": title, "draft_media_id": draft_media_id})
            print(f"   ✅ 草稿已创建: {title[:40]} ({draft_media_id})")
        except Exception as exc:
            print(f"   ⚠️ 草稿推送失败: {title[:40]} - {exc}")
    return results


def write_wechat_archive_record(email_articles: list[dict[str, str]], slot: str) -> None:
    if not email_articles:
        return
    date_slug = bj_now().strftime("%Y-%m-%d")
    record = {
        "date": date_slug,
        "slot": slot,
        "created_at": bj_now().isoformat(timespec="seconds"),
        "email_to": EMAIL_TO,
        "articles": [
            {
                "title": article.get("title", ""),
                "body_chars": len(article.get("body_txt", "")),
                "has_cover_url": bool(article.get("cover_url")),
                "site_url": article.get("site_url", ""),
            }
            for article in email_articles
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


def save_website_outputs(
    briefing: dict[str, Any],
    investigation_reports: list[dict[str, Any]],
    slot: str,
) -> list[Path]:
    print("💾 写入网站内容（简讯 + 调查报告）...")
    paths: list[Path] = []
    date_slug = bj_now().strftime("%Y-%m-%d")
    publish_time = batch_datetime(slot)
    update_time = bj_now()

    if briefing.get("items"):
        body = render_briefing_md(briefing, slot)
        briefing_title = briefing.get("title") or f"{date_slug} {slot} 简讯"
        briefing_summary = briefing.get("summary", "")
        briefing_cover = ""
        try:
            img_prompt = generate_cover_prompt(briefing_title, briefing_summary)
            briefing_cover = generate_cover_image(img_prompt, f"briefing-{date_slug}-{slot}")
        except Exception as exc:
            print(f"   ⚠️ 简讯封面图流程异常: {exc}")
        briefing_path = write_post(
            "daily-briefing",
            f"briefing-{date_slug}-{slot}.md",
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
        forbidden_headings = detect_forbidden_report_headings(body)
        if forbidden_headings:
            print(f"   ⚠️ 模型返回固定报告标题，已降级处理: {', '.join(sorted(set(forbidden_headings)))}")
            body = soften_report_template_headings(body)
        body = ensure_personal_footer(body)
        warn_if_action_advice_unbounded(body, title)
        article["content_md"] = body
        filename_stem = f"investigation-{date_slug}-{slot}-{slugify(title)}"

        cover_path = ""
        try:
            img_prompt = generate_cover_prompt(title, summary)
            article["cover_prompt_en"] = img_prompt
            article["cover_prompt_zh"] = article.get("cover_prompt_zh") or ""
            cover_path = generate_cover_image(img_prompt, filename_stem)
            article["cover"] = cover_path
        except Exception as exc:
            print(f"   ⚠️ 封面图流程异常: {exc}")
            article["cover"] = cover_path

        article_path = write_post(
            topic,
            f"{filename_stem}.md",
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

    # 主动通知搜索引擎收录新文章
    new_urls = []
    for path in paths:
        try:
            new_urls.append(site_url_for_post_path(path))
        except ValueError:
            pass
    if new_urls:
        submit_indexnow(new_urls)
        submit_baidu(new_urls)

    return paths


def save_wechat_outputs(
    wechat_articles: list[dict[str, Any]],
    slot: str,
    persona: str,
) -> list[Path]:
    print("📱 写入公众号文章并发送邮件...")
    paths: list[Path] = []
    email_articles: list[dict[str, str]] = []
    date_slug = bj_now().strftime("%Y-%m-%d")
    wechat_metadata = optimize_wechat_metadata(wechat_articles[:3], persona)

    for index, article in enumerate(wechat_articles[:3]):
        title = article.get("title", "公众号文章")
        summary = str(article.get("summary") or "")
        cover_url = absolute_site_url(str(article.get("cover") or ""))
        site_url = str(article.get("site_url") or "")
        body_md = article.get("content_md", "")
        body_wechat = normalize_wechat_body(body_md)
        meta = wechat_metadata[index] if index < len(wechat_metadata) else {}
        wechat_title = meta.get("wechat_title") or wechat_safe_title(str(title), summary)
        wechat_digest = meta.get("wechat_digest") or wechat_safe_digest(summary, str(body_md))
        article["wechat_title"] = wechat_title
        article["wechat_digest"] = wechat_digest

        path = WECHAT_OUTPUT_DIR / f"{date_slug}-{slot}-{slugify(title)}.md"
        content_parts = ["标题", str(title), ""]
        if wechat_title != str(title):
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
            "title": str(title),
            "summary": summary,
            "wechat_title": wechat_title,
            "wechat_digest": wechat_digest,
            "cover": str(article.get("cover") or ""),
            "cover_url": cover_url,
            "site_url": site_url,
            "content_md": body_md,
        }
        draft_payload_path.write_text(json.dumps(draft_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        paths.append(draft_payload_path)

        email_articles.append(
            {
                "title": title,
                "cover_url": cover_url,
                "site_url": site_url,
                "body_txt": body_wechat,
                "attachment_txt": content,
            }
        )

    for path in paths:
        try:
            display_path = path.relative_to(ROOT)
        except ValueError:
            display_path = path
        print(f"   ✅ {display_path}")

    send_email_articles(email_articles, slot)
    write_wechat_archive_record(email_articles, slot)
    return paths


def build_wechat_articles_from_reports(investigation_reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    for report in investigation_reports[:3]:
        title = str(report.get("title") or "公众号文章")
        summary = str(report.get("summary") or "")
        content_md = ensure_personal_footer(str(report.get("content_md") or ""))
        articles.append(
            {
                "topic": report.get("topic", "life-signal"),
                "title": title,
                "summary": summary,
                "cover_prompt_en": str(report.get("cover_prompt_en") or report.get("prompt_en") or ""),
                "cover_prompt_zh": str(report.get("cover_prompt_zh") or ""),
                "cover": str(report.get("cover") or ""),
                "content_md": content_md,
                "site_url": str(report.get("site_url") or ""),
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


# ─── 搜索引擎主动推送 ─────────────────────────────────────────────────────────

def pending_push_path(service: str) -> Path:
    return CACHE_DIR / f"pending_push_urls_{service}.json"


def load_pending_push_urls(service: str) -> list[str]:
    path = pending_push_path(service)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(url) for url in data if isinstance(url, str) and url.startswith("http")]
    except Exception as exc:
        print(f"   ⚠️ 待读推送记录读取失败: {exc}")
    return []


def save_pending_push_urls(service: str, urls: list[str]) -> None:
    unique = sorted({url for url in urls if url.startswith("http")})
    path = pending_push_path(service)
    if not unique:
        if path.exists():
            path.unlink()
        return
    path.write_text(json.dumps(unique[:500], ensure_ascii=False, indent=2), encoding="utf-8")


def merged_push_urls(service: str, urls: list[str]) -> list[str]:
    pending = load_pending_push_urls(service)
    merged = list(dict.fromkeys([*pending, *urls]))
    if pending:
        print(f"   🔁 合并待补推 URL: {len(pending)} 条")
    return merged

def submit_indexnow(urls: list[str]) -> None:
    """Push new URLs to Bing / Yandex via IndexNow protocol."""
    if not urls:
        return
    urls = merged_push_urls("indexnow", urls)
    try:
        resp = requests.post(
            "https://api.indexnow.org/indexnow",
            json={
                "host": "www.huadongpeng.com",
                "key": INDEXNOW_KEY,
                "keyLocation": f"{SITE_URL}/{INDEXNOW_KEY}.txt",
                "urlList": urls[:100],
            },
            timeout=15,
        )
        print(f"   🔍 IndexNow (Bing/Yandex) 推送 {len(urls)} 条 → HTTP {resp.status_code}")
        if 200 <= resp.status_code < 300:
            save_pending_push_urls("indexnow", [])
        else:
            save_pending_push_urls("indexnow", urls)
    except Exception as exc:
        print(f"   ⚠️ IndexNow 推送失败: {exc}")
        save_pending_push_urls("indexnow", urls)


def submit_baidu(urls: list[str]) -> None:
    """Push new URLs to Baidu via Active Push API.

    Baidu 普通收录 has a small daily quota; if we resend the whole accumulated backlog every run
    it exceeds the quota and Baidu rejects the entire batch ("over quota"), so nothing ever drains.
    Push newest-first in capped batches and keep the remainder pending to drain over later runs.
    """
    if not urls:
        return
    pending = load_pending_push_urls("baidu")
    # This run's fresh URLs first, then backlog — newest content matters most for indexing.
    ordered = list(dict.fromkeys([*urls, *pending]))
    if pending:
        print(f"   🔁 合并待补推 URL: {len(pending)} 条")
    if not BAIDU_PUSH_TOKEN:
        save_pending_push_urls("baidu", ordered)
        print("   📭 未配置 BAIDU_PUSH_TOKEN，已暂存本批 URL，等待后续补推")
        return
    batch = ordered[:BAIDU_MAX_PER_PUSH]
    rest = ordered[len(batch):]
    # 百度站长平台验证的域名为 www.huadongpeng.com，与 SITE_URL 一致。
    site = urlparse(SITE_URL).hostname or "www.huadongpeng.com"
    try:
        resp = requests.post(
            f"http://data.zz.baidu.com/urls?site={site}&token={BAIDU_PUSH_TOKEN}",
            data="\n".join(batch),
            headers={"Content-Type": "text/plain"},
            timeout=15,
        )
        result = resp.json()
        # Baidu returns {"error":N,"message":...} on quota/auth/site problems — surface it instead of
        # silently reporting "成功 0 条", which hides the real cause.
        if "error" in result:
            print(f"   ⚠️ 百度推送被拒: error={result.get('error')} {result.get('message', '')} (site={site})")
            save_pending_push_urls("baidu", ordered)
            return
        success = int(result.get("success", 0))
        not_same = result.get("not_same_site") or []
        not_valid = result.get("not_valid") or []
        detail = f"，剩余配额 {result.get('remain', '?')}"
        if not_same:
            detail += f"，站点不匹配 {len(not_same)} 条（核对百度站长验证域名是否为 {site}）"
        if not_valid:
            detail += f"，非法 URL {len(not_valid)} 条"
        print(f"   🔍 百度主动推送 {len(batch)} 条 → 成功 {success} 条{detail}")
        # Keep the un-pushed remainder pending; on partial failure, retry the whole ordered set.
        save_pending_push_urls("baidu", rest if success >= len(batch) else ordered)
    except Exception as exc:
        print(f"   ⚠️ 百度推送失败: {exc}")
        save_pending_push_urls("baidu", ordered)


# ─── Telegram 通知 ────────────────────────────────────────────────────────────

def tg_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_telegram_message(lines: list[str], thread_id: str | None = None) -> bool:
    payload: dict[str, Any] = {
        "chat_id": TG_CHAT_ID,
        "text": "\n".join(lines)[:3900],
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    if thread_id:
        try:
            payload["message_thread_id"] = int(thread_id)
        except ValueError:
            print(f"   ⚠️ Telegram topic id 非数字，忽略: {thread_id}")
    try:
        resp = requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", json=payload, timeout=20)
        if resp.ok:
            return True
        print(f"   ⚠️ Telegram 失败: {resp.status_code} {resp.text[:160]}")
    except Exception as exc:
        print(f"   ⚠️ Telegram 异常: {exc}")
    return False


def send_telegram(
    briefing: dict[str, Any],
    investigation_reports: list[dict[str, Any]],
    wechat_articles: list[dict[str, Any]],
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
        lines = [
            f"<b>{tg_escape(topic_titles.get(topic, topic))}</b>",
            f"{bj_now().strftime('%Y-%m-%d')} {slot}",
            "",
        ]
        if items:
            lines.append("<b>简讯</b>")
            for item in items:
                title = tg_escape(item.get("title", ""))
                source = tg_escape(item.get("source", ""))
                url = tg_escape(item.get("url", ""))
                lines.append(f"• {title}｜{source}")
                if url:
                    lines.append(url)
        if reports:
            if items:
                lines.append("")
            lines.append("<b>网站深度文章</b>")
            for article in reports:
                title = tg_escape(article.get("title", ""))
                summary = tg_escape(article.get("summary", ""))
                url = tg_escape(article.get("site_url", ""))
                lines.append(f"• {title}")
                if summary:
                    lines.append(summary)
                if url:
                    lines.append(url)

        if briefing.get("site_url"):
            lines.extend(["", f"本批简讯：{tg_escape(briefing.get('site_url', ''))}"])
        if wechat_articles and reports:
            lines.append("公众号源文件已发邮件。")
        if send_telegram_message(lines, TG_THREAD_BY_TOPIC.get(topic) or TG_THREAD_BRIEFING):
            sent += 1

    if sent:
        print(f"📨 Telegram 分类通知已发送: {sent} 条")
    else:
        print("📭 本批次没有可发送的 Telegram 分类内容")


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
    recent_index = load_recent_published_index(days=7)

    # 采集 & 初筛
    collected = collect_sources(args.max_age_hours)
    filtered = initial_filter(collected, persona, recent_index)

    # 简讯
    briefing_report = compose_briefing(filtered, persona, slot)

    # 深度检索
    candidates = filtered.get("deep_candidates", [])
    candidates = filter_recent_source_duplicates(candidates, recent_index)
    researched = research_with_tools(candidates)

    # 阶段一：网站调查报告
    if researched:
        inv_result = compose_investigation_reports(filtered, researched, research_method, writing_method, slot, recent_index)
        investigation_reports = inv_result.get("investigation_reports", [])
    else:
        print("📋 没有深度候选通过证据门槛，本批次跳过调查报告和公众号长文")
        investigation_reports = []
    save_website_outputs(briefing_report.get("briefing", {}), investigation_reports, slot)

    # 阶段二：公众号源文件直接复用网站文章 + 发邮件
    if investigation_reports:
        wechat_articles = build_wechat_articles_from_reports(investigation_reports)
    else:
        wechat_articles = build_wechat_articles_from_briefing(briefing_report.get("briefing", {}))
    if wechat_articles:
        save_wechat_outputs(wechat_articles, slot, persona)
        publish_wechat_drafts(wechat_articles, slot)
    else:
        print("📭 没有可用于公众号草稿的文章，跳过公众号输出")

    # Telegram 通知
    if not args.no_telegram:
        send_telegram(briefing_report.get("briefing", {}), investigation_reports, wechat_articles, slot)

    print("🏁 完成")


if __name__ == "__main__":
    main()
