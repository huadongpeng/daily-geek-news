import os
import glob
import json
import time
import feedparser
import requests
import re
import threading
from datetime import datetime, timezone, timedelta
import concurrent.futures
from ddgs import DDGS

# GitHub Actions 使用 UTC，统一转为北京时间
BJT = timezone(timedelta(hours=8))

def bj_now():
    return datetime.now(BJT)

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
BRIEFING_THREAD = os.environ.get("TG_THREAD_BRIEFING")

# ============================================================
# 全球系统提示 — 注入目标读者画像
# ============================================================
SYSTEM_PROMPT = """你是「老花有话说」的情报分析引擎——专门为被AI和全球化冲击最狠的普通人寻找真实可行的出路。

【你的读者不是投资人，不是企业高管，是这些人】
- 28-38岁，有技术基础（会写代码）和基础英语阅读能力，但非名校/大厂背景
- 可能已失业或即将失业（行业萎缩、岗位被AI替代），有房贷/车贷/消费贷压力
- 每月可支配现金<2000元，启动资金<1000元，必须优先零成本路径
- 焦虑但愿意行动：每天可挤出2-4小时尝试新方向
- 信息渠道有限（可能不会翻墙），缺乏海外第一手信息
- 不需要"行业趋势分析"——需要"打开XX网站→做XX→花30分钟→得到XX"
- 愿意学习、愿意尝试、愿意从零开始，但需要有人告诉第一步往哪走

【写作铁律——违反任何一条输出无效】
1. 每条分析后面跟一句"你现在就能做的事"（具体到网站名/工具名/操作动作）
2. 拒绝"XX行业正在变革""XX趋势加速"→改成"去XX平台搜XX→筛选XX→做XX"
3. 所有方案标注三要素：启动成本（元）、时间投入（小时）、预期首周收益（元）
4. 代码必须可运行，工具必须可免费注册，推荐资源优先国内可直接访问的
5. 不要"密切关注XX""建立XX认知"→要"打开XX→点击XX→输入XX→提交"
6. 深度长文不是"深度分析"而是"深度教程"——读者看完能跟着做
7. 宁可800字干货，不写2000字水文
8. 语言像朋友给朋友出主意，不要学术腔、咨询腔、新闻腔

【痛点挖掘——从抱怨和摩擦中发现机会】
机会不是从成功故事里来的，是从别人的不满里来的。请主动从资料中挖掘：
- 人们在抱怨什么？（工具不好用？价格太贵？信息不对称？渠道缺失？被封禁？）
- 人们在求助什么？（"有没有XX工具？""谁知道怎么XX？""求推荐XX？"）
- 人们在对比什么？（"XX vs YY哪个好？""有没有XX的替代品？"）
- 人们在骂什么？（"垃圾XX""坑爹XX""再也不用了"）
每发现一个普遍抱怨→判断是否有人在解决→如果没有→这就是机会。
格式：从[具体抱怨/求助/对比]中发现→[具体机会]→[零成本验证方式]"""

