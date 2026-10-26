"""生产邮件发送器：企业 SMTP（密码从环境变量/钥匙串读取，不落盘）。"""

from __future__ import annotations

import datetime as dt
import logging
import os
import smtplib
from email.message import EmailMessage

from ..models import DunningMail, SendResult
from .base import MailSender

logger = logging.getLogger(__name__)


class SmtpMailSender(MailSender):
    """通过 SMTP 发送，支持 STARTTLS / SSL。"""

    def __init__(self, host: str, port: int = 587, use_tls: bool = True,
                 username: str = "", password_env: str = "SPV_SMTP_PASSWORD",
                 from_addr: str = "", timeout: int = 20, keyring_service: str = "spv_reminder"):
        self.host = host
        self.port = port
        self.use_tls = use_tls
        self.username = username
        self.password_env = password_env
        self.from_addr = from_addr or username or "ar-team@example.com"
        self.timeout = timeout
        self.keyring_service = keyring_service

    def send(self, mail: DunningMail) -> SendResult:
        if not self.host:
            return SendResult(success=False, message="未配置 SMTP 主机，邮件未发送")
        try:
            message = EmailMessage()
            message["Subject"] = mail.subject
            message["From"] = self.from_addr
            message["To"] = ", ".join(mail.to_addrs)
            if mail.cc_addrs:
                message["Cc"] = ", ".join(mail.cc_addrs)
            message.set_content(mail.text_body)
            message.add_alternative(mail.html_body, subtype="html")

            recipients = list(mail.to_addrs) + list(mail.cc_addrs)
            if self.port == 465:
                server = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
            try:
                server.ehlo()
                if self.use_tls and self.port != 465:
                    server.starttls()
                    server.ehlo()
                password = self._password()
                if self.username and password:
                    server.login(self.username, password)
                server.send_message(message, from_addr=self.from_addr, to_addrs=recipients)
            finally:
                try:
                    server.quit()
                except Exception:  # noqa: BLE001 - 关闭连接失败不影响结果
                    pass
            return SendResult(success=True, message="邮件已发送", sent_at=dt.datetime.now())
        except Exception as exc:  # noqa: BLE001
            logger.exception("SMTP 发送失败")
            return SendResult(success=False, message=f"SMTP 发送失败：{exc}")

    # ------------------------------------------------------------------ 安全
    def _password(self) -> str:
        """优先环境变量，其次系统钥匙串（keyring），配置文件不存明文。"""
        password = os.environ.get(self.password_env, "")
        if password:
            return password
        try:
            import keyring

            return keyring.get_password(self.keyring_service, self.username) or ""
        except Exception:  # noqa: BLE001 - keyring 不可用时静默降级
            return ""
