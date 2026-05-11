import os
import glob
import json
import time
import feedparser
import requests
import re
from datetime import datetime
import concurrent.futures
from duckduckgo_search import DDGS

# ============================================================
# 环境变量
# ============================================================
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
TG_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
SITE_URL = "https://radar.huadongpeng.com"

THREAD_IDS = {
    "Arbitrage-Radar": os.environ.get("TG_THREAD_ARBITRAGE"),
    "AI-Frontier": os.environ.get("TG_THREAD_AI"),
    "Cross-Border-Insights": os.environ.get("TG_THREAD_CROSS"),
    "Macro-Events": os.environ.get("TG_THREAD_MACRO"),
    "China-Going-Global": os.environ.get("TG_THREAD_CHINA"),
    "Developer-Goldmine": os.environ.get("TG_THREAD_DEV")
}

# ============================================================
# 六大引擎配置 — 快讯 + 可选深度长文，并行抓取 + 缓存去重
# ============================================================
AGENTS = {
    "Arbitrage-Radar": {
        "title_cn": "零库存套利雷达",
        "emoji": "💰",
        "feeds": [
            "https://news.ycombinator.com/rss",
            "https://www.producthunt.com/feed",
            "https://feed.indiehackers.com/forum/rss",
            "https://www.reddit.com/r/SaaS/top/.rss?t=day",
            "https://www.reddit.com/r/SideProject/top/.rss?t=day",
            "https://www.reddit.com/r/Entrepreneur/top/.rss?t=day",
            "https://www.reddit.com/r/juststart/top/.rss?t=day",
            "https://acquire.com/blog/feed/",
            "https://starterstory.com/rss",
            "https://betalist.com/feed",
            "https://saasclub.co/feed/",
            "https://v2ex.com/feed/create.xml",
            "https://sspai.com/feed",
            "https://www.geekpark.net/rss",
            "https://www.oschina.net/news/rss",
        ],
        "briefing_prompt": """你是独立开发者商业情报官。请扫描资料库，提炼今天最有价值的 3-5 条商业/套利/副业信息。

输出 JSON（不要代码块外壳）：
{
  "briefing": {
    "title": "当日快讯标题（10字以内）",
    "items": [
      {
        "title": "信息标题",
        "source": "来源平台名",
        "one_liner": "一句话核心要点（30字内）",
        "why_matters": "为什么值得关注（50字内）",
        "zero_cost_angle": "零/低成本可执行角度（40字内，若无则填'暂无可执行角度'）"
      }
    ],
    "tg_brief": "Telegram 推送用汇总文案（200字内，按 1. 2. 3. 编号，每条包含来源+核心要点+零成本切入点）"
  },
  "deep_dive": null
}

如果今天资料库中有一条信息具备深度拆解价值（数据充分、案例具体、可落地），则 deep_dive 字段输出：
{
  "title": "深度长文标题",
  "content_md": "完整 Markdown 正文（按四章结构：商业模型拆解→本土化映射→MVP落地方案→风险天花板，核心章节≥500字，含≥30行可运行Python代码片段）",
  "tg_summary": "Telegram 精简推送（50字内，包含一个核心数据点+行动引导动词）"
}

硬性要求：
- 所有个人机会必须考虑零成本或低成本（< 500 元启动）方案
- 每条信息必须标注来源平台
- tg_brief 必须按编号列出，每条有实质内容
- 如果今天没有值得深度拆解的话题，deep_dive 填 null，不要强行输出""",

        "deep_dive_prompt": """你是年收入 50 万美元的独立开发者。请从资料库中挑选最有商业价值的话题，输出一份可执行的深度拆解报告。

输出纯净 JSON（不要代码块外壳）：
{
  "title": "文章标题（10字以内）",
  "content_md": "完整 Markdown 正文",
  "tg_summary": "Telegram 精简推送（50字内，含核心数据点+行动引导动词）"
}

content_md 严格按以下四章结构：
## 一、商业模型白盒拆解
- 收入逻辑 + 成本结构 + 利润公式（用具体数字）
- 2-3 个真实案例（注明来源、收入/用户量数据）

## 二、中国市场本土化映射
- 微信/小红书/闲鱼/拼多多/抖音生态中的对等机会
- ≥2 个具体套利切入点（信息差/平台差/汇率差）

## 三、MVP 落地执行方案（核心章节，≥500 字）
- ≥30 行可直接运行的 Python 代码
- Day1 / Day2 / Day3 分步清单（每步 30 分钟内可完成）

## 四、风险与天花板
- 3 大风险 + 退出策略
- 3 个月后收入天花板预估

硬性要求：所有方案必须是零成本或低成本（< 500 元启动）。代码必须可运行。每个观点有数据或案例支撑。"""
    },

    "AI-Frontier": {
        "title_cn": "AI 生产力前沿",
        "emoji": "🤖",
        "feeds": [
            # 大模型厂商官方
            "https://openai.com/blog/rss.xml",
            "https://www.anthropic.com/feed/",
            "https://blog.google/technology/ai/rss/",
            "https://deepmind.google/blog/feed.xml",
            "https://ai.meta.com/blog/feed/",
            "https://mistral.ai/feed/",
            # AI 前沿媒体
            "https://tldr.tech/ai/rss",
            "https://therundown.ai/feed",
            "https://huggingface.co/blog/feed.xml",
            "https://www.technologyreview.com/feed/",
            "https://dev.to/feed/tag/ai",
            "https://www.reddit.com/r/MachineLearning/top/.rss?t=day",
            "https://aivalley.ai/feed",
            "https://venturebeat.com/category/ai/feed/",
            "https://news.ycombinator.com/rss",
            "http://arxiv.org/rss/cs.AI",
            "https://jiqizhixin.com/rss",
        ],
        "briefing_prompt": """你是 AI 技术情报官。请扫描资料库，提炼今天最有价值的 3-5 条 AI/技术前沿信息。

输出 JSON（不要代码块外壳）：
{
  "briefing": {
    "title": "当日快讯标题（10字以内）",
    "items": [
      {
        "title": "信息标题",
        "source": "来源平台名",
        "one_liner": "一句话核心要点（30字内）",
        "why_matters": "为什么值得关注（50字内）",
        "zero_cost_angle": "零/低成本可执行角度（40字内，若无则填'待观察'）"
      }
    ],
    "tg_brief": "Telegram 推送用汇总文案（200字内，按 1. 2. 3. 编号，每条包含来源+核心要点+零成本切入点）"
  },
  "deep_dive": null
}

如果今天资料库中有一条信息具备深度拆解价值（技术突破性足够、有接入可能），则 deep_dive 字段输出：
{
  "title": "深度长文标题",
  "content_md": "完整 Markdown 正文（按四章结构：技术原理白盒拆解→替代人工量化分析→实战接入方案→3个月演进预测，核心章节≥500字，含≥40行可运行Python代码）",
  "tg_summary": "Telegram 精简推送（50字内，含核心数据点+行动引导动词）"
}

硬性要求：
- 所有个人接入方案必须考虑零成本或低成本
- 每条信息必须标注来源平台
- tg_brief 必须按编号列出
- 如果今天没有值得深度拆解的话题，deep_dive 填 null""",

        "deep_dive_prompt": """你是顶级 AI 架构师。请从资料库中挑选最具突破性的 AI 技术，输出一份硬核深度分析。

输出纯净 JSON：
{
  "title": "文章标题（10字以内）",
  "content_md": "完整 Markdown 正文",
  "tg_summary": "Telegram 精简推送（50字内，含核心数据点+行动引导动词）"
}

content_md 严格按以下四章结构：
## 一、技术原理白盒拆解
- 通俗 + 技术双轨解释核心原理
- 与同类方案性能/成本对比表（≥3 维度）

## 二、替代人工的量化分析
- 3-5 种可被替代的人工操作场景
- 每个场景的时间/成本节省量化估算

## 三、Easton 实战接入方案（核心章节，≥500 字）
- ≥40 行可运行 Python 代码（含错误处理+日志）
- API 关键参数、费用预估、常见坑点

## 四、未来 3 个月演进预测
- 技术路线方向 + 潜在颠覆点
- 现在就应该布局的准备动作

硬性要求：所有接入方案必须是零成本或低成本。代码必须可运行。拒绝营销话术。"""
    },

    "Cross-Border-Insights": {
        "title_cn": "跨国商业脑洞",
        "emoji": "🌍",
        "feeds": [
            "https://www.reddit.com/r/Entrepreneur/top/.rss?t=day",
            "https://www.wired.com/feed/rss",
            "https://restofworld.org/feed/",
            "https://www.theguardian.com/world/rss",
            "https://www.semafor.com/feed/technology/rss",
            "https://pragmaticengineer.com/feed",
            "https://stratechery.com/feed/",
            "https://lennysnewsletter.com/feed",
            "https://review.firstround.com/feed.xml",
        ],
        "briefing_prompt": """你是跨国商业观察家。请扫描资料库，提炼今天最有价值的 3-5 条跨国商业/海外模式信息。

输出 JSON（不要代码块外壳）：
{
  "briefing": {
    "title": "当日快讯标题（10字以内）",
    "items": [
      {
        "title": "信息标题",
        "source": "来源平台名",
        "one_liner": "一句话核心要点（30字内）",
        "why_matters": "为什么值得关注（50字内）",
        "zero_cost_angle": "零/低成本可执行角度（40字内，若无则填'待观察'）"
      }
    ],
    "tg_brief": "Telegram 推送用汇总文案（200字内，按 1. 2. 3. 编号，每条包含来源+核心要点+零成本切入点）"
  },
  "deep_dive": null
}

如果今天资料库中有一条信息具备深度拆解价值（模式独特、有本土化套利空间），则 deep_dive 字段输出：
{
  "title": "深度长文标题",
  "content_md": "完整 Markdown 正文（按四章结构：海外模式全景还原→中国缺席底层原因→本土化降维打击方案→窗口期与风险预案，核心章节≥500字，含冷启动策略）",
  "tg_summary": "Telegram 精简推送（50字内，含核心数据点+行动引导动词）"
}

硬性要求：
- 所有个人机会必须考虑零成本或低成本方案
- 每条信息必须标注来源平台
- tg_brief 必须按编号列出
- 如果今天没有值得深度拆解的话题，deep_dive 填 null""",

        "deep_dive_prompt": """你是跨国商业战略顾问。请从资料库中找到一个国外已验证但中国市场空白的模式，输出本土化落地方案。

输出纯净 JSON：
{
  "title": "文章标题（10字以内）",
  "content_md": "完整 Markdown 正文",
  "tg_summary": "Telegram 精简推送（50字内，含核心数据点+行动引导动词）"
}

content_md 严格按以下四章结构：
## 一、海外模式全景还原
- 起源、关键玩家、融资/收入/用户规模数据
- ≥2 个标杆案例深度拆解

## 二、中国缺席的底层原因（核心分析章节）
- 从文化习惯、监管环境、支付体系、物流基建、用户心智 5 维度分析
- 区分真实壁垒 vs 信息差伪壁垒

## 三、本土化降维打击方案
- 适配中国市场的变体模式（信息流/资金流）
- 微信小程序/小红书/抖音冷启动策略（选一平台深讲）

## 四、套利窗口期与风险预案
- 时间窗口预估（6月/1年/3年）
- 3 大风险 + 应对预案

硬性要求：所有方案必须是零成本或低成本启动。必须有具体市场数据。拒绝"感觉式"分析。"""
    },

    "Macro-Events": {
        "title_cn": "宏观局势风向标",
        "emoji": "📉",
        "feeds": [
            "https://techcrunch.com/feed/",
            "https://feeds.bloomberg.com/technology/news.rss",
            "https://www.theverge.com/rss/index.xml",
            "https://feeds.arstechnica.com/arstechnica/index",
            "http://feeds.bbci.co.uk/news/technology/rss.xml",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
            "https://sifted.eu/feed",
            "https://ycombinator.com/blog/rss",
            "https://a16z.com/feed/",
            "https://www.theguardian.com/technology/rss",
        ],
        "briefing_prompt": """你是宏观对冲策略分析师。请扫描资料库，提炼今天 3-5 条对独立开发者影响最大的全球科技/经济事件。

输出 JSON（不要代码块外壳）：
{
  "briefing": {
    "title": "当日快讯标题（10字以内）",
    "items": [
      {
        "title": "信息标题",
        "source": "来源平台名",
        "one_liner": "一句话核心要点（30字内）",
        "why_matters": "为什么值得关注（50字内）",
        "zero_cost_angle": "零/低成本应对建议（40字内，若无则填'持续关注'）"
      }
    ],
    "tg_brief": "Telegram 推送用汇总文案（200字内，按 1. 2. 3. 编号，每条包含来源+核心要点+应对建议）"
  },
  "deep_dive": null
}

如果今天资料库中有一条信息具备深度拆解价值（影响深远、需要决策级分析），则 deep_dive 字段输出：
{
  "title": "深度长文标题",
  "content_md": "完整 Markdown 正文（按四章结构：事件本质与噪音剥离→巨头博弈棋局→独立开发者冲击链→3个月对冲行动清单，核心章节≥500字）",
  "tg_summary": "Telegram 精简推送（50字内，含核心数据点+行动引导动词）"
}

硬性要求：
- 所有个人应对建议必须考虑零成本或低成本
- 每条信息必须标注来源平台
- tg_brief 必须按编号列出
- 如果今天没有值得深度拆解的话题，deep_dive 填 null""",

        "deep_dive_prompt": """你是宏观对冲基金策略师。请从资料库中挑选对独立开发者影响最大的全球事件，输出决策级分析报告。

输出纯净 JSON：
{
  "title": "文章标题（10字以内）",
  "content_md": "完整 Markdown 正文",
  "tg_summary": "Telegram 精简推送（50字内，含核心数据点+行动引导动词）"
}

content_md 严格按以下四章结构：
## 一、事件本质与噪音剥离
- 3 句话概括核心（剥离媒体标题党）
- 3-5 个关键时间节点形成时间线

## 二、巨头博弈棋局（核心分析章节）
- ≥2 方参与者真实战略意图（谁进攻/谁防守）
- 博弈论视角最优策略分析
- 资金/人才流向变化

## 三、独立开发者冲击链
- 融资环境、获客成本、技术栈选择、出海窗口 4 维度传导路径
- 3-5 个预警信号清单

## 四、Easton 3 个月风险对冲行动清单
- 第 1 个月：3 个防御动作
- 第 2 个月：2 个进攻机会
- 第 3 个月：复盘指标与调整节点

硬性要求：必须引用具体数据、公司名称和时间线。所有行动清单必须考虑零成本或低成本。拒绝新闻摘抄。"""
    },

    "China-Going-Global": {
        "title_cn": "中国出海录",
        "emoji": "🌏",
        "feeds": [
            "https://pandaily.com/feed/",
            "https://technode.com/feed/",
            "https://36kr.com/feed",
            "https://www.huxiu.com/rss/0.xml",
            "https://asia.nikkei.com/rss/feed/nar",
            "https://www.scmp.com/rss/91/feed",
            "https://restofworld.org/feed/",
            "https://techinasia.com/feed",
            "https://e27.co/feed",
            "https://yourstory.com/feed",
            "https://inc42.com/feed",
            "https://entrackr.com/feed/",
            "https://latamlist.com/feed",
            "https://contxto.com/feed",
            "https://disrupt-africa.com/feed",
        ],
        "briefing_prompt": """你是中国科技出海战略顾问。请扫描资料库，提炼今天最有价值的 3-5 条中国产品/技术/模式出海的逆向套利信息。

输出 JSON（不要代码块外壳）：
{
  "briefing": {
    "title": "当日快讯标题（10字以内）",
    "items": [
      {
        "title": "信息标题",
        "source": "来源平台名",
        "one_liner": "一句话核心要点（30字内）",
        "why_matters": "为什么值得关注（50字内）",
        "zero_cost_angle": "零/低成本可执行角度（40字内，若无则填'待观察'）"
      }
    ],
    "tg_brief": "Telegram 推送用汇总文案（200字内，按 1. 2. 3. 编号）"
  },
  "deep_dive": null
}

如果今天有值得深度拆解的出海话题（中国独有模式、海外稀缺机会），则 deep_dive 字段输出：
{
  "title": "深度长文标题",
  "content_md": "完整 Markdown 正文（按四章结构：中国模式全景还原→海外缺口分析→出海落地路径→风险与合规，核心章节≥500字）",
  "tg_summary": "Telegram 精简推送（50字内，含核心数据点+行动引导动词）"
}

硬性要求：所有方案必须零成本或低成本启动。必须标注来源平台。deep_dive 宁缺毋滥。""",

        "deep_dive_prompt": """你是中国科技出海战略顾问。请从资料库中找到一个中国独有或领先、海外市场稀缺的商业模式/技术，输出出海落地方案。

输出纯净 JSON：
{
  "title": "文章标题（10字以内）",
  "content_md": "完整 Markdown 正文",
  "tg_summary": "Telegram 精简推送（50字内，含核心数据点+行动引导动词）"
}

content_md 严格按以下四章结构：
## 一、中国模式全景还原
- 该模式在中国的起源、关键玩家、市场规模数据
- 为什么在中国成功（文化/支付/物流/政策四维度分析）

## 二、海外缺口分析（核心章节）
- 目标市场的空白程度和真实需求验证
- 为什么海外没有类似模式（技术/文化/监管差异）
- ≥2 个具体目标国家/地区的市场画像

## 三、出海落地路径（≥500 字）
- 最小可行出海方案（MVP for overseas）
- ≥30 行可运行代码或详细的落地执行步骤
- 本地化适配清单（语言/支付/合规/运营）

## 四、风险与合规
- 3 大出海风险（政策/竞争/文化）
- 零成本启动的具体步骤和资源需求

硬性要求：所有方案必须是零成本或低成本启动。必须有具体市场数据。"""
    },

    "Developer-Goldmine": {
        "title_cn": "开发者金矿",
        "emoji": "⛏️",
        "feeds": [
            # 开发者社区
            "https://news.ycombinator.com/rss",
            "https://www.reddit.com/r/programming/top/.rss?t=day",
            "https://www.reddit.com/r/webdev/top/.rss?t=day",
            # 技术产品
            "https://www.producthunt.com/feed",
            "https://github.com/trending.atom",
            # 技术媒体
            "https://www.technologyreview.com/feed/",
            "https://www.infoworld.com/index.rss",
            # 独立开发者
            "https://feed.indiehackers.com/forum/rss",
        ],
        "briefing_prompt": """你是独立开发者技术变现顾问。请扫描资料库，提炼今天最有价值的 3-5 条开发者变现/工具红利/技术创业信息。

输出 JSON（不要代码块外壳）：
{
  "briefing": {
    "title": "当日快讯标题（10字以内）",
    "items": [
      {
        "title": "信息标题",
        "source": "来源平台名",
        "one_liner": "一句话核心要点（30字内）",
        "why_matters": "为什么值得关注（50字内）",
        "zero_cost_angle": "零/低成本可执行角度（40字内，若无则填'待观察'）"
      }
    ],
    "tg_brief": "Telegram 推送用汇总文案（200字内，按 1. 2. 3. 编号）"
  },
  "deep_dive": null
}

如果今天有值得深度拆解的开发者工具/平台/变现话题，则 deep_dive 字段输出：
{
  "title": "深度长文标题",
  "content_md": "完整 Markdown 正文（按四章结构：技术白盒拆解→变现路径分析→Easton实战接入→3个月红利窗口，核心章节≥500字，含≥40行可运行代码）",
  "tg_summary": "Telegram 精简推送（50字内，含核心数据点+行动引导动词）"
}

硬性要求：所有变现方案必须零成本或低成本启动。代码必须可运行。deep_dive 宁缺毋滥。""",

        "deep_dive_prompt": """你是独立开发者技术变现顾问。请从资料库中挑选最有变现价值的技术/工具/平台，输出实战接入方案。

输出纯净 JSON：
{
  "title": "文章标题（10字以内）",
  "content_md": "完整 Markdown 正文",
  "tg_summary": "Telegram 精简推送（50字内，含核心数据点+行动引导动词）"
}

content_md 严格按以下四章结构：
## 一、技术/工具白盒拆解
- 核心原理、技术架构、关键 API
- 与同类方案对比表（≥3 维度）

## 二、变现路径分析（核心章节）
- ≥3 种可落地的变现方式
- 每种方式的收入预估、成本分析、时间投入
- 适合独立开发者的最优路径推荐

## 三、Easton 实战接入方案（≥500 字）
- ≥40 行可直接运行的 Python/JS 代码
- 从注册到首次收入的完整操作流程
- 常见坑点和排错指南

## 四、3 个月红利窗口
- 该机会的时间窗口预估
- 竞争者进入门槛分析
- 3 个月内可达到的收入预期

硬性要求：所有方案必须零成本或低成本启动。代码必须可运行。"""
    }
}