# ============================================================
# 六大引擎配置 — 方向重塑：机会导向 + 可操作性 + 去模板化
# ============================================================
AGENTS = {
    # ====================================================================
    # 引擎 1: Arbitrage-Radar — 本周可验证机会
    # ====================================================================
    "Arbitrage-Radar": {
        "title_cn": "套利雷达",
        "emoji": "💰",
        "feeds": [
            # --- 正面信号：新产品、新项目、新趋势 ---
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
            # --- 负面信号：抱怨、求助、对比、摩擦 → 机会金矿 ---
            "https://www.reddit.com/r/SomebodyMakeThis/top/.rss?t=day",       # 直接的需求：有人求做这个
            "https://www.reddit.com/r/Startup_Ideas/top/.rss?t=day",          # 创业点子
            "https://www.reddit.com/r/Business_Ideas/top/.rss?t=day",         # 商业点子
            "https://www.reddit.com/r/assholedesign/top/.rss?t=day",          # 烂设计→重新设计机会
            "https://www.reddit.com/r/mildlyinfuriating/top/.rss?t=day",     # 日常摩擦→产品机会
            "https://www.reddit.com/r/freelance/top/.rss?t=day",             # 自由职业痛苦→工具/平台机会
            "https://www.reddit.com/r/digitalnomad/top/.rss?t=day",          # 数字游民工具需求
            "https://www.reddit.com/r/webdev/top/.rss?t=day",                # 开发者痛点→更好的工具
        ],
        "briefing_prompt": """你是独立开发者商业情报官。从资料库提炼今天 3-5 条对普通人有操作价值的机会信息。

重点关注两类信号：
1. 正面信号：新产品/新模式/新趋势中有什么个人能抓住的套利点？
2. 负面信号（更重要）：人们在抱怨什么？求助什么？骂什么工具不好用？有没有人在问"有没有XX替代品"？——每一句抱怨都是一个待满足的需求。

每条信息必须回答：月入5000的人，本周能用这条信息做什么？

输出 JSON（不要代码块外壳）：
{
  "briefing": {
    "title": "当日快讯标题（10字内）",
    "items": [
      {
        "title": "信息标题",
        "source": "来源平台名",
        "one_liner": "一句话说清这个机会（30字内）",
        "why_matters": "为什么普通人能做（50字内，说清进入门槛和所需技能）",
        "zero_cost_angle": "本周第一步（40字内，具体操作动词开头：打开/注册/搜索/联系/发布）"
      }
    ],
    "tg_brief": "Telegram 推送用（200字内，编号列表，每条含核心操作指引）"
  },
  "deep_dive": null
}

优先选择有具体操作路径的话题，写出读者能直接照做的步骤。
zero_cost_angle 不能写"在XX平台发帖"这种废话，必须具体到平台名+动作+预期结果。""",

        "deep_dive_prompt": """你是独立开发者创富教练。选一个今天最有操作性的机会，写一份普通人能照着做的执行手册。

输出纯净 JSON：
{
  "title": "文章标题（10字内）",
  "content_md": "完整 Markdown 正文",
  "tg_summary": "Telegram 推送（50字内，含一个核心数据点+行动引导动词）"
}

content_md 自由结构，但必须包含以下内容（不用固定章节标题，自然叙述）：

核心洞察（200字）：这个钱为什么别人还没赚到？是真壁垒还是信息差？
- 如果机会来自抱怨/求助/负面信号：引用具体的抱怨原文（英文可翻译），说明有多少人在抱怨、为什么现有方案没解决

执行清单 Day1-7：每天的具体操作（每天≤30分钟可完成）
- 格式："Day1（周一）：打开XX网站→用XX邮箱注册→搜索XX关键词→筛选XX条件→记录前5个结果"
- 不要说"了解市场"——要说"打开什么网站看什么数据"
- Day1 优先做：去原始抱怨发生的地方（Reddit帖子/V2EX帖子/ProductHunt评论区），数一数有多少人在表达相同的不满

工具清单：名字 + 网址 + 费用 + 如果收费有没有替代免费方案

收益预估（三档）：
- 保守：做对了但没有运气，首月收益 XX 元
- 中等：一般情况，首月收益 XX 元
- 乐观：踩中风口的运气，首月收益 XX 元
- 每档附计算逻辑

3 个最容易踩的坑 + 如何避开

延伸资源：3 个进一步学习的免费资源（YouTube/公众号/B站/网站均可）

首要选题原则：优先选择那些来自负面信号（抱怨/求助/骂声）的机会——这些是真实的需求验证。其次才是正面信号（新产品/新模式）的套利机会。

硬性要求：
- 启动成本<1000元，优先零成本
- 所有工具必须国内可访问或标注替代方案
- 如有代码则必须可运行（含依赖安装和免费API注册）
- 每个步骤具体到操作动词：打开/点击/输入/提交/等待/查看
- 拒绝"建立个人品牌""积累行业认知""持续关注"类空洞话术
- 如果这个话题本质上需要大量资金或资源才能做，就不要选它"""
    },

    # ====================================================================
    # 引擎 2: AI-Frontier — AI 工具实战测评
    # ====================================================================
    "AI-Frontier": {
        "title_cn": "AI 工具实战",
        "emoji": "🤖",
        "feeds": [
            "https://openai.com/blog/rss.xml",
            "https://www.anthropic.com/feed/",
            "https://blog.google/technology/ai/rss/",
            "https://deepmind.google/blog/feed.xml",
            "https://ai.meta.com/blog/feed/",
            "https://mistral.ai/feed/",
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
        ],
        "briefing_prompt": """你是 AI 工具测评师。从资料库提炼今天 3-5 条对普通人最有用的 AI 信息。

重点不是"XX公司发布了XX模型"——而是"这个工具现在能用了吗？怎么用？免费吗？"

输出 JSON：
{
  "briefing": {
    "title": "当日快讯标题（10字内）",
    "items": [
      {
        "title": "信息标题",
        "source": "来源平台名",
        "one_liner": "一句话说清这是什么/能做什么（30字内）",
        "why_matters": "为什么你该试试（50字内，说清免费额度/上手难度/效率提升量化）",
        "zero_cost_angle": "立即体验：打开XX→注册→试XX功能（40字内）"
      }
    ],
    "tg_brief": "Telegram 推送用（200字内，编号列表）"
  },
  "deep_dive": null
}

优先选择有实用价值的话题，写出读者能跟着做的教程或测评。""",

        "deep_dive_prompt": """你是 AI 工具实战专家。选一个今天最值得关注的 AI 工具/模型，写一份实战测评或使用教程。

输出纯净 JSON：
{
  "title": "文章标题（10字内）",
  "content_md": "完整 Markdown 正文",
  "tg_summary": "Telegram 推送（50字内）"
}

content_md 自由结构，二选一：

如果是测评对比：
- 工具卡片：名称/网址/定价（含免费额度）/竞品/上手难度（5分制）
- 实测记录：用同一个任务在 2-3 个工具上跑一遍，记录实际结果
- 对比表：功能/价格/速度/中文支持/API可用性 五维度打分
- 3 个实际使用场景及效果量化（节省多少时间/提升多少质量）
- 优缺点清单 + 替代方案
- 性价比结论：免费够用还是建议付费？

如果是使用教程：
- 这个工具解决什么痛点（具体场景+浪费了多少时间）
- 从注册到产出第一个结果的完整流程（每步可截图）
- 进阶技巧：3 个大多数人不知道的用法
- 常见错误和排障
- 同类工具对比（至少 2 个替代品）

硬性要求：
- 所有工具必须国内可注册（或明确标注需要特殊网络环境+给出替代方案）
- 对比数据必须具体（秒数/字数/评分）
- 必须有"谁适合用/谁不适合用"判断
- 免费额度必须实测验证（不要照搬官网描述，标注"未实测"如无法验证）"""
    },

    # ====================================================================
    # 引擎 3: Cross-Border-Insights — 海外信息差变现
    # ====================================================================
    "Cross-Border-Insights": {
        "title_cn": "海外信息差",
        "emoji": "🌍",
        "feeds": [
            "https://www.reddit.com/r/Entrepreneur/top/.rss?t=day",
            "https://www.reddit.com/r/juststart/top/.rss?t=day",
            "https://restofworld.org/feed/",
            "https://www.theguardian.com/world/rss",
            "https://www.semafor.com/feed/technology/rss",
            "https://pragmaticengineer.com/feed",
            "https://stratechery.com/feed/",
            "https://lennysnewsletter.com/feed",
            "https://review.firstround.com/feed.xml",
            "https://www.producthunt.com/feed",
            "https://news.ycombinator.com/rss",
        ],
        "briefing_prompt": """你是海外信息差猎人。从资料库提炼今天 3-5 条海外独有、国内认识不足的信息差机会。

聚焦：国外有但国内没有的产品模式 / 价格差 / 认知差 / 工具差

输出 JSON：
{
  "briefing": {
    "title": "当日快讯标题（10字内）",
    "items": [
      {
        "title": "信息标题",
        "source": "来源平台名+国家",
        "one_liner": "一句话说清国外的什么在国内是空白（30字内）",
        "why_matters": "为什么你能吃到这个信息差（50字内，说清搬运/模仿/代理的可行性）",
        "zero_cost_angle": "零成本验证方式（40字内，如：去XX平台搜XX看有没有人在做）"
      }
    ],
    "tg_brief": "Telegram 推送用（200字内，编号列表）"
  },
  "deep_dive": null
}

优先选择有国内可行性或可模仿的角度，写出具体操作方案。""",

        "deep_dive_prompt": """你是海外信息差变现教练。选一个海外有但国内几乎空白的机会，写一份搬运/模仿/本地化方案。

输出纯净 JSON：
{
  "title": "文章标题（10字内）",
  "content_md": "完整 Markdown 正文",
  "tg_summary": "Telegram 推送（50字内）"
}

content_md 自由结构，必须包含：

源头还原：
- 什么产品/模式/服务？哪个国家/平台？谁在做？什么数据？（收入/用户量/增长）
- 为什么在海外成立？（文化/支付/物流/习惯，2-3 个真实原因）
- 为什么国内没人做/做不好？（是真壁垒还是信息差？区分清楚）

搬运路径（核心）：
- 最小搬运方案：如果不是照搬而是适配，改哪 3 个点就够了？
- Day1-3 验证清单：每天 1 个验证动作（搜索/联系/发布/统计）
- 工具和平台：推荐用的平台（微信/小红书/闲鱼/抖音选一深讲）+ 注册步骤

变现路径：至少 2 种，每种标注启动成本 + 预期时间线

风险提示：政策/平台规则/竞争 3 方面

硬性要求：
- 必须区分"真壁垒"（资质/资金/技术）和"伪壁垒"（认知/信息/语言）
- 所有验证动作必须零成本
- 如果该机会需要>5000元启动资金则放弃，另选话题"""
    },

    # ====================================================================
    # 引擎 4: Macro-Events — 宏观风向标（仅快讯，不做深度长文）
    # ====================================================================
    "Macro-Events": {
        "title_cn": "宏观风向标",
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
        "briefing_prompt": """你是宏观信息筛选官。从资料库提炼今天 3-5 条对普通人最有切身影响的全球科技/经济事件。

聚焦：裁员/政策变化/平台规则变动/汇率/工具被封/新市场开放——直接影响普通人钱袋子的事

输出 JSON：
{
  "briefing": {
    "title": "当日快讯标题（10字内）",
    "items": [
      {
        "title": "信息标题",
        "source": "来源平台名",
        "one_liner": "一句话说清发生了什么事（30字内）",
        "why_matters": "对你的直接影响（50字内，说清影响谁/影响什么/什么时候）",
        "zero_cost_angle": "应对行动（40字内，具体动作而非建议，如：今天去XX平台更新XX设置）"
      }
    ],
    "tg_brief": "Telegram 推送用（200字内，编号列表）"
  },
  "deep_dive": null
}

本引擎不生成深度长文。deep_dive 字段永远填 null。
宁缺毋滥——没有对个人有直接影响的事件就少写，不要凑数。""",

        "deep_dive_prompt": "NO_DEEP_DIVE"  # 明确标记不生成深度长文
    },

    # ====================================================================
    # 引擎 5: China-Going-Global — 出海工具链实操
    # ====================================================================
    "China-Going-Global": {
        "title_cn": "出海工具链",
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
        "briefing_prompt": """你是出海工具链研究员。从资料库提炼今天 3-5 条出海实操相关的信息。

不关注"XX公司融资XX亿"——关注"你可以用什么工具/渠道/方法出海"。

输出 JSON：
{
  "briefing": {
    "title": "当日快讯标题（10字内）",
    "items": [
      {
        "title": "信息标题",
        "source": "来源平台名+目标市场",
        "one_liner": "一句话说清什么工具/方法/渠道（30字内）",
        "why_matters": "为什么个人开发者/小团队能用（50字内，含成本+门槛评估）",
        "zero_cost_angle": "立即尝试的第一步（40字内，如：去XX平台用XX邮箱注册，选择XX计划）"
      }
    ],
    "tg_brief": "Telegram 推送用（200字内，编号列表）"
  },
  "deep_dive": null
}

优先选择有实操价值的出海工具或平台，写出详细上手指南。""",

        "deep_dive_prompt": """你是出海实操教练。写一份具体的出海工具/平台使用指南，让完全没出过海的人能跟着做。

输出纯净 JSON：
{
  "title": "文章标题（10字内）",
  "content_md": "完整 Markdown 正文",
  "tg_summary": "Telegram 推送（50字内）"
}

content_md 自由结构，必须包含：

目标市场画像（200字）：
- 为什么选这个市场/平台？（数据支撑：用户量/客单价/竞争度）
- 适合卖什么？（3 个具体品类/服务举例）

从零到上线的每一步：
- Step 1：注册（用什么证件/邮箱/支付方式？截图步骤）
- Step 2：配置（设置什么？常见的坑？）
- Step 3：上架/发布（审核要求？时效？被拒的常见原因？）
- Step 4：接单/收款（用什么收款？回款周期？手续费？）

工具链推荐：至少 3 个必备工具（名称+费用+用途+替代品）

避坑清单：这个平台最常见的 3 个导致封号/失败的原因

成本拆解：启动成本 + 月度运营成本 + 预期回本周期

硬性要求：
- 必须具体到一个平台（如 Gumroad/Etsy/Shopee/Amazon FBA/TikTok Shop 选一）
- 注册步骤必须是实际可操作的（不要写"完成注册"——要写"上传身份证正反面JPG,<2MB"）
- 所有费用标注币种和具体金额
- 如果该平台不支持中国用户直接注册，标注替代方案"""
    },

    # ====================================================================
    # 引擎 6: Developer-Goldmine — 效率工具与自动化
    # ====================================================================
    "Developer-Goldmine": {
        "title_cn": "效率工具与自动化",
        "emoji": "⛏️",
        "feeds": [
            "https://news.ycombinator.com/rss",
            "https://www.reddit.com/r/programming/top/.rss?t=day",
            "https://www.reddit.com/r/webdev/top/.rss?t=day",
            "https://www.producthunt.com/feed",
            "https://github.com/trending.atom",
            "https://www.technologyreview.com/feed/",
            "https://www.infoworld.com/index.rss",
            "https://feed.indiehackers.com/forum/rss",
            "https://dev.to/feed/tag/ai",
        ],
        "briefing_prompt": """你是效率工具猎人。从资料库提炼今天 3-5 条能帮普通人提升效率的信息。

关注：新工具发布、自动化方案、免费替代品、AI 辅助开发、工作流优化

输出 JSON：
{
  "briefing": {
    "title": "当日快讯标题（10字内）",
    "items": [
      {
        "title": "信息标题",
        "source": "来源平台名",
        "one_liner": "一句话说清这个工具/方法能做什么（30字内）",
        "why_matters": "为什么值得花时间尝试（50字内，含效率提升量化）",
        "zero_cost_angle": "立即体验：下载/打开/注册XX→试XX功能（40字内）"
      }
    ],
    "tg_brief": "Telegram 推送用（200字内，编号列表）"
  },
  "deep_dive": null
}

优先选择有教学价值的工具或方案，写出读者能快速上手的指南。""",

        "deep_dive_prompt": """你是效率黑客。选一个今天最值得教的高效工具/自动化方案，写一份详细的上手指南。

输出纯净 JSON：
{
  "title": "文章标题（10字内）",
  "content_md": "完整 Markdown 正文",
  "tg_summary": "Telegram 推送（50字内）"
}

content_md 自由结构，必须包含：

效率痛点（100字）：
- 什么场景？谁在浪费时间？（具体：每天花XX分钟做XX重复操作）
- 不用这个工具/方案的代价（一个月浪费多少小时）

自动化/提效方案：
- 工具链架构（用什么+怎么串联）
- 从安装到首次运行的完整步骤（每步具体到命令/操作）
- 核心配置代码（如有，必须可运行+注释关键行）

效果量化：
- 优化前：花 XX 分钟/次 × XX 次/天 = XX 小时/月
- 优化后：花 XX 分钟/次 × XX 次/天 = XX 小时/月
- 节省：XX 小时/月 = 如果用来接外包值 XX 元

进阶技巧：3 个大多数人不知道的用法

常见排障：3 个最容易遇到的问题及解决方法

硬性要求：
- 所有工具必须有免费方案
- 代码必须可运行（含依赖安装步骤）
- 适用于 Windows/macOS 双平台（或标注仅支持某平台）
- 如果该工具需要付费才能用核心功能，标注替代免费方案"""
    }
}


