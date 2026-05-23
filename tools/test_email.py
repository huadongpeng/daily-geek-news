#!/usr/bin/env python3
"""
本地邮件发送测试脚本。

用法：
  export EMAIL_FROM=1599932603@qq.com
  export EMAIL_PASSWORD=QQ邮箱授权码
  export EMAIL_TO=huadongpeng@outlook.com   # 可选，默认收件人
  python tools/test_email.py

支持的邮箱（自动识别 SMTP）：
  QQ / Foxmail   → smtp.qq.com:465 SSL
  163 / 126      → smtp.163.com:465 SSL
  Outlook / Live → smtp.office365.com:587 STARTTLS
  Gmail          → smtp.gmail.com:587 STARTTLS

自定义 SMTP（可选）：
  export EMAIL_SMTP_HOST=smtp.example.com
  export EMAIL_SMTP_PORT=465
"""
import os
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

EMAIL_FROM = os.environ.get("EMAIL_FROM", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", EMAIL_FROM)
EMAIL_SMTP_HOST = os.environ.get("EMAIL_SMTP_HOST", "")
EMAIL_SMTP_PORT = int(os.environ.get("EMAIL_SMTP_PORT", "0"))

SMTP_PRESETS: dict[str, tuple[str, int, bool]] = {
    "qq.com":      ("smtp.qq.com",          465, True),
    "foxmail.com": ("smtp.qq.com",          465, True),
    "163.com":     ("smtp.163.com",         465, True),
    "126.com":     ("smtp.126.com",         465, True),
    "yeah.net":    ("smtp.yeah.net",        465, True),
    "sina.com":    ("smtp.sina.com",        465, True),
    "outlook.com": ("smtp.office365.com",   587, False),
    "hotmail.com": ("smtp.office365.com",   587, False),
    "live.com":    ("smtp.office365.com",   587, False),
    "gmail.com":   ("smtp.gmail.com",       587, False),
}

if not EMAIL_FROM or not EMAIL_PASSWORD:
    raise SystemExit(
        "❌ 需要设置环境变量：\n"
        "  export EMAIL_FROM=你的邮箱\n"
        "  export EMAIL_PASSWORD=授权码或密码\n"
        "  export EMAIL_TO=收件人邮箱（可选）"
    )

if EMAIL_SMTP_HOST:
    port = EMAIL_SMTP_PORT or 587
    host, use_ssl = EMAIL_SMTP_HOST, port == 465
else:
    domain = EMAIL_FROM.split("@")[-1].lower()
    host, port, use_ssl = SMTP_PRESETS.get(domain, ("smtp.office365.com", 587, False))

print(f"📧 发件人: {EMAIL_FROM}")
print(f"📬 收件人: {EMAIL_TO}")
print(f"🔌 连接 {host}:{port} ({'SSL' if use_ssl else 'STARTTLS'}) ...")

msg = MIMEMultipart()
msg["From"] = EMAIL_FROM
msg["To"] = EMAIL_TO
msg["Subject"] = "[测试] Easton Radar 邮件功能验证"

body = (
    "这是一封测试邮件，说明 Easton Radar 邮件发送功能配置正确。\n\n"
    "文章标题：测试文章\n\n"
    "生图提示词：\n公众号封面图，900x383，2.35:1 横版构图，无文字，无logo，无人物面孔。测试用。"
)
msg.attach(MIMEText(body, "plain", "utf-8"))

attachment = MIMEBase("application", "octet-stream")
attachment.set_payload("这是测试正文内容。\n如果你看到这个附件，说明附件发送也正常。\n".encode("utf-8"))
encoders.encode_base64(attachment)
attachment.add_header("Content-Disposition", 'attachment; filename="test-article.txt"')
msg.attach(attachment)

try:
    if use_ssl:
        ctx = smtplib.SMTP_SSL(host, port)
    else:
        ctx = smtplib.SMTP(host, port)

    with ctx as server:
        if not use_ssl:
            server.ehlo()
            server.starttls()
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())

    print("✅ 邮件发送成功！请检查收件箱（或垃圾邮件文件夹）。")

except smtplib.SMTPAuthenticationError as e:
    print(f"\n❌ 认证失败: {e}")
    if "qq.com" in EMAIL_FROM:
        print("\nQQ 邮箱解决方法：")
        print("1. 登录 mail.qq.com → 设置 → 账户")
        print("2. 找到「POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务」")
        print("3. 开启「SMTP服务」，获取16位授权码")
        print("4. 用授权码作为 EMAIL_PASSWORD（不是QQ密码）")
    else:
        print("\n请检查邮箱密码或授权码是否正确。")

except Exception as e:
    print(f"\n❌ 发送失败: {e}")
