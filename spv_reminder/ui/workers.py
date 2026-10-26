"""后台工作线程：扫描与邮件发送放工作线程，通过信号回 UI（§7 性能）。"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Optional

from PySide6.QtCore import QThread, Signal

from ..models import DunningMail, SendResult

logger = logging.getLogger(__name__)


class ScanWorker(QThread):
    """执行一次扫描。"""

    finished = Signal(object)   # ScanReport
    failed = Signal(str)        # 异常信息

    def __init__(self, scanner, business_date: Optional[dt.date] = None, parent=None):
        super().__init__(parent)
        self.scanner = scanner
        self.business_date = business_date

    def run(self) -> None:  # noqa: D102 - QThread 入口
        try:
            report = self.scanner.scan(business_date=self.business_date)
            self.finished.emit(report)
        except Exception as exc:  # noqa: BLE001 - 线程内异常需回传 UI
            logger.exception("扫描失败")
            self.failed.emit(str(exc))


class MailWorker(QThread):
    """批量发送邮件；逐封回传进度与结果。"""

    progress = Signal(int, int, str)        # 当前序号 / 总数 / 描述
    mail_done = Signal(object, object)      # DunningMail / SendResult
    finished = Signal(int, int)             # 成功数 / 总数

    def __init__(self, sender, mails: list[DunningMail], parent=None):
        super().__init__(parent)
        self.sender = sender
        self.mails = mails

    def run(self) -> None:  # noqa: D102
        ok = 0
        total = len(self.mails)
        for index, mail in enumerate(self.mails, start=1):
            self.progress.emit(index, total, mail.customer_name)
            try:
                result: SendResult = self.sender.send(mail)
            except Exception as exc:  # noqa: BLE001
                result = SendResult(success=False, message=str(exc))
            ok += 1 if result.success else 0
            self.mail_done.emit(mail, result)
        self.finished.emit(ok, total)