# ============================================================
# RAG 检索层
# ============================================================
def auto_search_context(query):
    """全网主动检索补充深度背景"""
    try:
        print(f"   🔍 正在全网主动检索: {query[:60]}...")
        results = DDGS().text(query, max_results=20)
        context = ""
        for r in results:
            context += f"-[外网检索] {r['title']}: {r['body']}\n"
        return context
    except Exception as e:
        print(f"   ⚠️ 检索失败，退回纯 RSS 模式: {e}")
        return ""


def auto_search_pain_points(query):
    """从负面信号角度检索——搜索抱怨、替代品、对比"""
    try:
        pain_queries = [
            f"{query} complaints frustrated",
            f"{query} alternative vs",
        ]
        context = ""
        for pq in pain_queries:
            results = DDGS().text(pq, max_results=10)
            for r in results:
                context += f"-[痛点挖掘] {r['title']}: {r['body']}\n"
        return context
    except Exception:
        return ""


_FEED_CACHE = {}  # URL → (timestamp, parsed_feed)
_FEED_CACHE_LOCK = threading.Lock()

_FEED_OK = 0
_FEED_FAIL = 0

def _fetch_one_feed(url):
    """抓取单个 RSS feed，带缓存去重（线程安全）"""
    global _FEED_OK, _FEED_FAIL
    with _FEED_CACHE_LOCK:
        if url in _FEED_CACHE:
            ts, cached = _FEED_CACHE[url]
            if time.time() - ts < 300:
                return cached
    feed = feedparser.parse(url)
    if feed.bozo and not feed.entries:
        try:
            resp = requests.get(url, timeout=15, headers={"User-Agent": "EastonRadar/1.0"})
            feed = feedparser.parse(resp.content)
        except Exception:
            pass
    if not feed.entries:
        with _FEED_CACHE_LOCK:
            _FEED_FAIL += 1
        return []
    with _FEED_CACHE_LOCK:
        _FEED_OK += 1
    entries = []
    for entry in feed.entries:
        desc = ""
        if hasattr(entry, 'description') and entry.description:
            desc = re.sub('<[^<]+>', '', entry.description)
        elif hasattr(entry, 'summary') and entry.summary:
            desc = re.sub('<[^<]+>', '', entry.summary)
        link = getattr(entry, 'link', '')
        entries.append(f"标题: {entry.title}\n来源: {link}\n摘要: {desc}")
    with _FEED_CACHE_LOCK:
        _FEED_CACHE[url] = (time.time(), entries)
    return entries


