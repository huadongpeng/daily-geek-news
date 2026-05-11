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
        "feeds": ["https://www.reddit.com/r/SaaS/top/.rss?t=day", "https://feed.indiehackers.com/forum/rss"],
        "prompt": "你是一位顶级商业架构师。请拆解一个低成本、零库存的自动化套利项目。必须包含：底层逻辑、中国市场映射（如微信/小红书/闲鱼）、以及一份具体的 Easton 午休期 MVP 落地代码测试方案。"
    },
    "AI-Frontier": {
        "title_cn": "AI 生产力前沿",
        "emoji": "🤖",
        "feeds": ["https://news.ycombinator.com/rss"],
        "prompt": "你是顶级 AI 架构师。请分析一个最新突破性的 AI 工具或 Agent 工作流。必须包含：硬核原理解释、能替代哪些人工操作、以及 Easton 如何用 Python 接入该技术的实战指南。"
    },
    "Cross-Border-Insights": {
        "title_cn": "跨国商业脑洞",
        "emoji": "🌍",
        "feeds": ["https://www.reddit.com/r/Entrepreneur/top/.rss?t=day", "https://www.wired.com/feed/rss"],
        "prompt": "你是跨国商业观察家。请深挖一个国外火爆但国内少见的商业脑洞。必须包含：背景还原、为什么国内没有（文化/生态差异）、Easton 如何在国内做本土化降维打击套利。"
    },
    "Macro-Events": {
        "title_cn": "宏观局势风向标",
        "emoji": "📉",
        "feeds": ["https://techcrunch.com/feed/"],
        "prompt": "你是宏观对冲基金经理。请分析一个重大全球科技或经济事件。必须包含：剥离噪音的巨头战略/资金流向真相、对底层独立开发者的冲击分析、Easton 未来3个月的风险对冲动作。"
    }
}

def auto_search_context(query):
    """【新功能】主动出击：调用 DuckDuckGo 搜索补充深度背景"""
    try:
        print(f"   🔍 正在全网主动检索深度背景: {query}...")
        results = DDGS().text(query, max_results=3)
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
    print(f"[{category_name}] 数据就绪，唤醒 DeepSeek-Reasoner (R1) 进行深度思考...")
    context = fetch_and_augment(config['feeds'])
    
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }
    
    full_prompt = f"""
    当前时间是 {datetime.now().strftime("%Y年%m月%d日")}。
    {config['prompt']}
    
    你的输出必须是纯净的 JSON 对象，千万不要加 ```json 代码块外壳。必须包含以下字段：
    - "title": 文章标题
    - "content_md": 深度长文正文（严格 Markdown，层层递进，必须包含代码思路或深入分析）
    - "tg_summary": 用于 Telegram 的 100 字一句话极简导读。
    """
    
    payload = {
        "model": "deepseek-reasoner", # 启用最强的 R1 推理模型
        "messages": [
            {"role": "system", "content": "你是一个严格输出标准 JSON 格式的战略分析机。"},
            {"role": "user", "content": full_prompt + "\n\n【资料库】\n" + context}
        ]
        # 注意：DeepSeek-Reasoner 有时不支持 response_format，我们依靠强力 Prompt 和正则解析
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=200) # R1 思考需要时间，放宽至200秒
        response.raise_for_status()
        
        # DeepSeek-Reasoner 的返回包含思维过程 (reasoning_content) 和 最终结果 (content)
        final_text = response.json()['choices'][0]['message']['content']
        
        # 强力洗脱 Markdown 标记，提取纯 JSON
        json_match = re.search(r'\{.*\}', final_text, re.DOTALL)
        if json_match:
            return category_name, json.loads(json_match.group(0))
        else:
            raise ValueError("大模型未返回有效的 JSON 结构")
            
    except Exception as e:
        print(f"[{category_name}] R1 推理失败: {e}")
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
    """投递到特定的 Topic 房间"""
    msg = f"{config['emoji']} **[{config['title_cn']}]**\n\n"
    msg += f"🔥 **{data['title']}**\n\n"
    msg += f"🧠 **深度思考引擎导读**: {data['tg_summary']}\n\n"
    msg += f"🌐 详情已同步至 Easton 雷达站。"
    
    payload = {"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    
    # 投递至特定房间
    thread_id = THREAD_IDS.get(category_name)
    if thread_id:
        payload["message_thread_id"] = int(thread_id)
        
    url = f"[https://api.telegram.org/bot](https://api.telegram.org/bot){TG_BOT_TOKEN}/sendMessage"
    requests.post(url, json=payload)

if __name__ == "__main__":
    print("🚀 启动 Easton 满血外脑：RAG主动检索 + R1 深度推理并发引擎...")
    
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
