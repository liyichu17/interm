"""生产提醒日志仓库：标准 SQL，兼容 MySQL / PostgreSQL / SQL Server。

与 SQLiteLogRepository 实现同一接口，通过 ``log_repo.type`` 配置切换。
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Optional

import pandas as pd

from ..constants import RemindStatus
from ..models import ReminderLog
from .base import LogRepository

logger = logging.getLogger(__name__)


class DbLogRepository(LogRepository):
    """数据库实现（表结构同 §4.2，由 ensure_schema 自动建表）。"""

    TABLE = "reminder_log"
    SNOOZE_TABLE = "snooze"

    def __init__(self, db_url: str, echo: bool = False):
        try:
            import sqlalchemy as sa
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("使用 database 日志仓库需安装 sqlalchemy") from exc
        self.sa = sa
        self.engine = sa.create_engine(db_url, pool_pre_ping=True, echo=echo)
        self.meta = sa.MetaData()
        self.table = sa.Table(
            self.TABLE, self.meta,
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column("invoice_no", sa.String(64), nullable=False),
            sa.Column("customer_code", sa.String(32)),
            sa.Column("customer_name", sa.String(256)),
            sa.Column("bu", sa.String(32)),
            sa.Column("remind_round", sa.Integer, nullable=False),
            sa.Column("remind_date", sa.Date),
            sa.Column("popup_shown", sa.Boolean, default=False),
            sa.Column("popup_shown_at", sa.DateTime),
            sa.Column("mail_generated", sa.Boolean, default=False),
            sa.Column("mail_sent", sa.Boolean, default=False),
            sa.Column("mail_to", sa.String(512)),
            sa.Column("mail_cc", sa.String(512)),
            sa.Column("sent_at", sa.DateTime),
            sa.Column("status", sa.String(16)),
            sa.Column("fail_reason", sa.String(512)),
            sa.Column("operator", sa.String(64)),
            sa.Column("amount_cny", sa.Numeric(18, 2), default=0),
            sa.Column("created_at", sa.DateTime),
            sa.Column("updated_at", sa.DateTime),
            sa.UniqueConstraint("invoice_no", "remind_round", name="uq_invoice_round"),
        )
        self.snooze = sa.Table(
            self.SNOOZE_TABLE, self.meta,
            sa.Column("invoice_no", sa.String(64), primary_key=True),
            sa.Column("biz_date", sa.Date, primary_key=True),
            sa.Column("created_at", sa.DateTime),
        )
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self.meta.create_all(self.engine, tables=[self.table, self.snooze], checkfirst=True)

    # ------------------------------------------------------------------ 写入
    def save(self, log: ReminderLog) -> ReminderLog:
        sa = self.sa
        now = dt.datetime.now()
        values = {
            "customer_code": log.customer_code, "customer_name": log.customer_name,
            "bu": log.bu, "remind_date": log.remind_date, "popup_shown": log.popup_shown,
            "popup_shown_at": log.popup_shown_at, "mail_generated": log.mail_generated,
            "mail_sent": log.mail_sent, "mail_to": log.mail_to, "mail_cc": log.mail_cc,
            "sent_at": log.sent_at, "status": log.status, "fail_reason": log.fail_reason,
            "operator": log.operator, "amount_cny": log.amount_cny, "updated_at": now,
        }
        t = self.table
        with self.engine.begin() as conn:
            existing = conn.execute(
                sa.select(t.c.id).where(t.c.invoice_no == log.invoice_no)
                .where(t.c.remind_round == log.remind_round)
            ).first()
            if existing:
                conn.execute(sa.update(t).where(t.c.id == existing[0]).values(**values))
                log.id = existing[0]
            else:
                result = conn.execute(sa.insert(t).values(
                    invoice_no=log.invoice_no, remind_round=log.remind_round,
                    created_at=now, **values))
                log.id = result.inserted_primary_key[0]
        return log

    def mark_closed(self, invoice_no: str, reason: str = "") -> int:
        sa = self.sa
        t = self.table
        with self.engine.begin() as conn:
            result = conn.execute(
                sa.update(t).where(t.c.invoice_no == invoice_no)
                .where(t.c.status.in_(RemindStatus.ACTIVE))
                .values(status=RemindStatus.CLOSED,
                        fail_reason=reason or "账单已回款/核销，自动关闭",
                        updated_at=dt.datetime.now())
            )
            return result.rowcount or 0

    # ------------------------------------------------------------------ 查询
    def query_by_invoice(self, invoice_no: str) -> list[ReminderLog]:
        sa = self.sa
        t = self.table
        with self.engine.connect() as conn:
            rows = conn.execute(
                sa.select(t).where(t.c.invoice_no == invoice_no).order_by(t.c.remind_round)
            ).mappings().all()
        return [self._to_log(r) for r in rows]

    def latest(self, invoice_no: str) -> Optional[ReminderLog]:
        sa = self.sa
        t = self.table
        with self.engine.connect() as conn:
            row = conn.execute(
                sa.select(t).where(t.c.invoice_no == invoice_no)
                .order_by(t.c.remind_round.desc(), t.c.id.desc()).limit(1)
            ).mappings().first()
        return self._to_log(row) if row else None

    def latest_rounds(self, invoice_keys: list[str]) -> dict[str, ReminderLog]:
        sa = self.sa
        t = self.table
        result: dict[str, ReminderLog] = {}
        if not invoice_keys:
            return result
        with self.engine.connect() as conn:
            for i in range(0, len(invoice_keys), 400):
                chunk = invoice_keys[i:i + 400]
                sub = (
                    sa.select(t.c.invoice_no, sa.func.max(t.c.remind_round).label("mr"))
                    .where(t.c.invoice_no.in_(chunk)).group_by(t.c.invoice_no).subquery()
                )
                rows = conn.execute(
                    sa.select(t).join(
                        sub, sa.and_(t.c.invoice_no == sub.c.invoice_no,
                                     t.c.remind_round == sub.c.mr))
                ).mappings().all()
                for row in rows:
                    log = self._to_log(row)
                    result.setdefault(log.invoice_no, log)
        return result

    def list_active(self) -> list[ReminderLog]:
        sa = self.sa
        t = self.table
        with self.engine.connect() as conn:
            rows = conn.execute(
                sa.select(t).where(t.c.status.in_(RemindStatus.ACTIVE))
                .order_by(t.c.remind_date.desc())
            ).mappings().all()
        return [self._to_log(r) for r in rows]

    def export(self, filters: Optional[dict] = None) -> pd.DataFrame:
        filters = filters or {}
        sa = self.sa
        t = self.table
        stmt = sa.select(t)
        if filters.get("status"):
            stmt = stmt.where(t.c.status == filters["status"])
        if filters.get("invoice_no"):
            stmt = stmt.where(t.c.invoice_no.like(f"%{filters['invoice_no']}%"))
        if filters.get("date_from"):
            stmt = stmt.where(t.c.remind_date >= filters["date_from"])
        if filters.get("date_to"):
            stmt = stmt.where(t.c.remind_date <= filters["date_to"])
        stmt = stmt.order_by(t.c.remind_date.desc(), t.c.id.desc())
        with self.engine.connect() as conn:
            return pd.DataFrame([dict(r) for r in conn.execute(stmt).mappings().all()])

    # ------------------------------------------------------------- 稍后提醒
    def snooze(self, invoice_no: str, business_date: str) -> None:
        sa = self.sa
        with self.engine.begin() as conn:
            conn.execute(sa.delete(self.snooze).where(
                self.snooze.c.invoice_no == invoice_no,
                self.snooze.c.biz_date == business_date))
            conn.execute(sa.insert(self.snooze).values(
                invoice_no=invoice_no, biz_date=business_date,
                created_at=dt.datetime.now()))

    def is_snoozed(self, invoice_no: str, business_date: str) -> bool:
        sa = self.sa
        with self.engine.connect() as conn:
            row = conn.execute(sa.select(self.snooze.c.invoice_no).where(
                self.snooze.c.invoice_no == invoice_no,
                self.snooze.c.biz_date == business_date)).first()
        return row is not None

    # ---------------------------------------------------------------- 统计
    def stats(self, business_date: str) -> dict:
        sa = self.sa
        t = self.table
        with self.engine.connect() as conn:
            def count(cond):
                return conn.execute(sa.select(sa.func.count()).select_from(t).where(
                    t.c.remind_date == business_date, cond)).scalar() or 0
            pending = count(t.c.status.in_(["PENDING", "ESCALATE"]))
            sent = count(t.c.mail_sent.is_(True))
            failed = count(t.c.status == "FAILED")
            amount = conn.execute(sa.select(sa.func.coalesce(sa.func.sum(t.c.amount_cny), 0))
                                  .select_from(t).where(
                                      t.c.remind_date == business_date,
                                      t.c.status.in_(RemindStatus.ACTIVE))).scalar() or 0
        return {"pending": pending, "sent": sent, "failed": failed, "amount_cny": float(amount)}

    # ---------------------------------------------------------------- 内部
    @staticmethod
    def _to_log(row) -> ReminderLog:
        return ReminderLog(
            id=row.get("id"),
            invoice_no=row.get("invoice_no") or "",
            customer_code=row.get("customer_code") or "",
            customer_name=row.get("customer_name") or "",
            bu=row.get("bu") or "",
            remind_round=row.get("remind_round") or 0,
            remind_date=row.get("remind_date"),
            popup_shown=bool(row.get("popup_shown")),
            popup_shown_at=row.get("popup_shown_at"),
            mail_generated=bool(row.get("mail_generated")),
            mail_sent=bool(row.get("mail_sent")),
            mail_to=row.get("mail_to") or "",
            mail_cc=row.get("mail_cc") or "",
            sent_at=row.get("sent_at"),
            status=row.get("status") or "",
            fail_reason=row.get("fail_reason") or "",
            operator=row.get("operator") or "",
            amount_cny=float(row.get("amount_cny") or 0),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
