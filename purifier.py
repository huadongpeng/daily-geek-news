import os
import json
import feedparser
import requests
import re
from datetime import datetime
import concurrent.futures
from duckduckgo_search import DDGS # 引入免费且免梯子的搜索引擎

# 1. 环境变量加载
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
TG_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

THREAD_IDS = {
    "Arbitrage-Radar": os.environ.get("TG_THREAD_ARBITRAGE"),
    "AI-Frontier": os.environ.get("TG_THREAD_AI"),
    "Cross-Border-Insights": os.environ.get("TG_THREAD_CROSS"),
    "Macro-Events": os.environ.get("TG_THREAD_MACRO")
}

# 2. 四大引擎独立配置
AGENTS = {
    "Arbitrage-Radar": {
        "title_cn": "零库存套利雷达",
        "emoji": "💰",
        "feeds": [
            "https://www.reddit.com/r/SaaS/top/.rss?t=day",
            "https://www.reddit.com/r/SideProject/top/.rss?t=day",
            "https://www.reddit.com/r/juststart/top/.rss?t=day",
            "https://feed.indiehackers.com/forum/rss"
        ],
        "prompt": """你是一位年收入 50 万美元的独立开发者兼商业架构师。请从资料库中挑选一个最有商业价值的话题，创作一篇可执行的深度拆解文章。

输出结构（严格按以下章节，Markdown 格式）：
## 一、商业模型白盒拆解
- 用具体数据还原该模式的收入逻辑、成本结构、利润公式
- 列出 2-3 个真实案例（注明来源，附收入/用户量数据）

## 二、中国市场本土化映射
- 分析在微信/小红书/闲鱼/拼多多/抖音生态中的对等机会
- 指出至少 2 个具体的套利切入点（信息差/平台差/汇率差）

## 三、MVP 落地执行方案（核心章节，至少 500 字）
- 提供可直接运行的 Python 代码片段（至少 30 行，含关键注释）
- 列出 Day 1 / Day 2 / Day 3 分步执行清单，每步可 30 分钟内完成

## 四、风险与天花板
- 诚实评估该模式的 3 大风险和退出策略
- 预估该项目 3 个月后的收入天花板

要求：每个观点必须有数据或案例支撑，代码必须可运行，拒绝空洞概念。"""
    },
    "AI-Frontier": {
        "title_cn": "AI 生产力前沿",
        "emoji": "🤖",
        "feeds": [
            "https://news.ycombinator.com/rss",
            "https://www.technologyreview.com/feed/",
            "http://arxiv.org/rss/cs.AI"
        ],
        "prompt": """你是顶级 AI 架构师和全栈工程师。请从资料库中挑选一个最具突破性的 AI 工具、模型或技术，创作一篇硬核深度分析。

输出结构（严格按以下章节，Markdown 格式）：
## 一、技术原理白盒拆解
- 用通俗语言 + 技术细节双轨解释核心原理（附架构图思维描述）
- 与同类方案做性能/成本对比表（至少 3 个维度）

## 二、替代人工的量化分析
- 具体列出可被替代的 3-5 种人工操作场景
- 每个场景给出时间/成本节省的量化估算（美元或小时）

## 三、Easton 实战接入方案（核心章节，至少 500 字）
- 提供完整的 Python 接入代码（至少 40 行，含错误处理和日志）
- 标注 API 关键参数、费用预估、常见坑点和排错方法

## 四、未来 3 个月演进预测
- 该技术路线的下一步方向和潜在颠覆点
- 给出 Easton 现在就应该布局的具体准备动作

要求：代码必须可运行、可复现，技术解释必须有深度但不过度学术化，拒绝营销话术和 PR 稿风格。"""
    },
    "Cross-Border-Insights": {
        "title_cn": "跨国商业脑洞",
        "emoji": "🌍",
        "feeds": [
            "https://www.reddit.com/r/Entrepreneur/top/.rss?t=day",
            "https://www.wired.com/feed/rss",
            "https://restofworld.org/feed/"
        ],
        "prompt": """你是跨国商业战略顾问，专注于中国与海外市场的信息差套利。请从资料库中找到一个在国外已验证但中国市场几乎空白的商业模式，撰写一篇本土化落地方案。

输出结构（严格按以下章节，Markdown 格式）：
## 一、海外模式全景还原
- 该模式在国外的起源、关键玩家、融资/收入/用户规模数据
- 至少 2 个标杆案例的深度拆解（商业模式画布 + 关键指标）

## 二、中国缺席的底层原因（核心分析章节）
- 从文化习惯、监管环境、支付体系、物流基建、用户心智 5 个维度逐一分析
- 明确区分：哪些是真实壁垒，哪些是信息差造成的伪壁垒

## 三、本土化降维打击方案
- 设计一个适配中国市场的变体模式（画出信息流/资金流）
- 列出具体执行步骤和关键资源需求
- 提供微信小程序 / 小红书 / 抖音的冷启动策略（选一个平台深讲）

## 四、套利窗口期与风险预案
- 预估该机会的时间窗口（6 个月 / 1 年 / 3 年）
- 列出最大的 3 个风险和具体应对预案

要求：必须有具体的市场数据和公司案例，拒绝"感觉式"分析。每个结论要有逻辑推理链条。"""
    },
    "Macro-Events": {
        "title_cn": "宏观局势风向标",
        "emoji": "📉",
        "feeds": [
            "https://techcrunch.com/feed/",
            "https://www.theverge.com/rss/index.xml",
            "https://feeds.arstechnica.com/arstechnica/index"
        ],
        "prompt": """你是宏观对冲基金策略师，专为独立开发者和中小创业者提供决策情报。请从资料库中挑选一个对独立开发者影响最大的全球科技/经济事件，撰写一份可行动的决策报告。

输出结构（严格按以下章节，Markdown 格式）：
## 一、事件本质与噪音剥离
- 用 3 句话概括事件核心（剥离媒体标题党和 PR 话术）
- 标注 3-5 个关键时间节点，形成事件时间线

## 二、巨头博弈棋局（核心分析章节）
- 揭示该事件背后至少 2 方参与者的真实战略意图（谁进攻/谁防守）
- 用博弈论视角分析各方的最优策略和可能的均衡结果
- 标注资金、人才的流向变化

## 三、独立开发者冲击链
- 从融资环境、获客成本、技术栈选择、出海窗口 4 个维度分析传导路径
- 给出 3-5 个预警信号清单（出现任一信号应立即调整策略）

## 四、Easton 3 个月风险对冲行动清单
- 第 1 个月：立即执行的 3 个防御动作
- 第 2 个月：可以布局的 2 个进攻机会
- 第 3 个月：复盘指标和调整节点

要求：必须引用具体数据、公司名称和事件时间线。每个结论必须有推理链条。拒绝新闻摘抄和泛泛而谈。"""
    }
}