# ============================================================
# RAG 检索层
# ============================================================
def auto_search_context(query):
    """全网主动检索补充深度背景"""
    try:
        print(f"   🔍 正在全网主动检索: {query[:60]}...")
        results = DDGS().text(query, max_results=5)
        context = ""
        for r in results:
            context += f"-[外网检索] {r['title']}: {r['body']}\n"
        return context
    except Exception as e:
        print(f"   ⚠️ 检索失败，退回纯 RSS 模式: {e}")
        return ""


_FEED_CACHE = {}  # URL → (timestamp, parsed_feed) 防止同一次运行中重复抓取

_FEED_OK = 0
_FEED_FAIL = 0

def _fetch_one_feed(url):
    """抓取单个 RSS feed，带缓存去重"""
    global _FEED_OK, _FEED_FAIL
    if url in _FEED_CACHE:
        ts, cached = _FEED_CACHE[url]
        if time.time() - ts < 300:
            return cached
    feed = feedparser.parse(url)  # feedparser 自带 HTTP，兼容性最好
    if feed.bozo and not feed.entries:
        # feedparser 解析失败，尝试 requests 获取
        try:
            resp = requests.get(url, timeout=15, headers={"User-Agent": "EastonRadar/1.0"})
            feed = feedparser.parse(resp.content)
        except Exception:
            pass
    if not feed.entries:
        _FEED_FAIL += 1
        return []
    _FEED_OK += 1
    entries = []
    for entry in feed.entries[:3]:
        desc = ""
        if hasattr(entry, 'description') and entry.description:
            desc = re.sub('<[^<]+>', '', entry.description)[:200]
        elif hasattr(entry, 'summary') and entry.summary:
            desc = re.sub('<[^<]+>', '', entry.summary)[:200]
        entries.append(f"标题: {entry.title}\n摘要: {desc}")
    _FEED_CACHE[url] = (time.time(), entries)
    return entries


