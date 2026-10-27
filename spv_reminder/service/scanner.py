"""逾期扫描服务（OverdueScanner）：编排数据源 → 筛选 → 日志 → 关闭回写。"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from ..auth.base import UserInfo
from ..constants import (
    C_AMOUNT_CNY,
    RemindStatus,
    SKIP_CREDIT_NOTE,
    SKIP_DUNNING_BLOCK,
    SKIP_MAX_ROUND,
    SKIP_NO_MAIL,
    SKIP_UNBILLED,
)
from ..datasource import DataSource, LocalXlsxSource, ROW_KEY
from ..filters import FilterResult, SKIP_REASON, filter_overdue_bills
from ..models import Bill, ReminderLog
from ..repository import LogRepository
from ..utils import business_date_now, to_float

logger = logging.getLogger(__name__)

# 需要落 SKIPPED 日志的排除原因（其余为正常流转状态，不写日志）
EXCLUSION_REASONS = {
    SKIP_DUNNING_BLOCK, SKIP_CREDIT_NOTE, SKIP_NO_MAIL, SKIP_UNBILLED,
}


@dataclass
class ScanReport:
    """一次扫描的结果摘要。"""

    business_date: dt.date
    hits: pd.DataFrame
    skipped: pd.DataFrame
    scanned_rows: int = 0
    overdue_rows: int = 0
    closed_count: int = 0
    new_log_count: int = 0
    overdue_keys: set = field(default_factory=set)
    # 仍在逾期清单中的账单键（用于自动关闭判定与 UI 展示）
    data_source: str = ""
    degraded: bool = False
    degrade_reason: str = ""
    elapsed_ms: int = 0
    bills: list[Bill] = field(default_factory=list)

    @property
    def hit_count(self) -> int:
        return len(self.hits)

    @property
    def total_amount_cny(self) -> float:
        if not len(self.hits):
            return 0.0
        return round(float(pd.to_numeric(self.hits[C_AMOUNT_CNY], errors="coerce")
                           .fillna(0).sum()), 2)

    def summary(self) -> str:
        return (f"扫描 {self.scanned_rows} 行 / 逾期命中 {self.overdue_rows} 行 / "
                f"待提醒 {self.hit_count} 条 / 合计 ¥{self.total_amount_cny:,.2f} / "
                f"自动关闭 {self.closed_count} 条")


class OverdueScanner:
    """扫描器：只读源表 + 回写提醒日志，不修改账单数据（§1 非目标）。"""

    def __init__(self, cfg, datasource: DataSource, log_repo: LogRepository,
                 fallback_source: Optional[LocalXlsxSource] = None,
                 user: Optional[UserInfo] = None):
        self.cfg = cfg
        self.datasource = datasource
        self.log_repo = log_repo
        self.fallback_source = fallback_source
        self.user = user
        self.last_report: Optional[ScanReport] = None

    # ------------------------------------------------------------------ 主流程
    def scan(self, business_date: Optional[dt.date] = None,
             write_log: bool = True, apply_permission: bool = True) -> ScanReport:
        started = dt.datetime.now()
        business_date = business_date or business_date_now(self.cfg.scan.timezone_offset_hours)
        operator = self.user.user_id if self.user else ""

        # 1) 取数（数据库不可达时降级本地 xlsx，§2 降级可用）
        df, source_desc, degraded, degrade_reason = self._fetch()

        # 2) 批量取最新轮次日志
        keys = df[ROW_KEY].astype(str).tolist() if ROW_KEY in df else []
        latest_logs = self.log_repo.latest_rounds(keys)

        # 3) 核心筛选
        result: FilterResult = filter_overdue_bills(df, self.cfg, business_date, latest_logs)

        # 4) 权限视角（SSO 用户只见自己名下账单）
        hits = result.hits
        if apply_permission and self.user is not None and len(hits):
            hits = self._filter_by_permission(hits)

        # 5) 日志回写（幂等）与自动关闭
        new_logs, closed = 0, 0
        if write_log:
            new_logs = self._write_logs(hits, business_date, operator)
            self._write_skipped(result.skipped, business_date, operator)
            closed = self._auto_close(result.overdue_keys)

        report = ScanReport(
            business_date=business_date, hits=hits.reset_index(drop=True),
            skipped=result.skipped, scanned_rows=result.scanned_rows,
            overdue_rows=result.overdue_rows, closed_count=closed,
            new_log_count=new_logs, data_source=source_desc,
            overdue_keys=result.overdue_keys,
            degraded=degraded, degrade_reason=degrade_reason,
            elapsed_ms=int((dt.datetime.now() - started).total_seconds() * 1000),
            bills=[Bill.from_row(r) for _, r in hits.iterrows()],
        )
        self.last_report = report
        logger.info("扫描完成：%s（%d ms，来源：%s）", report.summary(),
                    report.elapsed_ms, source_desc)
        return report

    # ------------------------------------------------------------------ 步骤
    def _fetch(self):
        try:
            df = self.datasource.fetch_bills()
            return df, self.datasource.describe(), False, ""
        except Exception as exc:  # noqa: BLE001
            if self.fallback_source is None:
                raise
            logger.error("主数据源不可用，回退本地 xlsx：%s", exc)
            df = self.fallback_source.fetch_bills()
            return df, self.fallback_source.describe(), True, str(exc)

    def _filter_by_permission(self, hits: pd.DataFrame) -> pd.DataFrame:
        from ..constants import C_OWNER, C_PS_PM

        keep = []
        for _, row in hits.iterrows():
            if self.user.match_owner(str(row.get(C_OWNER) or ""), str(row.get(C_PS_PM) or "")):
                keep.append(True)
            else:
                keep.append(False)
        return hits[pd.Series(keep, index=hits.index)]

    def _write_logs(self, hits: pd.DataFrame, business_date: dt.date, operator: str) -> int:
        from ..constants import C_BU, C_CUSTOMER_CODE, C_CUSTOMER_NAME

        count = 0
        now = dt.datetime.now()
        for _, row in hits.iterrows():
            key = str(row.get(ROW_KEY) or row.get("Invoice NO.") or "")
            if not key:
                continue
            round_no = int(row.get("remind_round") or 1)
            escalated = bool(row.get("escalated"))
            status = RemindStatus.ESCALATE if escalated else RemindStatus.PENDING
            log = ReminderLog(
                invoice_no=key,
                customer_code=str(row.get(C_CUSTOMER_CODE) or ""),
                customer_name=str(row.get(C_CUSTOMER_NAME) or ""),
                bu=str(row.get(C_BU) or ""),
                remind_round=round_no,
                remind_date=business_date,
                status=status,
                amount_cny=to_float(row.get(C_AMOUNT_CNY)),
                operator=operator,
                popup_shown=True,
                popup_shown_at=now,
            )
            existing = self.log_repo.latest(key)
            if existing is not None and existing.remind_round == round_no:
                # 已存在同轮次记录：保持幂等，仅允许升级为 ESCALATE
                if escalated and existing.status != RemindStatus.ESCALATE:
                    existing.status = RemindStatus.ESCALATE
                    existing.fail_reason = SKIP_MAX_ROUND
                    existing.operator = operator
                    self.log_repo.save(existing)
                    count += 1
                continue
            self.log_repo.save(log)
            count += 1
        return count

    def _write_skipped(self, skipped: pd.DataFrame, business_date: dt.date, operator: str) -> None:
        """为排除规则命中的账单写 SKIPPED 记录（round=0，仅保留最新原因）。"""
        if not len(skipped):
            return
        from ..constants import C_BU, C_CUSTOMER_CODE, C_CUSTOMER_NAME

        for _, row in skipped.iterrows():
            key = str(row.get(ROW_KEY) or row.get("Invoice NO.") or "")
            reason = str(row.get(SKIP_REASON) or "")
            # 仅记录排除规则命中（Dunning Block / 贷记凭证 / 无邮箱 / Unbilled），
            # 「未到下一轮」「已关闭」属正常流转状态，不写日志避免噪音
            if not key or reason not in EXCLUSION_REASONS:
                continue
            self.log_repo.save(ReminderLog(
                invoice_no=key,
                customer_code=str(row.get(C_CUSTOMER_CODE) or ""),
                customer_name=str(row.get(C_CUSTOMER_NAME) or ""),
                bu=str(row.get(C_BU) or ""),
                remind_round=0,
                remind_date=business_date,
                status=RemindStatus.SKIPPED,
                fail_reason=reason,
                amount_cny=to_float(row.get(C_AMOUNT_CNY)),
                operator=operator,
            ))

    def _auto_close(self, overdue_keys: set) -> int:
        """账单已不在逾期清单（已回款/核销）→ 日志置 CLOSED（§3.2）。

        注意：仅「未到下一轮提醒时点」的账单仍在逾期清单内，不得关闭。
        """
        closed = 0
        for log in self.log_repo.list_active():
            if log.invoice_no in overdue_keys:
                continue
            closed += self.log_repo.mark_closed(
                log.invoice_no, "账单已不在逾期清单（回款/核销），自动关闭")
        if closed:
            logger.info("自动关闭 %d 条已回款账单日志", closed)
        return closed

    # ------------------------------------------------------- 待处理队列（弹窗/邮件）
    def pending_queue(self, business_date: Optional[dt.date] = None,
                      include_escalated: bool = False
                      ) -> list[tuple[Bill, ReminderLog]]:
        """取「已提醒待跟进、尚未成功发邮件」的账单队列。

        弹窗与「生成邮件」基于该队列，而非重新扫描，保证当日重复打开程序
        仍能继续未完成的催收动作（幂等且不重复发信）。

        ``include_escalated=True`` 时纳入已达最大轮次的账单：弹窗需标红展示，
        但不再自动生成/发送邮件（§3.2）。
        """
        business_date = business_date or business_date_now(self.cfg.scan.timezone_offset_hours)
        statuses = {RemindStatus.PENDING, RemindStatus.FAILED}
        if include_escalated:
            statuses.add(RemindStatus.ESCALATE)
        df = self.datasource.fetch_bills()
        index: dict[str, dict] = {}
        if ROW_KEY in df:
            for _, row in df.iterrows():
                index[str(row[ROW_KEY])] = row.to_dict()

        queue: list[tuple[Bill, ReminderLog]] = []
        for log in self.log_repo.list_active():
            if log.mail_sent or log.status not in statuses:
                continue
            row = index.get(log.invoice_no)
            if row is None:
                continue
            bill = Bill.from_row(row)
            bill.remind_round = log.remind_round
            bill.is_escalated = log.status == RemindStatus.ESCALATE
            bill.overdue_days = (business_date - bill.due_date).days if bill.due_date else None
            if self.user is not None and not self.user.match_owner(bill.owner, bill.ps_pm):
                continue
            queue.append((bill, log))
        return queue

    # ------------------------------------------------------------------ 交互
    def mark_processed(self, invoice_no: str, reason: str = "人工标记已处理") -> None:
        """人工关闭：弹窗「标记已处理」。"""
        self.log_repo.mark_closed(invoice_no, reason)
        logger.info("人工关闭账单 %s：%s", invoice_no, reason)

    def snooze(self, invoice_no: str, business_date: Optional[dt.date] = None) -> None:
        """「稍后提醒」：当日不再弹出。"""
        business_date = business_date or business_date_now(self.cfg.scan.timezone_offset_hours)
        self.log_repo.snooze(invoice_no, business_date.isoformat())

    def stats(self, business_date: Optional[dt.date] = None) -> dict:
        business_date = business_date or business_date_now(self.cfg.scan.timezone_offset_hours)
        return self.log_repo.stats(business_date.isoformat())
