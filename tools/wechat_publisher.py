"""
微信公众号草稿箱发布工具 + 国内大模型封面图生成（双引擎：通义万相 + 智谱 CogView）

部署位置：腾讯云服务器（与 GitLab Docker 同机）
触发方式：crontab 定时任务（推荐 07:00 执行）
依赖安装：pip3 install -r tools/requirements_wechat.txt -i https://mirrors.aliyun.com/pypi/simple/

环境变量（在 tools/.env 中设置）：
  WECHAT_APPID          — 公众号 AppID
  WECHAT_APPSECRET      — 公众号 AppSecret
  WECHAT_AUTHOR         — 作者名
  DASHSCOPE_API_KEY     — 阿里百炼 API Key（通义万相, 免费 200 张/月）
  ZHIPU_API_KEY         — 智谱 API Key（CogView 备选, 免费 100 张/月）
  GIT_REPO_DIR          — 仓库路径（默认 /ws/web/daily-geek-news）

使用方法：
  python3 tools/wechat_publisher.py                       # 仅精品深度长文（推荐）
  python3 tools/wechat_publisher.py --include-briefings   # 包含每日快讯
  python3 tools/wechat_publisher.py --date 2026-05-12     # 指定日期
  python3 tools/wechat_publisher.py --dry-run             # 预览不实际推送
  python3 tools/wechat_publisher.py --no-image            # 跳过生图

每日流程：
  06:00 GitHub Actions → purifier.py 生成文章 → 推送 GitHub + GitLab
  07:00 crontab → git pull（从本地 GitLab） → 本脚本 → 公众号草稿箱
"""
import os
import sys
import json
import time
import argparse
import requests
from datetime import datetime
from pathlib import Path

# ============================================================
# 配置
# ============================================================
WECHAT_APPID = os.environ.get("WECHAT_APPID")
WECHAT_APPSECRET = os.environ.get("WECHAT_APPSECRET")
WECHAT_AUTHOR = os.environ.get("WECHAT_AUTHOR", "Easton Hua")
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY")
ZHIPU_API_KEY = os.environ.get("ZHIPU_API_KEY")
GIT_REPO_DIR = Path(os.environ.get("GIT_REPO_DIR", "/ws/web/daily-geek-news"))
CONTENT_DIR = GIT_REPO_DIR / "content" / "posts"
STATIC_COVERS_DIR = GIT_REPO_DIR / "static" / "images" / "covers"
SITE_URL = "https://radar.huadongpeng.com"

WECHAT_DIGEST_MAX = 120
COVER_SIZE = "1024*1024"
WANX_MODEL = "wanx2.0-t2i-turbo"  # 通义万相极速版, 0.04 元/张, 免费 200 张/月

# 引擎 emoji 映射
EMOJI_MAP = {
    "Arbitrage-Radar": "💰",
    "AI-Frontier": "🤖",
    "Cross-Border-Insights": "🌍",
    "Macro-Events": "📉",
}

# 引擎中文名映射
TITLE_MAP = {
    "Arbitrage-Radar": "零库存套利雷达",
    "AI-Frontier": "AI 生产力前沿",
    "Cross-Border-Insights": "跨国商业脑洞",
    "Macro-Events": "宏观局势风向标",
}


# ============================================================
# 微信 API
# ============================================================
def get_access_token():
    """获取微信公众号 access_token，有效期 2 小时，建议缓存"""
    url = "https://api.weixin.qq.com/cgi-bin/token"
    resp = requests.get(url, params={
        "grant_type": "client_credential",
        "appid": WECHAT_APPID,
        "secret": WECHAT_APPSECRET,
    }, timeout=10)
    data = resp.json()
    if "access_token" in data:
        return data["access_token"]
    raise RuntimeError(f"获取 access_token 失败: {data}")