def auto_search_context(query):
    """【新功能】主动出击：调用 DuckDuckGo 搜索补充深度背景"""
    try:
        print(f"   🔍 正在全网主动检索深度背景: {query}...")
        results = DDGS().text(query, max_results=5)
        context = ""
        for r in results:
            context += f"-[外网检索] {r['title']}: {r['body']}\n"
        return context
    except Exception as e:
        print(f"   ⚠️ 检索失败，退回纯 RSS 模式: {e}")
        return ""

def fetch_and_augment(feeds):
    """抓取 RSS 并触发主动搜索"""
    raw_articles = []
    top_title = ""
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                desc = re.sub('<[^<]+>', '', entry.description if hasattr(entry, 'description') else "")[:200]
                raw_articles.append(f"标题: {entry.title}\n摘要: {desc}")
                if not top_title: top_title = entry.title # 拿最火的一条去外网深度搜索
        except Exception:
            continue
            
    base_context = "\n".join(raw_articles)
    deep_context = auto_search_context(top_title) if top_title else ""
    return base_context + "\n\n【主动全网检索扩充资料】:\n" + deep_context

def deep_dive_worker(category_name, config):
    print(f"[{category_name}] 数据就绪，唤醒 DeepSeek V4 Pro 深度思考引擎...")
    context = fetch_and_augment(config['feeds'])
    
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }
    
    full_prompt = f"""
    当前时间是 {datetime.now().strftime("%Y年%m月%d日")}，请基于资料库创作一篇深度长文。
    {config['prompt']}

    你的输出必须是纯净的 JSON 对象，千万不要加 ```json 代码块外壳。必须包含以下字段：
    - "title": 文章标题（吸引眼球但不过度标题党，15 字以内）
    - "content_md": 深度长文正文（严格 Markdown，按上述章节结构，层层递进，核心章节不少于 500 字）
    - "tg_summary": 用于 Telegram 的精简推送（严格 50 字以内，包含一个核心数据点，结尾用一个动词引导行动）
    """
    
    payload = {
        "model": "deepseek-chat",  # DeepSeek V4 Pro，最新旗舰模型
        "messages": [
            {"role": "system", "content": "你是一个严格输出标准 JSON 格式的战略分析机。"},
            {"role": "user", "content": full_prompt + "\n\n【资料库】\n" + context}
        ]
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=300)  # 深度思考 + 联网搜索，放宽至300秒
        response.raise_for_status()
        
        # 返回包含思维链 (reasoning_content) 和最终结果 (content)
        final_text = response.json()['choices'][0]['message']['content']
        
        # 强力洗脱 Markdown 标记，提取纯 JSON
        json_match = re.search(r'\{.*\}', final_text, re.DOTALL)
        if json_match:
            return category_name, json.loads(json_match.group(0))
        else:
            raise ValueError("大模型未返回有效的 JSON 结构")
            
    except Exception as e:
        print(f"[{category_name}] V4 Pro 推理失败: {e}")
        return category_name, None

