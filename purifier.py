import os
import json
import feedparser
import requests

# 1. 从 GitHub Actions 环境变量中提取你的 Secrets
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
HALO_TOKEN = os.environ.get("HALO_TOKEN")

def fetch_hn_rss(limit=5):
    """极简抓取层：只拉取 Hacker News 前 5 条最新热帖"""
    url = "https://news.ycombinator.com/rss"
    feed = feedparser.parse(url)
    articles = []
    for entry in feed.entries[:limit]:
        articles.append({"title": entry.title, "link": entry.link})
    return articles

def summarize_with_deepseek(articles):
    """AI 提纯层：调用 DeepSeek 接口剥离冗余信息"""
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }
    
    # 将抓取到的标题和链接拼接给 AI
    content_to_summarize = "\n".join([f"- {a['title']} ({a['link']})" for a in articles])
    
    prompt = f"""
    你是一个硬核的极客商业分析师。请快速扫描以下来自 Hacker News 的热门帖子：
    {content_to_summarize}
    
    任务：提取出最具有商业价值、SaaS 独立开发、或技术套利的信息。
    要求：用硬核、直接的中文极客口吻输出摘要。总字数控制在 300 字左右，分点作答，直接给结论，不要废话。
    """
    
    payload = {
        "model": "deepseek-chat", # 使用 DeepSeek 核心模型
        "messages": [
            {"role": "system", "content": "你是一个高效的海外信息提纯 AI。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.5
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        return f"🚨 DeepSeek 提纯失败: {e}"

def send_to_telegram(text):
    """免持推送层：发送到你的手机 TG 客户端"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"🚀 **今日极客信息差提纯**\n\n{text}",
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
        print("✅ 成功推送到 Telegram！")
    except Exception as e:
        print(f"❌ Telegram 推送失败: {e}")

# def send_to_halo(text):
#     """沉淀层：推送至国内 Halo2 博客 (预留框架)"""
#     url = "你的_HALO_博客_API_地址/api/content/posts"
#     headers = {"Authorization": f"Bearer {HALO_TOKEN}"}
#     # ... 根据 Halo API 文档组装 JSON 并 POST
#     pass

if __name__ == "__main__":
    print("1. 开始拉取 RSS 源...")
    articles = fetch_hn_rss()
    
    print("2. 唤醒 DeepSeek 引擎进行降维提纯...")
    summary = summarize_with_deepseek(articles)
    
    print("3. 发射数据至移动终端...")
    send_to_telegram(summary)
    
    print("🏁 自动化流水线执行完毕。")
