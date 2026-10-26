"""测试用邮件发送器：生成 .eml 文件到本地目录，不真实外发（§5.3 FileMailSender）。"""

from __future__ import annotations

import datetime as dt
import os
import re
from email.message import EmailMessage

from ..models import DunningMail, SendResult
from .base import MailSender


class FileMailSender(MailSender):
    """把邮件写入 outbox 目录（可用 Outlook/邮件客户端打开预览）。"""

    def __init__(self, outbox_dir: str, from_addr: str = "ar-team@example.com"):
        self.outbox_dir = outbox_dir
        self.from_addr = from_addr
        os.makedirs(outbox_dir, exist_ok=True)

    def send(self, mail: DunningMail) -> SendResult:
        try:
            now = dt.datetime.now()
            message = EmailMessage()
            message["Subject"] = mail.subject
            message["From"] = self.from_addr
            message["To"] = ", ".join(mail.to_addrs)
            if mail.cc_addrs:
                message["Cc"] = ", ".join(mail.cc_addrs)
            message.set_content(mail.text_body)
            message.add_alternative(mail.html_body, subtype="html")

            safe = _safe_filename(mail.customer_name or mail.customer_code or "customer")
            path = os.path.join(self.outbox_dir, f"{now:%Y%m%d_%H%M%S}_{safe}.eml")
            with open(path, "wb") as fp:
                fp.write(message.as_bytes())
            return SendResult(success=True, message=f"邮件已生成：{path}",
                              sent_at=now, path=path)
        except Exception as exc:  # noqa: BLE001 - 发送失败仅记录，不阻断流程
            return SendResult(success=False, message=f"生成邮件文件失败：{exc}")


def _safe_filename(text: str) -> str:
    name = re.sub(r"[^\w\u4e00-\u9fa5.-]+", "_", text).strip("_")
    return name[:60] or "customer"
