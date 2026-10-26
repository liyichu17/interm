"""提醒日志仓库抽象接口（设计文档 §5.4）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd

from ..models import ReminderLog


class LogRepository(ABC):
    """提醒日志读写。唯一约束 (invoice_no, remind_round) 保证幂等。"""

    @abstractmethod
    def save(self, log: ReminderLog) -> ReminderLog:
        """写入或更新一条日志（同 invoice_no + remind_round 视为同一条）。"""

    @abstractmethod
    def query_by_invoice(self, invoice_no: str) -> list[ReminderLog]:
        """按账单号查询全部提醒历史。"""

    @abstractmethod
    def latest(self, invoice_no: str) -> Optional[ReminderLog]:
        """取该账单最新一轮日志（轮次最大者）。"""

    @abstractmethod
    def latest_rounds(self, invoice_keys: list[str]) -> dict[str, ReminderLog]:
        """批量取最新轮次，返回 {账单键: 最新日志}（避免逐条查询）。"""

    @abstractmethod
    def mark_closed(self, invoice_no: str, reason: str = "") -> int:
        """将账单的非终态日志置为 CLOSED，返回受影响行数。"""

    @abstractmethod
    def export(self, filters: Optional[dict] = None) -> pd.DataFrame:
        """导出日志为 DataFrame（支持 status / 日期区间 / 账单号过滤）。"""

    @abstractmethod
    def list_active(self) -> list[ReminderLog]:
        """列出仍处于跟进状态（PENDING/SUCCESS/FAILED/ESCALATE）的日志。"""

    # ------------------------------------------------------------- 辅助能力
    def snooze(self, invoice_no: str, business_date: str) -> None:
        """「稍后提醒」：当日不再弹出（默认实现为空，子类可覆盖）。"""

    def is_snoozed(self, invoice_no: str, business_date: str) -> bool:
        return False

    def clear_snooze(self, business_date: str) -> None:
        pass

    def stats(self, business_date: str) -> dict:
        """当日统计：待提醒数 / 已发邮件数 / 失败数 / 累计逾期金额。"""
        return {"pending": 0, "sent": 0, "failed": 0, "amount_cny": 0.0}