def fetch_and_augment(feeds):
    """并行抓取 RSS + 触发全网主动搜索"""
    raw_articles = []
    top_title = ""

    # 并行抓取所有 feed（4 worker，避免 GitHub Actions 资源限制）
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_fetch_one_feed, feeds))

    for entries in results:
        for text in entries:
            raw_articles.append(text)
            if not top_title:
                # 从第一条摘要中提取标题用于 DuckDuckGo 搜索
                m = re.search(r'标题:\s*(.+)', text)
                if m:
                    top_title = m.group(1)[:80]

    base_context = "\n".join(raw_articles)
    deep_context = auto_search_context(top_title) if top_title else ""
    return base_context + "\n\n【主动全网检索扩充资料】:\n" + deep_context


# ============================================================
# JSON 提取 + DeepSeek API 调用
# ============================================================
def get_recent_titles(category_name, days=3):
    """读取近 N 天文章标题用于去重（仅解析 frontmatter 前 32 行）"""
    titles = []
    posts_dir = os.path.join("content", "posts", category_name)
    if not os.path.isdir(posts_dir):
        return titles
    for md_file in sorted(glob.glob(os.path.join(posts_dir, "*.md")), reverse=True):
        try:
            with open(md_file, "r", encoding="utf-8") as f:
                frontmatter = "".join(f.readline() for _ in range(32))
            if frontmatter.startswith("---"):
                parts = frontmatter.split("---", 2)
                if len(parts) >= 2:
                    for line in parts[1].split("\n"):
                        if line.startswith("title:"):
                            raw = line.split("title:", 1)[1].strip().strip("'\"")
                            raw = re.sub(r"^[^a-zA-Z0-9一-鿿#]+\s*", "", raw)
                            titles.append(raw)
                            break
        except Exception:
            pass
        if len(titles) >= days * 5:
            break
    return titles


