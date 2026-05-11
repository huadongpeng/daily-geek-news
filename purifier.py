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
HALO_TOKEN = os.environ.get("HALO_TOKEN")
HALO_URL = os.environ.get("HALO_URL")

# 2. 2026 年最新顶级优质信息源库 (深度阅读向)
RSS_FEEDS = {
    "Hacker News (极客热榜)": "https://news.ycombinator.com/rss",
    "TechCrunch (创投风向)": "https://techcrunch.com/feed/",
    "Wired (宏观科技)": "https://www.wired.com/feed/rss",
    "Reddit SaaS (商业实战)": "https://www.reddit.com/r/SaaS/top/.rss?t=day",
    "MIT Tech Review AI (硬核AI)": "https://www.technologyreview.com/topic/artificial-intelligence/feed/"
}

def fetch_all_feeds():
    """抓取全球前沿源，提供给大模型进行深度阅读材料的筛选"""
    articles = []
    for source, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:4]: # 增加抓取深度
                description = entry.description if hasattr(entry, 'description') else ""
                # 剥离HTML标签，保留纯文本大意
                clean_desc = re.sub('<[^<]+>', '', description)[:200]
                articles.append(f"[{source}] 标题: {entry.title}\n链接: {entry.link}\n摘要: {clean_desc}")
        except Exception as e:
            print(f"抓取 {source} 失败: {e}")
    return "\n\n".join(articles)

