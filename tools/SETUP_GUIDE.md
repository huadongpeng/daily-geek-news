# 腾讯云服务器初始化指南

## 每日自动化流程

```
北京时间 06:00  GitHub Actions 自动运行
  ├─ purifier.py: 4 引擎 × 双轨（快讯 + 可选深度长文）
  ├─ 生成 content/posts/<分类>/briefing-YYYY-MM-DD.md
  ├─ 生成 content/posts/<分类>/deep-dive-YYYY-MM-DD.md（质量门控）
  ├─ Telegram 推送（快讯丰满格式 + 深度长文单独推送）
  ├─ git commit & push → GitHub
  └─ git push → 你的 GitLab（腾讯云 Docker）

北京时间 07:00  腾讯云服务器 crontab
  ├─ git pull（从本地 Docker GitLab 拉取，秒级完成）
  ├─ python3 tools/wechat_publisher.py（默认仅精品深度长文）
  │   ├─ 双引擎封面图生成（通义万相 主 + 智谱 CogView 备）
  │   ├─ 封面保存到 static/images/covers/（网站可用）
  │   ├─ Markdown → 微信 HTML（含品牌栏 + 引流链接）
  │   └─ 存入公众号草稿箱
  └─ 你醒来后 → 公众号后台审核 → 发布

月均生图量：~4篇深度长文/天 × 30天 = ~120张
通义万相免费 200张/月 + 智谱 CogView 100张/月备选 → 完全够用
```

## 前置准备：获取 API Key

### 1. 微信公众号 AppID + AppSecret
1. 登录 [mp.weixin.qq.com](https://mp.weixin.qq.com)
2. 设置与开发 → 基本配置
3. 复制 AppID，点击「重置」获取 AppSecret（需管理员扫码）
4. 将服务器公网 IP 加入 IP 白名单（基本配置页下方）

### 2. 通义万相 API Key（主引擎，200张/月免费）
1. [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) → 支付宝登录
2. 左侧 API-KEY 管理 → 创建 → 复制

### 3. 智谱 CogView API Key（备引擎，100张/月免费）
1. [open.bigmodel.cn](https://open.bigmodel.cn) → 手机号注册
2. API Keys → 创建 → 复制

### 4. GitLab Personal Access Token
1. 登录你的 GitLab Docker 实例
2. Settings → Access Tokens
3. Token name: `github-push`，Scope: `write_repository` → 复制

## 服务器配置

### 第一步：创建 .env

```bash
cat > /ws/web/daily-geek-news/tools/.env << 'EOF'
export WECHAT_APPID="wx你的AppID"
export WECHAT_APPSECRET="你的AppSecret"
export WECHAT_AUTHOR="Easton Hua"
export DASHSCOPE_API_KEY="sk-你的百炼Key"
export ZHIPU_API_KEY="你的智谱Key"
export GIT_REPO_DIR="/ws/web/daily-geek-news"
EOF
chmod 600 /ws/web/daily-geek-news/tools/.env
```

### 第二步：配置 Git 从本地 GitLab 拉取

```bash
cd /ws/web/daily-geek-news

# 如果之前从 GitHub clone，改 remote 指向本地 GitLab
git remote set-url origin http://localhost:<GitLab端口>/<用户名>/daily-geek-news.git

# 测试拉取
git pull origin main
```

### 第三步：设置 crontab 定时任务

```bash
# 编辑 crontab
crontab -e

# 添加（每天早上 7 点执行）：
0 7 * * * cd /ws/web/daily-geek-news && git pull origin main && source tools/.env && /usr/bin/python3 tools/wechat_publisher.py >> /var/log/wechat_publisher.log 2>&1
```

### 第四步：手动测试

```bash
cd /ws/web/daily-geek-news
source tools/.env

# 预览模式
python3 tools/wechat_publisher.py --dry-run

# 如果快讯也想要推送
python3 tools/wechat_publisher.py --dry-run --include-briefings

# 正式运行
python3 tools/wechat_publisher.py
```

## GitHub Secrets（在 GitHub 仓库配置）

| Secret | 值 |
|--------|-----|
| `GITLAB_HOST` | `你的公网IP:GitLab端口` |
| `GITLAB_USERNAME` | GitLab 用户名 |
| `GITLAB_ACCESS_TOKEN` | 上面创建的 Access Token |

配置后 GitHub Actions 会自动推送文章到你的 GitLab。

## 生图额度监控

| 引擎 | 免费额度 | 单价 | 月用量预估 |
|------|---------|------|-----------|
| 通义万相 | 200张/月 | ¥0.04/张 | ~120张（主） |
| 智谱 CogView | 100张/月 | ¥0.10/张 | 0-30张（备） |

额度用完会自动切换备选引擎。如需增加备选：
- 百度文心一格：https://yige.baidu.com/ （免费额度不定）
- 腾讯混元：https://hunyuan.tencentcloudapi.com/ （腾讯云用户可能有优惠）