def _extract_json(text):
    """从 LLM 输出中稳健提取 JSON 对象"""
    candidates = []

    # 策略 1: 提取 ```json ... ``` 代码块
    for m in re.finditer(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL):
        candidates.append(m.group(1))

    # 策略 2: 平衡括号提取所有顶层 {...} 对象
    for start_m in re.finditer(r'\{', text):
        start = start_m.start()
        depth, in_s, esc = 0, False, False
        for i, ch in enumerate(text[start:], start):
            if esc: esc = False; continue
            if ch == '\\' and in_s: esc = True; continue
            if ch == '"' and not esc: in_s = not in_s; continue
            if in_s: continue
            if ch == '{': depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    candidates.append(text[start:i + 1])
                    break

    # 策略 3: 无外层花括号时，尝试找 briefing/deep_dive 模式并包裹
    if not candidates:
        m = re.search(r'(briefing|deep_dive)\s*:', text)
        if m:
            wrapped = text[m.start():].strip()
            if not wrapped.startswith('{'):
                # 如果以 key: 开头，在首尾加花括号
                wrapped = '{' + wrapped + '}'
                # 在最后一个 } 处截断（可能是多余文本）
                last_brace = wrapped.rfind('}')
                wrapped = wrapped[:last_brace + 1]
                candidates.append(wrapped)

    # 通用修复函数
    def _repair(raw):
        """逐步修复常见 LLM JSON 格式错误"""
        # 尾随逗号
        raw = re.sub(r',\s*([}\]])', r'\1', raw)
        # 无引号属性名（含行首和花括号后）
        raw = re.sub(r'(^|[{,\s\n])([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', raw)
        # 单引号键值
        raw = re.sub(r"'([^']*)':", r'"\1":', raw)
        raw = re.sub(r":\s*'([^']*)'", r': "\1"', raw)
        # 中文引号
        raw = raw.replace('“', '"').replace('”', '"')
        raw = raw.replace('‘', "'").replace('’', "'")
        # 缺失逗号
        raw = re.sub(r'"\s*\n\s*"', '", "', raw)
        raw = re.sub(r'([}\]\d])\s*\n\s*"', r'\1,\n"', raw)
        return raw

    errors = []
    for cand in candidates[-4:]:
        try:
            return json.loads(cand)
        except json.JSONDecodeError as e:
            errors.append(str(e))
            fixed = _repair(cand)
            try:
                return json.loads(fixed)
            except json.JSONDecodeError as e2:
                errors.append(str(e2))
                # 最后手段：压缩空白
                compact = re.sub(r'\n\s*', ' ', fixed)
                try:
                    return json.loads(compact)
                except json.JSONDecodeError as e3:
                    errors.append(str(e3))

    raise ValueError(f"JSON 提取失败: {'; '.join(errors[-3:])}")


