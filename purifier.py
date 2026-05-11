import os
import json
import feedparser
import requests
import re
from datetime import datetime
import concurrent.futures

# 1. 环境变量加载
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
TG_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
# 如果你在 TG 开启了 Topics，可以在环境变量里配置对应的 Thread ID，目前默认发到主频道
# TG_THREAD_ARBITRAGE = os.environ.get("TG_THREAD_ARBITRAGE", "") 

# 2. 四大引擎的独立配置 (数据源 + 专家 Prompt)
AGENTS = {
    "Arbitrage-Radar": {
        "title_cn": "零库存套利雷达",
        "emoji": "💰",
        "feeds": [
            "https://www.reddit.com/r/SaaS/top/.rss?t=day",
            "https://feed.indiehackers.com/forum/rss"
        ],
        "prompt": """你是一位年入千万的硅谷黑客增长专家。请深度阅读以下最新资讯。
挑选出 1 个最具有'低成本、零库存、自动化'套利潜力的项目或商业模式。
输出深度长文：
1. 拆解其底层搞钱逻辑（流量从哪来？凭什么收费？）。
2. 分析其在中国的平替或时间差套利空间。
3. 为 Easton（精通全栈的独立开发者）写一份详尽的、能在本周末跑通的 MVP 代码/业务落地测试清单。"""
    },
    
    "AI-Frontier": {
        "title_cn": "AI 生产力前沿",
        "emoji": "🤖",
        "feeds": [
            "https://news.ycombinator.com/rss", # 提取 HN 中的 AI 趋势
            "https://www.technologyreview.com/topic/artificial-intelligence/feed/"
        ],
        "prompt": """你是一位顶级的 AI 架构师。请从以下资讯中挑选 1 个最具突破性的 AI 模型、API 工具或自动化 Agent 工作流。
输出深度长文：
1. 用极客视角的底层硬核原理解释这个技术突破。
2. 它能如何替代目前繁琐的人工操作？
3. Easton（全栈开发者）应该如何通过 Python 或 Node.js 接入该技术来提升自己每天的研发效率或构建新的 SaaS？"""
    },
    
    "Cross-Border-Insights": {
        "title_cn": "跨国商业脑洞",
        "emoji": "🌍",
        "feeds": [
            "https://www.reddit.com/r/Entrepreneur/top/.rss?t=day",
            "https://www.wired.com/feed/rss"
        ],
        "prompt": """你是一位深谙中美商业文化差异的战略观察家。请挑选 1 个国外极其火爆、脑洞大开，但在国内鲜为人知的商业实践或现象。
输出深度长文：
1. 深度还原这个商业脑洞的兴起背景。
2. 国内外行情的根本差异在哪里？为什么国内没人做？
3. Easton 能否利用信息差，在小红书、闲鱼或微信生态做一个降维打击的本土化版本？"""
    },
    
    "Macro-Events": {
        "title_cn": "宏观局势风向标",
        "emoji": "📉",
        "feeds": [
            "https://techcrunch.com/feed/"
        ],
        "prompt": """你是一位冷酷的全球宏观对冲基金经理。请从资讯中挑选 1 个可能对全球科技产业链、经济周期或互联网格局产生重大影响的事件。
输出深度长文：
1. 剥离媒体噪音，直击事件背后的真实资金流向或大厂战略意图。
2. 这件事对底层的独立开发者或小微创业者是利好还是毁灭性打击？
3. Easton 在未来 3-6 个月内应该采取什么风险对冲动作？"""
    }
}

def fetch_category_feeds(feeds):
    """提取单个分类下的 RSS 资讯"""
    articles = []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]: # 增加上下文深度
                desc = re.sub('<[^<]+>', '', entry.description if hasattr(entry, 'description') else "")[:300]
                articles.append(f"标题: {entry.title}\n链接: {entry.link}\n摘要: {desc}")
        except Exception:
            pass
    return "\n\n".join(articles)

def deep_dive_worker(category_name, config):
    """【核心】单线程工作节点：抓取 -> 深度思考 -> 结构化返回"""
    print(f"[{category_name}] 正在池化数据并启动 DeepSeek 推理专线...")
    raw_content = fetch_category_feeds(config['feeds'])
    
    if not raw_content.strip():
        return category_name, None

    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }
    
    full_prompt = f"""
    当前时间是 {datetime.now().strftime("%Y年%m月%d日")}。
    {config['prompt']}
    
    请严格输出 JSON 格式，包含：
    - 'title': 文章标题（极客风，引人入胜）
    - 'content_md': 深度长文的正文（纯 Markdown 格式，至少 800 字，按你角色要求的分点详细展开，包含代码思路或深入分析）
    - 'tg_summary': 用于 Telegram 推送的 100 字极简导读。
    """
    
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个严格输出标准 JSON 格式的资深商业与技术极客。"},
            {"role": "user", "content": full_prompt + "\n\n资料库：\n" + raw_content}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.7 # 稍微调高温度，获取更有创造力的深度思考
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        raw_json = response.json()['choices'][0]['message']['content']
        clean_json = re.sub(r'^```json\n|```$', '', raw_json.strip(), flags=re.MULTILINE)
        return category_name, json.loads(clean_json)
    except Exception as e:
        print(f"[{category_name}] 推理失败: {e}")
        return category_name, None

def save_to_hugo(category_name, config, data):
    """将单篇深度长文落盘为独立的 Hugo Markdown 文件"""
    now = datetime.now()
    hugo_date = now.strftime('%Y-%m-%dT%H:%M:%S%z')
    date_slug = now.strftime("%Y-%m-%d")
    
    os.makedirs(os.path.join("content", "posts", category_name), exist_ok=True)
    file_name = os.path.join("content", "posts", category_name, f"deep-dive-{date_slug}.md")
    
    md = f"---\n"
    md += f"title: '{config['emoji']} {data['title']}'\n"
    md += f"date: {hugo_date}\n"
    md += f"categories: ['{category_name}']\n" # 自动打上 Hugo 标签
    md += f"draft: false\n"
    md += f"---\n\n"
    md += data['content_md']
    
    with open(file_name, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"✅ {category_name} 深度文章已生成: {file_name}")

def send_to_telegram(category_name, config, data):
    """向 Telegram 发送独立的导读卡片"""
    msg = f"{config['emoji']} **[{config['title_cn']}]**\n\n"
    msg += f"🔥 **{data['title']}**\n\n"
    msg += f"🧠 **核心导读**: {data['tg_summary']}\n\n"
    msg += f"🌐 详情请移步雷达站深度阅读。"
    
    payload = {
        "chat_id": TG_CHAT_ID, 
        "text": msg, 
        "parse_mode": "Markdown"
    }
    # 如果配置了 thread_id，就定向发送到特定 Topic
    # thread_id = os.environ.get(f"TG_THREAD_{category_name.replace('-', '_').upper()}")
    # if thread_id: payload["message_thread_id"] = thread_id
        
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    requests.post(url, json=payload)

if __name__ == "__main__":
    print("🚀 启动 Easton 多线程并发智库引擎...")
    
    # 核心：使用多线程并发执行四大领域的深度拉取与推理
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
                
    print("🏁 今日全领域深度流水线执行完毕。数据已落盘，随时准备触发 Hugo 编译。")