def fetch_and_augment(feeds):
    """并行抓取 RSS + 多话题全网主动搜索 + 痛点挖掘"""
    raw_articles = []
    all_titles = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_fetch_one_feed, feeds))

    for entries in results:
        for text in entries:
            raw_articles.append(text)
            m = re.search(r'标题:\s*(.+)', text)
            if m:
                title = m.group(1).strip()[:80]
                if title and title not in all_titles:
                    all_titles.append(title)

    base_context = "\n".join(raw_articles)

    # 对前 8 个最具代表性的标题做深度全网检索
    target_titles = all_titles[:8]
    deep_context = ""
    pain_context = ""

    if target_titles:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            futures = {}
            for i, t in enumerate(target_titles):
                futures[pool.submit(auto_search_context, t)] = ("bg", t)
                if i > 0 and i % 3 == 0:
                    time.sleep(0.5)  # 每 3 个标题稍息避免触发 DDG 频率限制
                futures[pool.submit(auto_search_pain_points, t)] = ("pain", t)
                try:
                    futures[pool.submit(
                        lambda q=t: "\n".join(
                            f"-[中国市场关联] {r['title']}: {r['body']}"
                            for r in DDGS().text(f"{q} 中国 替代 市场", max_results=5)
                        )
                    )] = ("cn", t)
                except Exception:
                    pass

            for future in concurrent.futures.as_completed(futures):
                tag, topic = futures[future]
                try:
                    text = future.result() or ""
                except Exception:
                    text = ""
                if not text:
                    continue
                if tag == "bg":
                    deep_context += f"\n\n【话题: {topic}】\n{text}"
                elif tag == "pain":
                    pain_context += f"\n\n【话题: {topic}】\n{text}"
                elif tag == "cn":
                    pain_context += f"\n\n【中国视角: {topic}】\n{text}"

    parts = [base_context]
    if deep_context:
        parts.append("\n\n========== 深度全网检索扩充资料 ==========\n" + deep_context)
    if pain_context:
        parts.append("\n\n========== 负面信号 & 中国视角检索 ==========\n" + pain_context)
    return "".join(parts)


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
                wrapped = '{' + wrapped + '}'
                last_brace = wrapped.rfind('}')
                wrapped = wrapped[:last_brace + 1]
                candidates.append(wrapped)

    # 通用修复函数
    def _repair(raw):
        """逐步修复常见 LLM JSON 格式错误（启发式，不保证处理嵌套字符串）"""
        raw = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', raw)              # 非法转义（\_ \* \p 等）→ 双写反斜杠字面量
        raw = re.sub(r',\s*([}\]])', r'\1', raw)                         # 尾随逗号
        raw = re.sub(r'(^|[{\[,:\s\n])([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', raw)  # 无引号键
        raw = re.sub(r"'([^']*)':", r'"\1":', raw)                     # 单引号键
        raw = re.sub(r":\s*'([^']*)'", r': "\1"', raw)                 # 单引号值
        raw = raw.replace('“', '"').replace('”', '"')        # 中文双引号
        raw = raw.replace('‘', "'").replace('’', "'")        # 中文单引号
        raw = re.sub(r'"\s*\n\s*"', '", "', raw)                       # 两个相邻字符串中间缺逗号
        raw = re.sub(r'([}\]\d])\s*\n\s*"', r'\1,\n"', raw)            # }/]/数字后换行接字符串缺逗号
        raw = re.sub(r'([}\]"\d])\s*\n\s*\{', r'\1,\n{', raw)          # }/]/"/数字后换行接对象缺逗号
        raw = re.sub(r'"\s+(")', r'", \1', raw)                         # 同行两个字符串中间缺逗号
        return raw

    # 对每个候选尝试解析，优先返回含 briefing+deep_dive 的有效 JSON
    errors = []
    for cand in reversed(candidates):
        for attempt in range(4):
            try:
                obj = json.loads(cand)
            except json.JSONDecodeError as e:
                if attempt == 0:
                    cand = _repair(cand)
                    continue
                elif attempt == 1:
                    cand = re.sub(r'\n\s*', ' ', cand)
                    continue
                elif attempt == 2:
                    cand = _repair(cand)
                    continue
                else:
                    errors.append(str(e))
                    break
            else:
                if isinstance(obj, dict) and "briefing" in obj:
                    return obj
                # 模型输出了有效 JSON 但缺少 briefing 键，尝试结构修复
                if isinstance(obj, dict):
                    wraps = []
                    if "items" in obj:
                        # briefing 对象缺外层 {"briefing": ...}
                        wraps.append({"briefing": obj, "deep_dive": None})
                    # 单条新闻条目 → 包裹为 items 列表
                    wraps.append({"briefing": {"items": [obj]}, "deep_dive": None})
                    for w in wraps:
                        w_json = json.dumps(w, ensure_ascii=False)
                        try:
                            w_obj = json.loads(w_json)
                            if isinstance(w_obj, dict) and "briefing" in w_obj:
                                return w_obj
                        except json.JSONDecodeError:
                            pass
                errors.append(f"跳过(缺briefing键): {list(obj.keys())[:3]}")
                break

    raise ValueError(f"JSON 提取失败: {'; '.join(errors[-3:])}")