def deep_dive_worker(category_name, config):
    print(f"[{category_name}] 抓取 {len(config['feeds'])} 个信息源...", flush=True)
    t0 = time.time()
    context = fetch_and_augment(config['feeds'])
    t1 = time.time()
    entry_count = context.count("标题:")
    print(f"[{category_name}] 获取 {entry_count} 条摘要 ({t1-t0:.0f}s)，唤醒 DeepSeek...", flush=True)

    if entry_count == 0:
        print(f"[{category_name}] 无有效数据，跳过", flush=True)
        return category_name, None

    # 去重：读取近期已覆盖话题
    recent = get_recent_titles(category_name, days=3)
    dedup_hint = ""
    if recent:
        dedup_hint = f"\n\n【重要：去重规则】以下话题最近 3 天已覆盖，请严格避免重复选择相同或高度相似的话题：\n" + \
                     "\n".join(f"- {t}" for t in recent[:15])

    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }

    full_prompt = f"""
当前时间是 {datetime.now().strftime("%Y年%m月%d日")}。
请根据资料库内容，同时生成"快讯汇总（briefing）"和"深度长文（deep_dive，可选）"。

【快讯任务】
{config['briefing_prompt']}

【深度长文任务——仅在资料库有足够深度的话题时生成】
{config['deep_dive_prompt']}

你的输出必须是纯净 JSON 对象（不要代码块外壳），包含 briefing 和 deep_dive 字段。
如果今天没有值得深度长文的话题，deep_dive 填 null。

硬性约束：
- 所有 title 字段严格不超过 10 个中文字（微信标题 32 字节限制，1 中文≈3 字节）
- 全文零 emoji，零网络用语，严谨专业学术商业分析风格
- 个人方案优先考虑零成本或低成本路径
- tg_summary 不超过 50 字，tg_brief 不超过 200 字
"""

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是严谨专业的跨国商业智库分析引擎，严格输出标准 JSON。所有输出必须：零 emoji 表情符号、零网络用语、数据驱动、学术商业分析风格。个人方案必须优先考虑零成本或低成本路径。"},
            {"role": "user", "content": full_prompt + dedup_hint + "\n\n【资料库】\n" + context}
        ]
    }

    try:
        t_api_start = time.time()
        response = requests.post(url, headers=headers, json=payload, timeout=300)
        response.raise_for_status()
        t_api = time.time()

        final_text = response.json()['choices'][0]['message']['content']
        result = _extract_json(final_text)
        has_brief = bool(result.get("briefing"))
        has_deep = bool(result.get("deep_dive") and result["deep_dive"].get("title"))
        print(f"[{category_name}] API {t_api-t_api_start:.0f}s | 快讯:{has_brief} 深度:{has_deep}", flush=True)
        return category_name, result

    except Exception as e:
        print(f"❌ [{category_name}] V4 Pro 推理失败: {e}", flush=True)
        return category_name, None


