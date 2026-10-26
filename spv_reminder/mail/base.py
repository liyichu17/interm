"""邮件接口（设计文档 §5.3）。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import DunningMail, SendResult


class MailSender(ABC):
    @abstractmethod
    def send(self, mail: DunningMail) -> SendResult:
        """发送一封催款邮件。"""


class MailComposer(ABC):
    @abstractmethod
    def compose(self, bills: list, language: str = "zh") -> list[DunningMail]:
        """按客户聚合并渲染邮件。"""
