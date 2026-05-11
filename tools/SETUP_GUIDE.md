# 腾讯云服务器初始化指南

## 架构总览

```
海外（无墙）                          中国（腾讯云）
───────────                         ────────────
GitHub Actions                       Docker: GitLab
  │ 生成文章                            │
  ├─ git push → GitHub                │← GitHub Actions 推送到此
  └─ git push → GitLab ─────────────→ GitLab 收到推送
                                        │
                                        ├─ GitLab CI 自动触发
                                        │     │
                                        │     └─ python wechat_publisher.py
                                        │           ├─ 通义万相 生成封面图
                                        │           ├─ Markdown→微信HTML
                                        │           └─ 微信公众号草稿箱
                                        │
                                        └─ （可选）部署国内 Hugo 镜像
```

## 前置准备：获取 4 个 Key

### 1. 微信公众号 AppID + AppSecret
1. 登录 [mp.weixin.qq.com](https://mp.weixin.qq.com)
2. 左侧菜单 → 设置与开发 → 基本配置
3. 复制 **AppID**（开发者ID）
4. 点击 **AppSecret** 旁的「重置」获取密钥（需管理员扫码）
5. **重要**：将服务器公网 IP 加入 IP 白名单（基本配置页面下方）

### 2. 阿里百炼 API Key（通义万相生图，200张/月免费）
1. 打开 [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com)
2. 支付宝扫码登录
3. 左侧 → API-KEY 管理 → 创建新的 API Key
4. 复制保存（只显示一次）

### 3. GitLab Personal Access Token
1. 登录你的 GitLab（Docker 实例）
2. 右上角头像 → Settings → Access Tokens
3. Token name: `github-action-push`
4. Scopes: 勾选 `write_repository`
5. 创建并复制 Token（只显示一次）

## 服务器初始化步骤

### 第一步：确保 GitLab Docker 可从外网访问

```bash
# 查看 GitLab Docker 端口映射
docker ps | grep gitlab

# 腾讯云安全组放行 GitLab 端口（通常 80/443 或 8080/8443）
# 控制台 → 云服务器 → 安全组 → 添加入站规则
#   协议: TCP  端口: 你的GitLab端口  来源: 0.0.0.0/0
```

验证外网可访问：
```bash
# 在你本地电脑浏览器访问
http://<腾讯云公网IP>:<端口>
```

### 第二步：克隆仓库到服务器

```bash
# 在腾讯云服务器上执行
cd /opt
git clone https://github.com/huadongpeng/daily-geek-news.git
cd daily-geek-news
```

> 如果服务器无法访问 GitHub，先在本地下载 zip 再 SCP 上传，或使用镜像站。

### 第三步：创建环境变量文件

```bash
# 创建 .env 文件（不会被 Git 提交）
cat > /opt/daily-geek-news/tools/.env << 'EOF'
# === 微信公众号 ===
WECHAT_APPID=wx你的AppID
WECHAT_APPSECRET=你的AppSecret
WECHAT_AUTHOR=Easton Hua

# === 通义万相封面图 ===
DASHSCOPE_API_KEY=sk-你的百炼APIKey

# === Git 仓库路径（一般不用改） ===
GIT_REPO_DIR=/opt/daily-geek-news
EOF

# 设置权限（保护密钥）
chmod 600 /opt/daily-geek-news/tools/.env
```

### 第四步：安装 Python 依赖并测试

```bash
cd /opt/daily-geek-news
# CentOS 7 用 pip3 + 阿里云镜像
pip3 install -r tools/requirements_wechat.txt -i https://mirrors.aliyun.com/pypi/simple/

# 加载环境变量并测试（预览模式）
source tools/.env
python tools/wechat_publisher.py --dry-run

# 如果预览正常，去掉 --dry-run 正式运行
python tools/wechat_publisher.py
```

### 第五步：配置 GitLab CI 自动触发

```bash
# 将示例文件重命名为正式 CI 配置
cp tools/.gitlab-ci.yml.example .gitlab-ci.yml

# 在 GitLab Settings → CI/CD → Variables 中添加以下变量：
#   WECHAT_APPID       = wx你的AppID
#   WECHAT_APPSECRET   = 你的AppSecret
#   DASHSCOPE_API_KEY  = sk-你的百炼Key
#   WECHAT_AUTHOR      = Easton Hua
```

### 第六步：在 GitHub Actions 中添加 GitLab 推送

给仓库添加 3 个 GitHub Secrets（Settings → Secrets and variables → Actions）：

| Secret 名称 | 值 |
|-------------|-----|
| `GITLAB_HOST` | `你的腾讯云公网IP:端口`（如 `42.193.xxx.xxx:8080`）|
| `GITLAB_USERNAME` | GitLab 登录用户名 |
| `GITLAB_ACCESS_TOKEN` | 上面创建的 Personal Access Token |

配置完成后，告诉我，我会更新 `.github/workflows/main.yml` 添加推送到 GitLab 的步骤。

## 日常使用

全部配置完成后，完全自动化：

1. **每天 06:00（北京时间）** GitHub Actions 运行
2. 生成文章 → 推送 GitHub + GitLab
3. GitLab CI 自动触发 → 公众号草稿箱
4. **你醒来后**：打开公众号后台 → 草稿箱 → 审核 → 发布
5. 同步 Telegram 已推送快讯和深度长文摘要