# ============================================================
# Hugo 落盘 —— 快讯 + 可选深度长文
# ============================================================
def save_to_hugo(category_name, config, data):
    """落盘快讯和深度长文至 Hugo"""
    now = datetime.now()
    hugo_date = now.strftime('%Y-%m-%dT%H:%M:%S%z')
    date_slug = now.strftime("%Y-%m-%d")
    cat_lower = category_name.lower()
    posts_dir = os.path.join("content", "posts", category_name)
    os.makedirs(posts_dir, exist_ok=True)

    briefing = data.get("briefing")
    deep_dive = data.get("deep_dive")
    saved_files = []

    # --- 快讯 ---
    if briefing:
        file_name = os.path.join(posts_dir, f"briefing-{date_slug}.md")
        md = f"---\n"
        md += f"title: '{briefing.get('title', '当日快讯')}'\n"
        md += f"date: {hugo_date}\n"
        md += f"categories: ['{cat_lower}']\n"
        md += f"tags: ['快讯', '每日汇总']\n"
        md += f"draft: false\n"
        md += f"type: briefing\n"
        md += f"---\n\n"
        md += f"> 📋 每日海外情报快讯 | {now.strftime('%Y年%m月%d日')}\n\n"

        items = briefing.get("items", [])
        for i, item in enumerate(items, 1):
            md += f"## {i}. {item.get('title', '无标题')}\n\n"
            md += f"**来源**：{item.get('source', '未知')}\n\n"
            md += f"**核心要点**：{item.get('one_liner', '')}\n\n"
            md += f"**为什么值得关注**：{item.get('why_matters', '')}\n\n"
            za = item.get('zero_cost_angle', '')
            if za and za not in ('暂无可执行角度', '待观察', '持续关注'):
                md += f"**💡 零成本切入点**：{za}\n\n"
            elif za:
                md += f"**💡**：{za}\n\n"
            md += "---\n\n"

        with open(file_name, "w", encoding="utf-8") as f:
            f.write(md)
        saved_files.append(("briefing", file_name))
        print(f"   📄 快讯已落盘: {file_name}")

    # --- 深度长文（仅在有内容时写入） ---
    if deep_dive and deep_dive.get("title") and deep_dive.get("content_md"):
        file_name = os.path.join(posts_dir, f"deep-dive-{date_slug}.md")
        md = f"---\n"
        md += f"title: '{deep_dive['title']}'\n"
        md += f"date: {hugo_date}\n"
        md += f"categories: ['{cat_lower}']\n"
        md += f"tags: ['深度长文', '深度分析']\n"
        md += f"draft: false\n"
        md += f"type: deep_dive\n"
        md += f"---\n\n"
        md += deep_dive['content_md']

        with open(file_name, "w", encoding="utf-8") as f:
            f.write(md)
        saved_files.append(("deep_dive", file_name))
        print(f"   📄 深度长文已落盘: {file_name}")
    else:
        print(f"   ⏭️ [{category_name}] 今日无值得深度长文的话题，跳过")

    return saved_files