def analyze_with_deepseek(content):
    """深度智库核心：调用大模型进行极其深度的商业解构"""
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }
    
    today = datetime.now().strftime("%Y年%m月%d日")
    
    prompt = f"""
    当前时间是 {today}。你是我（一位身处中国、拥有全栈开发能力、试图利用技术杠杆打破阶层和债务束缚的系统架构师）的首席战略官。
    我有充足的通勤时间和上班摸鱼时间来进行【深度阅读和商业思考】。

    请阅读以下今天抓取的海量全球顶尖科技与商业资讯：
    {content}
    
    请严格输出一个 JSON 格式，包含一个 'deep_dives' 数组。你需要从中挑选 2-3 个最具颠覆性、最能利用【中国特色供应链/平台】与【海外信息差】结合进行套利的方向。
    
    对于每一个 deep_dive，包含以下字段：
    - 'title': 深度剖析的标题
    - 'macro_context': 宏观背景与海外趋势（不少于 300 字的深度分析，这件事为什么在海外火了？）
    - 'arbitrage_logic': 商业套利底层逻辑（分析这是流量套利、信息差套利、还是服务中介？利润空间在哪？）
    - 'china_mapping': 极客本土化映射（针对微信、小红书、闲鱼等中国生态，这个模式应该如何被“换皮”或“微调”？）
    - 'mvp_action_plan': 【核心要求】为我量身定制的午休期 MVP（最小可行性产品）技术测试方案。比如：我今天该写一段什么样的 Python/Node.js 爬虫？用什么工具拼装 API？步骤必须极其硬核、可落地执行。
    """
    
    payload = {
        "model": "deepseek-chat", # 使用 DeepSeek 进行深度逻辑推理
        "messages": [
            {"role": "system", "content": "你是一个只输出标准 JSON 格式的战略分析与跨国套利 AI。不要输出多余的解释，直接输出 JSON。"},
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

def generate_markdown(deep_dives):
    """将 JSON 组装成极具深度排版的 Markdown 长文"""
    today = datetime.now().strftime("%Y-%m-%d")
    md_text = f"# 🌐 跨国信息差深度智库 | {today}\n\n"
    md_text += "> **战略定调**：本文档由 AI 针对全球最新极客与商业趋势进行深度解构。旨在为中国全栈开发者提供自动化增收与零库存套利的战略支持。\n\n---\n\n"
    
    for idx, item in enumerate(deep_dives):
        md_text += f"## {idx+1}. {item['title']}\n\n"
        md_text += f"### 🌍 宏观背景与海外趋势\n{item['macro_context']}\n\n"
        md_text += f"### 💡 商业套利底层逻辑\n{item['arbitrage_logic']}\n\n"
        md_text += f"### 🇨🇳 极客本土化映射 (中国生态)\n{item['china_mapping']}\n\n"
        md_text += f"### ⚡ 午休期 MVP 技术测试方案\n{item['mvp_action_plan']}\n\n"
        md_text += "---\n\n"
    return md_text

def send_to_telegram(deep_dives):
    """Telegram 端推送大纲与深度导读"""
    today = datetime.now().strftime("%Y-%m-%d")
    msg = f"🚀 **{today} 深度认知内参已生成**\n\n"
    msg += "建议利用通勤时间深入阅读博客原文。今日战略探讨核心：\n\n"
    
    for idx, item in enumerate(deep_dives):
        msg += f"🔥 **{idx+1}. {item['title']}**\n"
        # 截取 MVP 前几句话作为钩子
        hook = item['mvp_action_plan'][:80] + "..."
        msg += f"📌 **执行线索**: {hook}\n\n"
        
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    
    try:
        requests.post(url, json=payload)
        print("✅ Telegram 导读推送成功！")
    except Exception as e:
        print(f"❌ Telegram 推送失败: {e}")

def send_to_halo(markdown_content):
    """Halo 端：长文资产沉淀，采用标准 CRD API 发送"""
    if not HALO_TOKEN or not HALO_URL:
        print("⚠️ 未配置 Halo 环境变量 (HALO_TOKEN 或 HALO_URL)，跳过博客发布。")
        return
        
    # 【修复1】切换到 Halo 2.x 更底层的 Content API，专为自动化设计
    endpoint = f"{HALO_URL.rstrip('/')}/apis/content.halo.run/v1alpha1/posts"
    headers = {
        "Authorization": f"Bearer {HALO_TOKEN}",
        "Content-Type": "application/json"
    }
    
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 【修复2】剥离外层的 "post" 字典，将 apiVersion 和 kind 直接顶格暴露 (K8s 规范)
    payload = {
        "apiVersion": "content.halo.run/v1alpha1",
        "kind": "Post",
        "metadata": {
            "generateName": "post-" # 必须保留，交由系统生成唯一后缀
        },
        "spec": {
            "title": f"全球极客商业智库与套利沙盘 ({today})",
            "slug": f"arbitrage-deep-dive-{today}",
            "baseSnapshot": {
                "raw": markdown_content,
                "isAutoSave": False
            },
            "owner": "hdop",  # ⚠️ 最后一次提醒：必须是你 Halo 后台的纯英文登录名
            "publish": False   # 先存为草稿，供你午休时预览排版
        }
    }
    
    try:
        res = requests.post(endpoint, headers=headers, json=payload)
        res.raise_for_status()
        print("✅ 成功沉淀万字分析长文至 Halo 博客草稿箱！")
    except requests.exceptions.RequestException as e:
        print(f"❌ Halo 发布失败，HTTP 状态码: {e.response.status_code if e.response else 'Unknown'}")
        print(f"❌ 详细错误信息: {e.response.text if e.response else e}")

if __name__ == "__main__":
    print("1. 正在从 2026 顶级信息源池化前沿资讯...")
    raw_content = fetch_all_feeds()
    
    print("2. 唤醒 DeepSeek 开启长上下文深度推理...")
    try:
        analysis_data = analyze_with_deepseek(raw_content)
        deep_dives = analysis_data.get('deep_dives', [])
        
        if not deep_dives:
            print("⚠️ 大模型未返回有效的深度分析内容。")
        else:
            print("3. 生成深度 Markdown 文档...")
            full_markdown = generate_markdown(deep_dives)
            
            print("4. 发送高能导读至移动终端 (Telegram)...")
            send_to_telegram(deep_dives)
            
            print("5. 沉淀万字深度解析至博客 (Halo)...")
            send_to_halo(full_markdown)
            
            print("🏁 今日流水线执行完毕，祝你在深度思考中发现新机会。")
    except Exception as e:
        print(f"🚨 系统流水线崩溃: {e}")