def deep_dive_worker(category_name, config):
    print(f"[{category_name}] 抓取 {len(config['feeds'])} 个信息源...", flush=True)
    t0 = time.time()
    context = fetch_and_augment(config['feeds'])
    t1 = time.time()
    entry_count = context.count("标题:")
    print(f"[{category_name}] 获取 {entry_count} 条摘要 ({t1-t0:.0f}s)", flush=True)

    if entry_count == 0:
        print(f"[{category_name}] 无有效数据，跳过 DeepSeek 调用", flush=True)
        return category_name, None

    print(f"[{category_name}] 唤醒 DeepSeek...", flush=True)

    # 去重：读取近 3 天已覆盖话题，避免选题重复
    recent = get_recent_titles(category_name, days=3)
    dedup_hint = ""
    if recent:
        dedup_hint = f"\n\n【去重提醒】以下话题已在近 3 天内覆盖过。优先选择不同角度或新话题；如果确有重大更新或完全不同的切入点，仍然可以生成。\n" + \
                     "\n".join(f"- {t}" for t in recent[:20])

    # 判断该引擎是否支持 deep_dive
    deep_dive_prompt = config.get('deep_dive_prompt', '')
    has_deep_dive = bool(deep_dive_prompt and deep_dive_prompt != "NO_DEEP_DIVE")

    if has_deep_dive:
        deep_dive_section = f"""
【深度长文任务——仅在资料库有足够操作价值时生成】
{deep_dive_prompt}
"""
        deep_dive_instruction = "如果你找到了一个真正可操作、读者看完就能动手的话题，就放心生成 1 篇深度长文。每个引擎独立决策，不需要考虑其他引擎。宁可少而精。"
    else:
        deep_dive_section = ""
        deep_dive_instruction = "本引擎不生成深度长文。deep_dive 字段必须填 null。"

    if has_deep_dive:
        deep_dive_schema = """
      "deep_dive": {
        "title": "深度长文标题（≤10中文字）",
        "tg_summary": "一句话概述（≤50字）",
        "content_md": "Markdown 正文（实操指南，含成本/时间/收益标注）"
      }"""
    else:
        deep_dive_schema = """
      "deep_dive": null"""

    full_prompt = f"""
当前时间是 {bj_now().strftime("%Y年%m月%d日")}。
请根据资料库内容，生成"快讯汇总（briefing）"（必填）。

【快讯任务】
{config['briefing_prompt']}
{deep_dive_section}

你的输出**必须**严格遵循以下 JSON Schema，只输出一个 JSON 对象（不加 ```json 代码块外壳）：

    {{
      "briefing": {{
        "title": "快讯标题（≤10中文字）",
        "tg_brief": "Telegram 摘要（≤200字）",
        "items": [
          {{"title": "条目标题", "source": "来源", "one_liner": "一句话摘要", "why_matters": "为什么重要", "zero_cost_angle": "零成本切入点"}}
        ]
      }},{deep_dive_schema}
    }}

硬性约束（违反导致 JSON 解析失败即视为无效输出）：
- 所有 title 字段严格不超过 10 个中文字
- 全文零 emoji，零网络用语，拒绝 AI 套话和空洞排比
- 深度长文必须是实操指南而非行业分析——读者看完能跟着做
- 所有方案标注启动成本（元）、时间投入（小时）、预期收益（元）
- 代码必须可运行，工具必须免费或国内可访问（或标注替代方案）
- 不要"趋势展望""影响分析""关注XX"——要"打开XX→做XX→得到XX"
- tg_summary 不超过 50 字，tg_brief 不超过 200 字
"""

    # 深度长文指令放在资料库之前，作为模型读数据前的最后提醒
    user_content = full_prompt + dedup_hint + f"\n\n【资料库】\n{context}"
    if has_deep_dive:
        user_content += f"\n\n🚨 最后提醒 — {deep_dive_instruction}"

    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }

    payload = {
        "model": "deepseek-chat",
        "max_tokens": 8192,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
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
        print(f"❌ [{category_name}] DeepSeek 推理失败: {e}", flush=True)
        return category_name, None


# ============================================================
# Hugo 落盘
# ============================================================
def _write_hugo_post(dir_name, file_name, title, categories, tags, body):
    """写入 Hugo Markdown 文件，返回文件路径"""
    posts_dir = os.path.join("content", "posts", dir_name)
    os.makedirs(posts_dir, exist_ok=True)
    file_path = os.path.join(posts_dir, file_name)
    fm = f"---\ntitle: '{title}'\ndate: {bj_now().strftime('%Y-%m-%dT%H:%M:%S%z')}\n"
    fm += f"categories: {json.dumps(categories)}\ntags: {json.dumps(tags)}\n"
    fm += f"draft: false\n---\n\n"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(fm + body)
    return file_path


def save_deep_dive(category_name, config, data):
    """落盘单篇深度长文"""
    deep_dive = data.get("deep_dive")
    if not (deep_dive and deep_dive.get("title") and deep_dive.get("content_md")):
        print(f"   ⏭️ [{category_name}] 今日无值得深度长文的话题，跳过")
        return None

    now = bj_now()
    date_slug = now.strftime("%Y-%m-%d")
    time_slug = now.strftime("%H%M")
    cat_lower = category_name.lower()
    file_path = _write_hugo_post(
        category_name, f"deep-dive-{date_slug}-{time_slug}.md",
        deep_dive['title'], [cat_lower], ["深度长文"],
        deep_dive['content_md']
    )
    print(f"   📄 深度长文已落盘: {file_path}")
    return file_path


def save_aggregated_briefing(briefings_by_cat):
    """聚合所有引擎的快讯为一篇，按 topic 分组"""
    if not briefings_by_cat:
        return None

    now = bj_now()
    date_slug = now.strftime("%Y-%m-%d")
    posts_dir = os.path.join("content", "posts", "daily-briefing")
    os.makedirs(posts_dir, exist_ok=True)

    file_name = os.path.join(posts_dir, f"briefing-{date_slug}.md")
    md = f"---\n"
    md += f"title: '每日快讯'\n"
    md += f"date: {now.strftime('%Y-%m-%dT%H:%M:%S%z')}\n"
    md += f"categories: ['daily-briefing']\n"
    md += f"tags: ['快讯', '每日汇总']\n"
    md += f"draft: false\n"
    md += "---\n\n"
    md += f"> {now.strftime('%Y年%m月%d日')} · {sum(len(v) for v in briefings_by_cat.values())} 条情报\n\n"

    for cat_name, items in briefings_by_cat.items():
        config = AGENTS.get(cat_name, {})
        md += f"## {config.get('title_cn', cat_name)}\n\n"
        for item in items:
            md += f"### {item.get('title', '无标题')}\n\n"
            md += f"**来源**：{item.get('source', '未知')} | {item.get('one_liner', '')}\n\n"
            why = item.get('why_matters', '')
            if why:
                md += f"{why}\n\n"
            za = item.get('zero_cost_angle', '')
            if za and za not in ('暂无可执行角度', '待观察', '持续关注'):
                md += f"> 🎯 {za}\n\n"
        md += "---\n\n"

    with open(file_name, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"   📋 聚合快讯已落盘: {file_name}")
    return file_name


# ============================================================
# Telegram 推送
# ============================================================
def _tg_post(category_name, msg, thread_id=None):
    """发送单条 Telegram 消息到指定 Topic"""
    try:
        chat_id_int = int(TG_CHAT_ID.strip())
    except ValueError:
        chat_id_int = TG_CHAT_ID.strip()

    payload = {"chat_id": chat_id_int, "text": msg, "parse_mode": "Markdown",
                "disable_web_page_preview": False}
    if thread_id is None:
        thread_id = THREAD_IDS.get(category_name)
    if thread_id and str(thread_id).strip():
        payload["message_thread_id"] = int(str(thread_id).strip())

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


def send_aggregated_briefing_tg(briefings_by_cat):
    """推送聚合快讯到 Telegram 独立 Topic"""
    total_items = sum(len(v) for v in briefings_by_cat.values())
    if total_items == 0:
        return 0

    msg = f"📋 **每日快讯**\n"
    msg += f"{bj_now().strftime('%Y.%m.%d')} | {total_items} 条情报\n"
    msg += "━━━━━━━━━━━━━━\n\n"

    for cat_name, items in briefings_by_cat.items():
        config = AGENTS.get(cat_name, {})
        msg += f"**▸ {config.get('title_cn', cat_name)}**\n"
        for item in items:
            title = item.get('title', '')
            source = item.get('source', '')
            one_liner = item.get('one_liner', '')
            msg += f"  · {title} ({source})\n"
            if one_liner:
                msg += f"    {one_liner}\n"
        msg += "\n"

    msg += "━━━━━━━━━━━━━━\n"
    msg += f"详情: {SITE_URL}"
    return 1 if _tg_post("_briefing", msg, thread_id=BRIEFING_THREAD) else 0


def send_deep_dive_tg(category_name, data):
    """推送单篇深度长文到其 Topic"""
    deep_dive = data.get("deep_dive")
    if not (deep_dive and deep_dive.get("title") and deep_dive.get("content_md")):
        return 0

    title_cn = AGENTS.get(category_name, {}).get("title_cn", category_name)
    msg = f"**[{title_cn}] 深度长文**\n\n"
    msg += f"**{deep_dive['title']}**\n\n"
    msg += f"{deep_dive.get('tg_summary', '深度长文已发布')}\n\n"
    msg += f"阅读全文: {SITE_URL}/categories/{category_name.lower()}/"
    return 1 if _tg_post(category_name, msg) else 0


# ============================================================
# 主流程
# ============================================================
if __name__ == "__main__":
    print(f"🚀 启动 Easton 满血外脑 v2")
    print(f"   🎯 目标读者：被AI冲击的普通人（28-38岁/技术背景/现金流紧/零成本启动）")
    print(f"   📡 RSS 源: {sum(len(c['feeds']) for c in AGENTS.values())}")
    print(f"   🤖 模型: DeepSeek V4 Pro (deepseek-chat)")
    print(f"   📝 深度长文: 仅 5 引擎产出（宏观风向标仅快讯）")
    print()

    # 收集所有引擎结果
    all_briefings = {}  # category_name → [items]
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
                    briefing = result.get("briefing")
                    if briefing:
                        items = briefing.get("items", [])
                        if items:
                            all_briefings[category_name] = items
                            print(f"   📋 [{category_name}] 快讯 {len(items)} 条")

                    saved = save_deep_dive(category_name, AGENTS[category_name], result)
                    if saved:
                        total_deep_dives += 1

                    total_tg += send_deep_dive_tg(category_name, result)
                else:
                    print(f"   ⚠️ [{cat}] 未获取有效结果")
            except Exception as exc:
                print(f"❌ {cat} 引擎崩溃: {exc}")

    # 聚合所有快讯为一篇
    total_briefings = 1 if all_briefings else 0
    if all_briefings:
        save_aggregated_briefing(all_briefings)
        total_tg += send_aggregated_briefing_tg(all_briefings)

    print()
    print(f"🏁 执行完毕。")
    print(f"   📊 聚合快讯: {total_briefings} | 深度长文: {total_deep_dives} | TG推送: {total_tg}")
    print(f"   📡 Feed: {_FEED_OK} 成功 / {_FEED_FAIL} 失败")