# ============================================================
# Telegram 推送 —— 内容丰满版
# ============================================================
def _tg_post(category_name, msg):
    """发送单条 Telegram 消息到指定 Topic"""
    try:
        chat_id_int = int(TG_CHAT_ID.strip())
    except ValueError:
        chat_id_int = TG_CHAT_ID.strip()

    payload = {"chat_id": chat_id_int, "text": msg, "parse_mode": "Markdown",
                "disable_web_page_preview": False}
    thread_id = THREAD_IDS.get(category_name)
    if thread_id and thread_id.strip():
        payload["message_thread_id"] = int(thread_id.strip())

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json=payload, timeout=15
        )
        if resp.status_code == 200:
            print(f"   ✅ [{category_name}] Telegram 推送成功")
            return True
        else:
            err_text = resp.text[:200] if resp.text else "无返回"
            print(f"   ❌ [{category_name}] Telegram 推送失败: {resp.status_code} {err_text}")
            return False
    except Exception as e:
        print(f"   ❌ [{category_name}] Telegram 推送异常: {e}")
        return False


def send_to_telegram(category_name, config, data):
    """推送到 Telegram 群组指定 Topic"""
    briefing = data.get("briefing")
    deep_dive = data.get("deep_dive")
    has_deep = deep_dive and deep_dive.get("title") and deep_dive.get("content_md")
    sent_count = 0

    if briefing:
        items = briefing.get("items", [])
        msg = f"**{config['title_cn']}** 每日快讯\n"
        msg += f"{datetime.now().strftime('%Y.%m.%d')}\n"
        msg += "━━━━━━━━━━━━━━\n\n"

        for i, item in enumerate(items, 1):
            title = item.get('title', '无标题')
            source = item.get('source', '未知')
            one_liner = item.get('one_liner', '')
            why = item.get('why_matters', '')
            za = item.get('zero_cost_angle', '')

            msg += f"**{i}. {title}**\n"
            msg += f"  {source} | {one_liner}\n"
            if why:
                msg += f"  {why}\n"
            if za and za not in ('暂无可执行角度', '待观察', '持续关注'):
                msg += f"  > {za}\n"
            msg += "\n"

        msg += "━━━━━━━━━━━━━━\n"
        msg += f"详情: {SITE_URL}"
        if _tg_post(category_name, msg):
            sent_count += 1

    if has_deep:
        msg = f"**[{config['title_cn']}] 深度长文**\n\n"
        msg += f"**{deep_dive['title']}**\n\n"
        msg += f"{deep_dive.get('tg_summary', '深度分析已发布')}\n\n"
        msg += f"阅读全文: {SITE_URL}/categories/{category_name.lower()}/"
        if _tg_post(category_name, msg):
            sent_count += 1

    return sent_count


