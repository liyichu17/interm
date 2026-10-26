"""邮件层：模板渲染与发送。"""

from ..models import DunningMail, SendResult
from .base import MailComposer, MailSender
from .composer import JinjaMailComposer
from .file_sender import FileMailSender
from .smtp_sender import SmtpMailSender

__all__ = [
    "MailSender", "MailComposer", "JinjaMailComposer",
    "FileMailSender", "SmtpMailSender", "DunningMail", "SendResult",
]


def build_mail_sender(cfg, from_addr: str = "") -> MailSender:
    """按配置构建发送器（file = 本地 .eml，smtp = 真实外发）。"""
    if cfg.mail.mode == "smtp":
        return SmtpMailSender(
            host=cfg.mail.smtp_host, port=cfg.mail.smtp_port,
            use_tls=cfg.mail.smtp_use_tls, username=cfg.mail.smtp_username,
            password_env=cfg.mail.smtp_password_env,
            from_addr=from_addr or cfg.mail.smtp_username,
        )
    return FileMailSender(cfg.resolve_outbox_dir(), from_addr=from_addr or "ar-team@example.com")


def build_mail_composer(cfg, template_dir: str) -> JinjaMailComposer:
    return JinjaMailComposer(template_dir, cfg.mail.smtp_template, cfg.mail.sender_name)