def upload_image(token, image_path):
    """上传图片到公众号素材库，返回 media_id"""
    url = "https://api.weixin.qq.com/cgi-bin/material/add_material"
    with open(image_path, "rb") as f:
        resp = requests.post(url, params={
            "access_token": token,
            "type": "image",
        }, files={"media": (os.path.basename(image_path), f, "image/png")}, timeout=30)
    data = resp.json()
    if "media_id" in data:
        print(f"   🖼️ 封面图上传成功, media_id: {data['media_id']}")
        return data["media_id"]
    raise RuntimeError(f"上传封面图失败: {data}")


def add_draft(token, article):
    """将文章存入公众号草稿箱

    article 字段：
      - title: 标题（必填, ≤64 字）
      - author: 作者（可选）
      - digest: 摘要（可选, ≤120 字）
      - content: HTML 正文（必填, 支持部分 HTML 标签）
      - content_source_url: 原文链接（可选）
      - thumb_media_id: 封面图 media_id（必填）
      - need_open_comment: 是否打开评论 (0/1)
    """
    url = "https://api.weixin.qq.com/cgi-bin/draft/add"
    payload = {"articles": [article]}
    resp = requests.post(url, params={"access_token": token}, json=payload, timeout=15)
    data = resp.json()
    if "media_id" in data:
        print(f"   ✅ 草稿创建成功, draft_media_id: {data['media_id']}")
        return data["media_id"]
    raise RuntimeError(f"创建草稿失败: {data}")


# ============================================================
# 封面图生成 —— 双引擎：通义万相（主）+ 智谱 CogView（备）
# ============================================================
def _build_cover_prompt(title, category_name):
    emoji = EMOJI_MAP.get(category_name, "📰")
    cat_title = TITLE_MAP.get(category_name, category_name)
    return (
        f"微信公众号封面图，科技商业风格，主题：{title}。"
        f"简洁现代设计，适合{cat_title}类文章。"
        f"深色背景配亮色几何图形点缀，专业极简风格，"
        f"不要出现文字，不要出现人物面孔，16:9 比例，高清"
    )


def generate_cover_wanx(prompt):
    """通义万相（阿里百炼）—— 免费 200 张/月"""
    if not DASHSCOPE_API_KEY:
        return None
    url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
    headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json",
               "X-DashScope-Async": "enable"}
    payload = {"model": WANX_MODEL, "input": {"prompt": prompt}, "parameters": {"size": COVER_SIZE, "n": 1}}

    print(f"   🎨 通义万相 生图中...")
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    task_data = resp.json()
    task_id = task_data.get("output", {}).get("task_id")
    if not task_id:
        print(f"   ⚠️ 通义万相提交失败: {task_data}")
        return None

    task_url = f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
    for _ in range(12):
        time.sleep(5)
        status = requests.get(task_url, headers=headers, timeout=10).json()
        ts = status.get("output", {}).get("task_status")
        if ts == "SUCCEEDED":
            return status["output"]["results"][0]["url"]
        elif ts == "FAILED":
            print(f"   ⚠️ 通义万相失败: {status}")
            return None
        print(f"   ⏳ {ts}...")
    print(f"   ⚠️ 通义万相超时")
    return None


