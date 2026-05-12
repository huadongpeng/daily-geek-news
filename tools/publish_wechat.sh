#!/bin/bash
# ============================================================
# 微信公众号草稿箱发布脚本
# 每天 GitHub Actions 推送文章到 GitLab 后，运行此脚本
#
# 用法:
#   bash tools/publish_wechat.sh               # 推送今日精品深度长文
#   bash tools/publish_wechat.sh --yesterday   # 推送昨日文章
#   bash tools/publish_wechat.sh --dry-run     # 预览模式
#   bash tools/publish_wechat.sh --date 2026-05-11  # 指定日期
# ============================================================
set -e

REPO_DIR="${GIT_REPO_DIR:-/ws/web/daily-geek-news}"
cd "$REPO_DIR"

echo "=== 1. 拉取最新文章 ==="
# fetch + reset 避免 merge 冲突：服务器端是只读消费者，无需保留本地修改
git fetch origin main
git reset --hard origin/main

echo ""
echo "=== 2. 加载环境变量 ==="
source tools/.env

echo ""
echo "=== 3. 发布至公众号草稿箱 ==="
python3 tools/wechat_publisher.py "$@"

echo ""
echo "=== 完成 ==="