# ============================================================
# 主流程
# ============================================================
if __name__ == "__main__":
    print("🚀 启动 Easton 满血外脑：双轨引擎（快讯汇总 + 深度长文）...")
    print(f"   📡 RSS 源总数: {sum(len(c['feeds']) for c in AGENTS.values())}")
    print(f"   🤖 模型: DeepSeek V4 Pro (deepseek-chat)")
    print(f"   ⏱️  并行抓取: 6 引擎 × 4 worker")
    print()

    total_briefings = 0
    total_deep_dives = 0
    total_tg = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        future_to_category = {
            executor.submit(deep_dive_worker, cat, conf): cat
            for cat, conf in AGENTS.items()
        }
        for future in concurrent.futures.as_completed(future_to_category):
            cat = future_to_category[future]
            try:
                category_name, result = future.result()
                if result:
                    saved = save_to_hugo(category_name, AGENTS[category_name], result)
                    for stype, _ in saved:
                        if stype == "briefing":
                            total_briefings += 1
                        elif stype == "deep_dive":
                            total_deep_dives += 1

                    pushed = send_to_telegram(category_name, AGENTS[category_name], result)
                    total_tg += pushed
                else:
                    print(f"   ⚠️ [{cat}] 未获取有效结果")
            except Exception as exc:
                print(f"❌ {cat} 引擎崩溃: {exc}")

    print()
    print(f"🏁 今日流水线执行完毕。")
    print(f"   📊 快讯: {total_briefings} | 深度长文: {total_deep_dives} | Telegram 推送: {total_tg}")
    print(f"   📡 Feed 抓取: {_FEED_OK} 成功 / {_FEED_FAIL} 失败")