def generate_cover_zhipu(prompt):
    """智谱 CogView-3 — 免费 100 张/月，备选引擎"""
    if not ZHIPU_API_KEY:
        return None
    url = "https://open.bigmodel.cn/api/paas/v4/images/generations"
    headers = {"Authorization": f"Bearer {ZHIPU_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "cogview-3", "prompt": prompt, "size": COVER_SIZE}

    print(f"   🎨 智谱 CogView 生图中...")
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        data = resp.json()
        if "data" in data and len(data["data"]) > 0:
            return data["data"][0]["url"]
        print(f"   ⚠️ 智谱 CogView 失败: {data}")
        return None
    except Exception as e:
        print(f"   ⚠️ 智谱 CogView 异常: {e}")
        return None


def generate_cover_image(title, category_name, date_slug=""):
    """双引擎封面图生成 + 保存到 static/ 供网站使用"""
    prompt = _build_cover_prompt(title, category_name)

    # 引擎 1: 通义万相（主）
    image_url = generate_cover_wanx(prompt)
    engine = "wanx"

    # 引擎 2: 智谱 CogView（备）
    if not image_url:
        image_url = generate_cover_zhipu(prompt)
        engine = "cogview"

    if not image_url:
        print(f"   ⚠️ 所有生图引擎均失败，请检查 API Key 和额度")
        return None, None

    print(f"   🎨 [{engine}] 封面图生成成功，下载中...")
    img_resp = requests.get(image_url, timeout=30)

    # 保存到 tools/covers/（用于公众号上传）
    local_dir = GIT_REPO_DIR / "tools" / "covers"
    local_dir.mkdir(parents=True, exist_ok=True)
    cat_slug = category_name.lower().replace(" ", "-")
    local_path = local_dir / f"cover_{cat_slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    with open(local_path, "wb") as f:
        f.write(img_resp.content)
    print(f"   🖼️ 封面图已保存: {local_path}")

    # 同步保存到 static/images/covers/（Hugo 直接引用，按分类+日期命名避免覆盖）
    static_dir = STATIC_COVERS_DIR
    static_dir.mkdir(parents=True, exist_ok=True)
    static_name = f"{date_slug}_{cat_slug}_{engine}.png" if date_slug else f"{cat_slug}_{datetime.now().strftime('%Y%m%d')}_{engine}.png"
    static_path = static_dir / static_name
    with open(static_path, "wb") as f:
        f.write(img_resp.content)
    static_url = f"{SITE_URL}/images/covers/{static_name}"
    print(f"   🌐 网站可用: {static_url}")

    return str(local_path), static_url


# ============================================================
# Markdown → 微信公众号 HTML（支持有限的标签子集）
# ============================================================
def md_to_wechat_html(md_text, article_url=""):
    """将 Markdown 转换为微信公众号兼容的 HTML

    微信支持的标签：section, p, br, strong, em, h1-h6,
    ul, ol, li, blockquote, pre, code, a, img, table 系列
    """
    import re

    html = md_text

    # 转义已有 HTML 实体（防止破坏）
    # 代码块先保护起来
    code_blocks = {}
    code_idx = 0

    def protect_code(m):
        nonlocal code_idx
        lang = m.group(1) or ""
        code = m.group(2)
        placeholder = f"__CODE_BLOCK_{code_idx}__"
        # 微信代码块：用 pre > code 包裹，内联样式
        escaped_code = (code
                        .replace("&", "&amp;")
                        .replace("<", "&lt;")
                        .replace(">", "&gt;")
                        .replace('"', "&quot;"))
        code_blocks[placeholder] = (
            f'<pre style="background:#282c34;color:#abb2bf;padding:16px;'
            f'border-radius:6px;overflow-x:auto;font-size:14px;line-height:1.6;">'
            f'<code>{escaped_code}</code></pre>'
        )
        code_idx += 1
        return placeholder

    # 保护行内代码
    inline_codes = {}

    def protect_inline(m):
        nonlocal code_idx
        code = m.group(1)
        placeholder = f"__INLINE_CODE_{code_idx}__"
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        inline_codes[placeholder] = (
            f'<code style="background:#f0f0f0;color:#c7254e;padding:2px 6px;'
            f'border-radius:3px;font-family:monospace;font-size:14px;">{escaped}</code>'
        )
        code_idx += 1
        return placeholder

    # 保护代码块
    html = re.sub(r'```(\w*)\n(.*?)```', protect_code, html, flags=re.DOTALL)
    # 保护行内代码
    html = re.sub(r'`([^`]+)`', protect_inline, html)

    # 标题
    html = re.sub(r'^#### (.+)$', r'<h4 style="font-size:16px;margin:20px 0 10px;">\1</h4>', html, flags=re.MULTILINE)
    html = re.sub(r'^### (.+)$', r'<h3 style="font-size:18px;margin:24px 0 12px;">\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2 style="font-size:20px;margin:28px 0 14px;border-left:4px solid #1890ff;padding-left:12px;">\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^# (.+)$', r'<h1 style="font-size:22px;margin:32px 0 16px;text-align:center;">\1</h1>', html, flags=re.MULTILINE)

    # 粗体 / 斜体
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)

    # 链接
    html = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" style="color:#1890ff;">\1</a>', html)

    # 分割线
    html = re.sub(r'^---$', r'<hr style="border:none;border-top:1px solid #e8e8e8;margin:24px 0;">', html, flags=re.MULTILINE)

    # 引用
    html = re.sub(
        r'^> (.+)$',
        r'<blockquote style="border-left:3px solid #ddd;padding:8px 16px;color:#666;background:#f9f9f9;margin:16px 0;">\1</blockquote>',
        html, flags=re.MULTILINE
    )

    # 表格（保留 Markdown 表格的简单处理）
    # ... 表格处理较复杂，暂时保留原始格式或简单转换
    html = re.sub(r'^\|(.+)\|$', r'<p style="font-family:monospace;">\1</p>', html, flags=re.MULTILINE)

    # 无序列表
    html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
    # 有序列表
    html = re.sub(r'^\d+\. (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
    # 包装连续的 <li>
    html = re.sub(r'(<li>.*?</li>\n?)+', r'<ul style="padding-left:24px;margin:12px 0;">\g<0></ul>', html)

    # 段落（剩余的非空行）
    html = re.sub(r'^(?!<[a-z/])(.+)$', r'<p style="margin:8px 0;line-height:1.8;">\1</p>', html, flags=re.MULTILINE)

    # 恢复代码块
    for placeholder, code_html in code_blocks.items():
        html = html.replace(placeholder, code_html)
    for placeholder, code_html in inline_codes.items():
        html = html.replace(placeholder, code_html)

    # 清理多余空行
    html = re.sub(r'\n{3,}', '\n\n', html)

    # ---- 顶部品牌栏 ----
    header = (
        f'<section style="background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);'
        f'padding:20px 16px;margin-bottom:24px;border-radius:8px;text-align:center;">'
        f'<p style="color:#e0e0e0;font-size:12px;margin:0 0 6px;">'
        f'📡 Easton 跨国智库 · 每日海外情报深度解读</p>'
        f'<p style="margin:0;">'
        f'<a href="{SITE_URL}" style="color:#4fc3f7;font-size:13px;text-decoration:none;">'
        f'🌐 {SITE_URL.replace("https://", "")}</a>'
        f'</p></section>'
    )
    html = header + html

    # ---- 底部引流 + 原文链接 ----
    footer = (
        f'<hr style="border:none;border-top:1px solid #e8e8e8;margin:32px 0 16px;">'
        f'<section style="background:#f8f9fa;padding:16px;border-radius:8px;text-align:center;">'
        f'<p style="margin:0 0 8px;font-size:13px;color:#666;">'
        f'📡 本文由 DeepSeek V4 Pro 自动生成 · Easton 跨国智库</p>'
        f'<p style="margin:0 0 4px;font-size:14px;">'
        f'💰 套利雷达 · 🤖 AI 前沿 · 🌍 跨国脑洞 · 📉 宏观风向</p>'
    )
    if article_url:
        footer += (
            f'<p style="margin:8px 0 0;">'
            f'<a href="{article_url}" style="color:#1890ff;font-size:14px;text-decoration:none;font-weight:bold;">'
            f'🔗 在网站上阅读完整文章（含代码高亮和目录导航）</a></p>'
        )
    footer += (
        f'<p style="margin:8px 0 0;font-size:12px;color:#999;">'
        f'📧 hdop1993@gmail.com | 每日自动更新，欢迎收藏</p>'
        f'</section>'
    )
    html += footer

    return html


# ============================================================
# 主流程
# ============================================================
def find_articles(date_str=None):
    """在 content/posts/ 下查找今日文章"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    articles = []
    for md_file in sorted(CONTENT_DIR.rglob(f"*{date_str}*.md")):
        # 仅处理分类子目录下的文章，跳过 posts/ 根目录的旧版文件
        relative = md_file.relative_to(CONTENT_DIR)
        if len(relative.parts) < 2:
            continue
        category = relative.parts[0]
        is_briefing = "briefing" in md_file.name
        is_deep = "deep-dive" in md_file.name

        # 读取内容
        with open(md_file, "r", encoding="utf-8") as f:
            raw = f.read()

        # 提取 frontmatter
        body = raw
        frontmatter = {}
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].strip().split("\n"):
                    if ":" in line:
                        key, _, val = line.partition(":")
                        frontmatter[key.strip()] = val.strip().strip("'\"")
                body = parts[2]

        raw_title = frontmatter.get("title", md_file.stem)
        # 去掉 Hugo frontmatter 的 emoji 前缀（如 "💰 "）和单引号
        title = raw_title.strip("'\"")
        if title and title[0] in "💰🤖🌍📉📰":
            title = title[1:].strip()

        articles.append({
            "file": md_file,
            "category": category,
            "is_briefing": is_briefing,
            "is_deep": is_deep,
            "title": title,
            "body": body.strip(),
        })

    return articles


def process_article(token, article, args):
    """处理单篇文章：生图 + 转换 HTML + 存入草稿箱 + 回写封面到 Hugo"""
    cat = article["category"]
    title = article["title"]
    body = article["body"]
    md_file = article["file"]

    print(f"\n{'='*60}")
    print(f"📝 处理: [{cat}] {title}")
    print(f"{'='*60}")

    # 确定原文链接
    article_type = "deep-dive" if article["is_deep"] else "briefing"
    date_slug = datetime.now().strftime("%Y-%m-%d")
    article_url = f"{SITE_URL}/posts/{cat.lower()}/{article_type}-{date_slug}/"

    # ---- 封面图生成（双引擎）----
    cover_path = None
    cover_static_url = None
    if not args.no_image:
        cover_path, cover_static_url = generate_cover_image(title, cat, date_slug)

    # ---- 回写封面图到 Hugo 文章 frontmatter ----
    if cover_static_url and md_file:
        try:
            with open(md_file, "r", encoding="utf-8") as f:
                raw = f.read()
            if raw.startswith("---"):
                parts = raw.split("---", 2)
                if len(parts) >= 3 and "cover:" not in parts[1]:
                    # 在第二个 --- 前插入 cover 字段
                    fm = parts[1].rstrip() + f'\ncover: "{cover_static_url}"\n'
                    new_raw = f"---{fm}---{parts[2]}"
                    with open(md_file, "w", encoding="utf-8") as f:
                        f.write(new_raw)
                    print(f"   ✏️ 封面图已回写到 Hugo frontmatter")
        except Exception as e:
            print(f"   ⚠️ 回写封面失败: {e}")

    # ---- 上传封面图到公众号素材库 ----
    thumb_media_id = None
    if cover_path:
        try:
            thumb_media_id = upload_image(token, cover_path)
        except Exception as e:
            print(f"   ⚠️ 封面上传失败: {e}，将使用默认封面")
            cover_path = None

    if not thumb_media_id:
        print(f"   ⚠️ 无封面图，请在公众号后台手动添加封面")

    # ---- Markdown → 微信 HTML ----
    html_content = md_to_wechat_html(body, article_url)

    # 提取摘要
    import re as regex_lib
    plain_text = regex_lib.sub(r'<[^>]+>', '', html_content)
    digest = plain_text[:WECHAT_DIGEST_MAX].strip()

    # 构建文章数据
    article_data = {
        "title": title[:50],
        "author": WECHAT_AUTHOR,
        "digest": digest,
        "content": html_content,
        "content_source_url": article_url,
        "need_open_comment": 0,
    }
    if thumb_media_id:
        article_data["thumb_media_id"] = thumb_media_id

    if args.dry_run:
        print(f"   🔍 [DRY RUN] 将创建草稿: {title}")
        print(f"   HTML 长度: {len(html_content)} 字符")
        if cover_static_url:
            print(f"   🌐 网站封面: {cover_static_url}")
        return True

    try:
        add_draft(token, article_data)
        return True
    except Exception as e:
        print(f"   ❌ 草稿创建失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="微信公众号草稿箱发布工具")
    parser.add_argument("--date", help="处理指定日期文章 (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际创建草稿")
    parser.add_argument("--no-image", action="store_true", help="跳过封面图生成")
    parser.add_argument("--include-briefings", action="store_true",
                        help="同时推送每日快讯（默认仅推送精品深度长文）")
    args = parser.parse_args()

    # 参数校验
    if not WECHAT_APPID or not WECHAT_APPSECRET:
        print("❌ 请设置环境变量 WECHAT_APPID 和 WECHAT_APPSECRET")
        print("   在微信公众号后台 → 开发 → 基本配置 获取")
        sys.exit(1)

    if not args.no_image and not DASHSCOPE_API_KEY and not ZHIPU_API_KEY:
        print("⚠️ 未设置任何生图引擎 API Key，将跳过封面图生成")
        print("   通义万相: https://dashscope.console.aliyun.com/ (200 张/月免费)")
        print("   智谱 CogView: https://open.bigmodel.cn/ (100 张/月免费)")
        args.no_image = True

    # 查找文章
    articles = find_articles(args.date)
    if not articles:
        print(f"❌ 未找到日期为 {args.date or datetime.now().strftime('%Y-%m-%d')} 的文章")
        sys.exit(1)

    # 精品筛选：默认仅 deep-dive（质量已由模型把关）
    if not args.include_briefings:
        articles = [a for a in articles if a["is_deep"]]

    if not articles:
        print("✅ 今日无精品深度长文需要推送（快讯可通过 --include-briefings 开启）")
        sys.exit(0)

    # 生图数量预估
    if not args.no_image:
        print(f"📊 今日预计生图: {len(articles)} 张（通义万相免费 200/月 + 智谱 100/月备选）")

    print(f"📋 找到 {len(articles)} 篇精品文章")
    for a in articles:
        t = "深度长文" if a["is_deep"] else "快讯"
        print(f"   [{a['category']}] {t}: {a['title'][:40]}...")

    # 获取 access_token
    print(f"\n🔑 获取微信公众号 access_token...")
    token = get_access_token()
    print(f"   ✅ Token 获取成功")

    # 逐个处理
    success = 0
    for article in articles:
        if process_article(token, article, args):
            success += 1

    print(f"\n🏁 处理完毕: {success}/{len(articles)} 篇成功")
    if args.dry_run:
        print("   🔍 预览模式，未实际创建草稿。去掉 --dry-run 正式运行。")
    else:
        print(f"   📱 请前往微信公众号后台 → 草稿箱 审核并发布")
        print(f"   🌐 网站同步显示封面图: {SITE_URL}")
        # 将封面图推送回 GitLab，供 GitHub Actions 拉取用于网站
        push_covers_to_git()


def push_covers_to_git():
    """将生成的封面图推送到 GitLab，供 GitHub Actions 拉取用于网站"""
    try:
        import subprocess
        repo_dir = str(GIT_REPO_DIR)
        covers_glob = str(STATIC_COVERS_DIR / "*.png")
        # 检查是否有新封面图
        result = subprocess.run(
            ["git", "-C", repo_dir, "add", "static/images/covers/"],
            capture_output=True, text=True
        )
        subprocess.run(
            ["git", "-C", repo_dir, "commit", "-m", "Auto-generated cover images"],
            capture_output=True, text=True
        )
        subprocess.run(
            ["git", "-C", repo_dir, "push", "origin", "main"],
            capture_output=True, text=True, timeout=30
        )
        print("   📤 封面图已推送到 GitLab")
    except Exception as e:
        print(f"   ⚠️ 封面图推送失败: {e}")


if __name__ == "__main__":
    main()
