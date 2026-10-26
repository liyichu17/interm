"""定时扫描调度（§3.3）：每日固定时间触发 + 同日去重。"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ReminderScheduler:
    """纯逻辑调度器（不绑定任何 GUI 框架，UI 层用定时器 tick 驱动）。

    - ``should_run``：到达设定时间且当日尚未成功扫描时返回 True；
    - ``next_run_at``：下一次触发时刻（用于状态栏展示）。
    """

    def __init__(self, daily_scan_time: str = "09:00", enabled: bool = True,
                 timezone_offset_hours: int = 8):
        self.enabled = enabled
        self.timezone_offset_hours = timezone_offset_hours
        self.scan_time = self._parse_time(daily_scan_time)
        self.last_run: Optional[dt.datetime] = None

    @staticmethod
    def _parse_time(text: str) -> dt.time:
        text = (text or "09:00").strip()
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                return dt.datetime.strptime(text, fmt).time()
            except ValueError:
                continue
        logger.warning("非法扫描时间 %r，回退 09:00", text)
        return dt.time(9, 0)

    def now(self) -> dt.datetime:
        return dt.datetime.now(dt.timezone(dt.timedelta(hours=self.timezone_offset_hours))
                               ).replace(tzinfo=None)

    def next_run_at(self, now: Optional[dt.datetime] = None) -> dt.datetime:
        now = now or self.now()
        candidate = now.replace(hour=self.scan_time.hour, minute=self.scan_time.minute,
                                second=0, microsecond=0)
        if candidate <= now:
            candidate += dt.timedelta(days=1)
        return candidate

    def should_run(self, now: Optional[dt.datetime] = None) -> bool:
        """是否应触发一次定时扫描（跨零点以触发时刻的业务日期为准）。"""
        if not self.enabled:
            return False
        now = now or self.now()
        if now.hour != self.scan_time.hour or now.minute != self.scan_time.minute:
            return False
        if self.last_run and self.last_run.date() == now.date():
            return False  # 同日已执行
        return True

    def mark_run(self, now: Optional[dt.datetime] = None) -> None:
        self.last_run = now or self.now()

    # -------------------------------------------------------- 同日去重（开机自启）
    @staticmethod
    def day_key(business_date: dt.date) -> str:
        return business_date.isoformat()
