#!/usr/bin/env python3
"""
本地邮件发送测试脚本。
用法：
  export EMAIL_FROM=你的邮箱@outlook.com
  export EMAIL_PASSWORD=你的密码或应用密码
  export EMAIL_TO=收件人邮箱（可选，默认和 FROM 相同）
  python tools/test_email.py
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

EMAIL_FROM = os.environ.get("EMAIL_FROM", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", EMAIL_FROM)

if not EMAIL_FROM or not EMAIL_PASSWORD:
    raise SystemExit(
        "❌ 需要设置环境变量：\n"
        "  export EMAIL_FROM=你的邮箱@outlook.com\n"
        "  export EMAIL_PASSWORD=密码或应用密码"
    )

print(f"📧 发件人: {EMAIL_FROM}")
print(f"📬 收件人: {EMAIL_TO}")
print("🔌 连接 smtp.office365.com:587 ...")

msg = MIMEMultipart()
msg["From"] = EMAIL_FROM
msg["To"] = EMAIL_TO
msg["Subject"] = "[测试] Easton Radar 邮件功能验证"

body = (
    "这是一封测试邮件，说明 Easton Radar 邮件发送功能配置正确。\n\n"
    "文章标题：测试文章\n\n"
    "生图提示词：\n公众号封面图，900x383，2.35:1 横版构图，无文字，无logo，无人物面孔。"
    "测试用科技感抽象图案，蓝色调。"
)
msg.attach(MIMEText(body, "plain", "utf-8"))

attachment_content = "这是测试正文内容。\n如果你看到这个附件，说明附件发送也正常。\n"
attachment = MIMEBase("application", "octet-stream")
attachment.set_payload(attachment_content.encode("utf-8"))
encoders.encode_base64(attachment)
attachment.add_header("Content-Disposition", 'attachment; filename="test-article.txt"')
msg.attach(attachment)

try:
    with smtplib.SMTP("smtp.office365.com", 587) as server:
        server.set_debuglevel(1)
        server.ehlo()
        server.starttls()
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
    print("✅ 邮件发送成功！请检查收件箱（或垃圾邮件）。")
except smtplib.SMTPAuthenticationError as e:
    print(f"\n❌ 认证失败: {e}")
    print("\n可能原因及解决方法：")
    print("1. 如果开启了两步验证：")
    print("   → 去 account.microsoft.com/security → 高级安全选项 → 应用密码")
    print("   → 生成一个应用密码，用它替换 EMAIL_PASSWORD")
    print("2. 如果是普通账号（未开启两步验证）：")
    print("   → Outlook 个人账号已于 2023 年停止支持基本身份验证")
    print("   → 必须开启两步验证后使用应用密码")
    print("3. 如果是企业/教育账号：")
    print("   → 联系管理员开启 SMTP AUTH 权限")
except Exception as e:
    print(f"\n❌ 发送失败: {e}")
