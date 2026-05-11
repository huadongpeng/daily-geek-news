import os
import json
import feedparser
import requests
import subprocess
import re

# 1. 加载环境变量
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
TG_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
HALO_TOKEN = os.environ.get("HALO_TOKEN")
HALO_URL = os.environ.get("HALO_URL")

# 2. 扩充抓取源 (Map)
RSS_FEEDS = {
    "Hacker News": "https://news.ycombinator.com/rss",
    "Reddit SaaS": "https://www.reddit.com/r/SaaS/top/.rss?t=day",
    "IndieHackers": "https://feed.indiehackers.com/forum/rss"
}

def fetch_all_feeds():
    """抓取多个海外前沿源，池化信息"""
    articles = []
    for source, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]: # 每个源取前 3 条最热
                articles.append(f"[{source}] {entry.title} ({entry.link})")
        except Exception as e:
            print(f"抓取 {source} 失败: {e}")
    return "\n".join(articles)

def analyze_with_deepseek(content):
    """核心大脑：JSON 结构化输出与跨国套利分析"""
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }
    
    prompt = f"""
    你是我（一位身处中国、背负债务的全栈开发者）的首席情报官。请阅读以下今日海外高赞前沿资讯：
    {content}
    
    任务与输出格式：
    请严格输出 JSON 格式，包含 'telegram_msg' (限300字纯文本，用于通勤语音播报) 和 'halo_article' (Markdown格式的长文) 两个字段。
    
    分析要求：
    1. 剔除无效噪音，挑选出最有商业价值的 3-5 条情报。
    2. 在 'halo_article' 中，每一条情报必须附带【🌍 跨国时间差套利分析】模块。
    3. 结合中国环境，回答：这个海外的现成想法/工具，我能否用代码快速“汉化”或“微调”？国内是否存在对应的痛点？我能否利用国内供应链配合海外需求做到零库存套利？
    """
    
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个只输出标准 JSON 格式的跨国商业分析 AI。"},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"} # 强制 DeepSeek 输出 JSON
    }
    
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    raw_json = response.json()['choices'][0]['message']['content']
    
    # 清理可能存在的 Markdown 代码块标记
    clean_json = re.sub(r'^```json\n|```$', '', raw_json.strip(), flags=re.MULTILINE)
    return json.loads(clean_json)

def generate_audio(text):
    """利用 Edge-TTS 生成通勤语音"""
    output_file = "commute_brief.mp3"
    # 使用微软云希的声音，适合播报新闻
    cmd = ["edge-tts", "--text", text, "--voice", "zh-CN-YunxiNeural", "--write-media", output_file]
    subprocess.run(cmd)
    return output_file

def send_to_telegram(text, audio_file):
    """免持推送层：发送文本和 MP3 到 TG"""
    # 发送文本
    text_url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    requests.post(text_url, json={"chat_id": TG_CHAT_ID, "text": f"🚀 今日海外信息差套利简报\n\n{text}"})
    
    # 发送语音文件
    if os.path.exists(audio_file):
        audio_url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendAudio"
        with open(audio_file, 'rb') as audio:
            requests.post(audio_url, data={"chat_id": TG_CHAT_ID}, files={"audio": audio})
        print("✅ Telegram 语音推送成功！")

def send_to_halo(markdown_content):
    """资产沉淀层：推送至 Halo 2.x 博客"""
    if not HALO_TOKEN or not HALO_URL:
        print("未配置 Halo 参数，跳过博客发布。")
        return
        
    # Halo 2.x 的基础发布 API (需根据你的 Halo 实际版本微调)
    endpoint = f"{HALO_URL.rstrip('/')}/apis/api.console.halo.run/v1alpha1/posts"
    headers = {
        "Authorization": f"Bearer {HALO_TOKEN}",
        "Content-Type": "application/json"
    }
    
    import datetime
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    
    payload = {
        "post": {
            "spec": {
                "title": f"全球极客前沿与跨国套利雷达 ({today})",
                "slug": f"arbitrage-radar-{today}",
                "baseSnapshot": {"raw": markdown_content},
                "owner": "你的用户名" # 注意替换为你在 Halo 的实际用户名
            },
            "apiVersion": "content.halo.run/v1alpha1",
            "kind": "Post"
        }
    }
    
    try:
        res = requests.post(endpoint, headers=headers, json=payload)
        res.raise_for_status()
        print("✅ 成功沉淀至 Halo 博客！")
    except Exception as e:
        print(f"❌ Halo 发布失败: {e}")

if __name__ == "__main__":
    print("1. 正在从海外池化前沿资讯...")
    raw_content = fetch_all_feeds()
    
    print("2. 唤醒 DeepSeek 进行降维解析与套利分析...")
    analysis_data = analyze_with_deepseek(raw_content)
    
    print("3. 生成通勤语音文件...")
    audio_path = generate_audio(analysis_data['telegram_msg'])
    
    print("4. 发射数据至移动终端 (Telegram)...")
    send_to_telegram(analysis_data['telegram_msg'], audio_path)
    
    print("5. 沉淀深度分析至博客 (Halo)...")
    send_to_halo(analysis_data['halo_article'])
    
    print("🏁 今日流水线执行完毕，祝你在 4 小时通勤中有所收获。")