def save_to_hugo(category_name, config, data):
    """落盘至 Hugo"""
    now = datetime.now()
    hugo_date = now.strftime('%Y-%m-%dT%H:%M:%S%z')
    date_slug = now.strftime("%Y-%m-%d")
    
    os.makedirs(os.path.join("content", "posts", category_name), exist_ok=True)
    file_name = os.path.join("content", "posts", category_name, f"deep-dive-{date_slug}.md")
    cat_lower = category_name.lower()
    
    md = f"---\n"
    md += f"title: '{config['emoji']} {data['title']}'\n"
    md += f"date: {hugo_date}\n"
    md += f"categories: ['{cat_lower}']\n"
    md += f"draft: false\n"
    md += f"---\n\n"
    md += data['content_md']
    
    with open(file_name, "w", encoding="utf-8") as f:
        f.write(md)

def send_to_telegram(category_name, config, data):
    """推送到 Telegram 群组指定 Topic"""
    msg = f"{config['emoji']} **[{config['title_cn']}]**\n\n"
    msg += f"🔥 **{data['title']}**\n\n"
    msg += f"🧠 {data['tg_summary']}"

    chat_id = TG_CHAT_ID.strip()
    # 确保 chat_id 为正确的数字格式（群组 ID 以 -100 开头）
    try:
        chat_id_int = int(chat_id)
    except ValueError:
        chat_id_int = chat_id

    payload = {"chat_id": chat_id_int, "text": msg, "parse_mode": "Markdown"}

    thread_id = THREAD_IDS.get(category_name)
    if thread_id and thread_id.strip():
        payload["message_thread_id"] = int(thread_id.strip())
        print(f"   📨 推送到群组 {chat_id} → Topic {thread_id.strip()}")
    else:
        print(f"   ⚠️ [{category_name}] 未配置 Topic ID，消息将发送到群组主聊天")

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            print(f"   ✅ [{category_name}] Telegram 推送成功")
        else:
            print(f"   ❌ [{category_name}] Telegram 推送失败: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"   ❌ [{category_name}] Telegram 推送异常: {e}")

if __name__ == "__main__":
    print("🚀 启动 Easton 满血外脑：RAG主动检索 + V4 Pro深度推理 + 联网搜索并发引擎...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_category = {executor.submit(deep_dive_worker, cat, conf): cat for cat, conf in AGENTS.items()}
        for future in concurrent.futures.as_completed(future_to_category):
            cat = future_to_category[future]
            try:
                category_name, result = future.result()
                if result:
                    save_to_hugo(category_name, AGENTS[category_name], result)
                    send_to_telegram(category_name, AGENTS[category_name], result)
            except Exception as exc:
                print(f"❌ {cat} 引擎崩溃: {exc}")
                
    print("🏁 今日流水线执行完毕。")
