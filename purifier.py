import os
import json
import feedparser
import requests
import re
from datetime import datetime

# 1. 加载环境变量
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
TG_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 2. 顶级优质信息源库
RSS_FEEDS = {
    "Hacker News": "https://news.ycombinator.com/rss",
    "TechCrunch": "https://techcrunch.com/feed/",
    "IndieHackers": "https://feed.indiehackers.com/forum/rss",
    "Reddit SaaS": "https://www.reddit.com/r/SaaS/top/.rss?t=day"
}

def fetch_all_feeds():
    """抓取全球前沿源"""
    articles = []
    for source, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:4]:
                description = entry.description if hasattr(entry, 'description') else ""
                clean_desc = re.sub('<[^<]+>', '', description)[:200]
                articles.append(f"[{source}] 标题: {entry.title}\n链接: {entry.link}\n摘要: {clean_desc}")
        except Exception as e:
            print(f"抓取 {source} 失败: {e}")
    return "\n\n".join(articles)

def analyze_with_deepseek(content):
    """调用大模型进行深度推理"""
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }
    
    today = datetime.now().strftime("%Y年%m月%d日")
    prompt = f"""
    当前时间是 {today}。你是我（Easton Hua，全栈开发者）的首席战略官。请阅读以下资讯：
    {content}
    
    请严格输出 JSON 格式，包含一个 'deep_dives' 数组。挑选 2 个最具利用【海外信息差】套利的方向。
    每个元素包含：'title', 'macro_context', 'arbitrage_logic', 'china_mapping', 'mvp_action_plan'。
    """
    
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个只输出标准 JSON 格式的战略分析 AI。"},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.6
    }
    
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    raw_json = response.json()['choices'][0]['message']['content']
    clean_json = re.sub(r'^```json\n|```$', '', raw_json.strip(), flags=re.MULTILINE)
    return json.loads(clean_json)

def save_to_hugo(deep_dives):
    """直接写入本地文件系统，交由 Hugo 渲染"""
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    hugo_date = now.strftime('%Y-%m-%dT%H:%M:%S%z') # Hugo 需要的严格时间格式
    
    # 强制确保目录存在，防止任何路径报错
    os.makedirs(os.path.join("content", "posts"), exist_ok=True)
    file_name = os.path.join("content", "posts", f"arbitrage-deep-dive-{today_str}.md")
    
    # 注入 Hugo 的 YAML Frontmatter
    md_content = f"---\n"
    md_content += f"title: '全球极客商业智库与套利沙盘 ({today_str})'\n"
    md_content += f"date: {hugo_date}\n"
    md_content += f"draft: false\n"
    md_content += f"---\n\n"
    md_content += f"> **战略定调**：本文档由 AI 针对全球最新极客趋势进行深度解构，为 Easton Hua 提供自动化增收与零库存套利的战略支持。\n\n---\n\n"
    
    for idx, item in enumerate(deep_dives):
        md_content += f"## {idx+1}. {item['title']}\n\n"
        md_content += f"### 🌍 宏观背景与海外趋势\n{item['macro_context']}\n\n"
        md_content += f"### 💡 商业套利底层逻辑\n{item['arbitrage_logic']}\n\n"
        md_content += f"### 🇨🇳 极客本土化映射\n{item['china_mapping']}\n\n"
        md_content += f"### ⚡ 午休期 MVP 测试方案\n{item['mvp_action_plan']}\n\n"
        md_content += "---\n\n"
        
    with open(file_name, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"✅ 成功将文章写入本地目录: {file_name}")

def send_to_telegram(deep_dives):
    """TG 导读推送保留"""
    today = datetime.now().strftime("%Y-%m-%d")
    msg = f"🚀 **Easton 个人内参已生成 ({today})**\n\n博客原文已更新在雷达站，今日探讨核心：\n\n"
    for idx, item in enumerate(deep_dives):
        msg += f"🔥 **{idx+1}. {item['title']}**\n\n"
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "Markdown"})

if __name__ == "__main__":
    raw_content = fetch_all_feeds()
    analysis_data = analyze_with_deepseek(raw_content)
    deep_dives = analysis_data.get('deep_dives', [])
    
    if deep_dives:
        save_to_hugo(deep_dives)
        send_to_telegram(deep_dives)
        print("🏁 今日流水线执行完毕：Markdown已落盘，TG推送已发送。")