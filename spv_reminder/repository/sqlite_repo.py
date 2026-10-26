"""SQLite 本地提醒日志仓库（默认实现，零依赖）。"""

from __future__ import annotations

import datetime as dt
import logging
import os
import sqlite3
from typing import Optional

import pandas as pd

from ..constants import RemindStatus
from ..models import ReminderLog
from .base import LogRepository

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reminder_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_no      VARCHAR(64)  NOT NULL,
    customer_code   VARCHAR(32),
    customer_name   VARCHAR(256),
    bu              VARCHAR(32),
    remind_round    INTEGER      NOT NULL,
    remind_date     DATE,
    popup_shown     BOOLEAN      DEFAULT 0,
    popup_shown_at  DATETIME,
    mail_generated  BOOLEAN      DEFAULT 0,
    mail_sent       BOOLEAN      DEFAULT 0,
    mail_to         VARCHAR(512),
    mail_cc         VARCHAR(512),
    sent_at         DATETIME,
    status          VARCHAR(16),
    fail_reason     VARCHAR(512),
    operator        VARCHAR(64),
    amount_cny      DECIMAL(18,2) DEFAULT 0,
    created_at      DATETIME,
    updated_at      DATETIME,
    UNIQUE (invoice_no, remind_round)
);
CREATE INDEX IF NOT EXISTS idx_remind_date ON reminder_log(remind_date);
CREATE INDEX IF NOT EXISTS idx_status ON reminder_log(status);

CREATE TABLE IF NOT EXISTS snooze (
    invoice_no  VARCHAR(64) NOT NULL,
    biz_date    DATE        NOT NULL,
    created_at  DATETIME,
    PRIMARY KEY (invoice_no, biz_date)
);

CREATE TABLE IF NOT EXISTS scan_record (
    biz_date    DATE PRIMARY KEY,
    source_hash VARCHAR(64),
    scanned_at  DATETIME,
    hit_count   INTEGER DEFAULT 0
);
"""


def _iso(value):
    """datetime → ISO 秒级字符串（None 安全）。"""
    return value.isoformat(timespec="seconds") if value else None


def _row_to_log(row: sqlite3.Row) -> ReminderLog:
    def date_of(value):
        return dt.date.fromisoformat(value[:10]) if value else None

    def dt_of(value):
        if not value:
            return None
        try:
            return dt.datetime.fromisoformat(value)
        except ValueError:
            return None

    return ReminderLog(
        id=row["id"],
        invoice_no=row["invoice_no"],
        customer_code=row["customer_code"] or "",
        customer_name=row["customer_name"] or "",
        bu=row["bu"] or "",
        remind_round=row["remind_round"] or 0,
        remind_date=date_of(row["remind_date"]),
        popup_shown=bool(row["popup_shown"]),
        popup_shown_at=dt_of(row["popup_shown_at"]),
        mail_generated=bool(row["mail_generated"]),
        mail_sent=bool(row["mail_sent"]),
        mail_to=row["mail_to"] or "",
        mail_cc=row["mail_cc"] or "",
        sent_at=dt_of(row["sent_at"]),
        status=row["status"] or "",
        fail_reason=row["fail_reason"] or "",
        operator=row["operator"] or "",
        amount_cny=float(row["amount_cny"] or 0),
        created_at=dt_of(row["created_at"]),
        updated_at=dt_of(row["updated_at"]),
    )


class SQLiteLogRepository(LogRepository):
    """SQLite 实现（``%APPDATA%/spv_reminder/reminder.db``）。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
        self._init_db()

    # ---------------------------------------------------------------- 基础设施
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------ 写入
    def save(self, log: ReminderLog) -> ReminderLog:
        now = dt.datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM reminder_log WHERE invoice_no=? AND remind_round=?",
                (log.invoice_no, log.remind_round),
            ).fetchone()
            if row is None:
                cur = conn.execute(
                    """
                    INSERT INTO reminder_log (
                        invoice_no, customer_code, customer_name, bu, remind_round,
                        remind_date, popup_shown, popup_shown_at, mail_generated,
                        mail_sent, mail_to, mail_cc, sent_at, status, fail_reason,
                        operator, amount_cny, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        log.invoice_no, log.customer_code, log.customer_name, log.bu,
                        log.remind_round,
                        log.remind_date.isoformat() if log.remind_date else None,
                        int(log.popup_shown),
                        _iso(log.popup_shown_at),
                        int(log.mail_generated), int(log.mail_sent),
                        log.mail_to, log.mail_cc,
                        log.sent_at.isoformat(timespec="seconds") if log.sent_at else None,
                        log.status, log.fail_reason, log.operator, log.amount_cny,
                        now, now,
                    ),
                )
                log.id = cur.lastrowid
            else:
                conn.execute(
                    """
                    UPDATE reminder_log SET
                        customer_code=?, customer_name=?, bu=?, remind_date=?,
                        popup_shown=?, popup_shown_at=?, mail_generated=?, mail_sent=?,
                        mail_to=?, mail_cc=?, sent_at=?, status=?, fail_reason=?,
                        operator=?, amount_cny=?, updated_at=?
                    WHERE invoice_no=? AND remind_round=?
                    """,
                    (
                        log.customer_code, log.customer_name, log.bu,
                        log.remind_date.isoformat() if log.remind_date else None,
                        int(log.popup_shown),
                        _iso(log.popup_shown_at),
                        int(log.mail_generated), int(log.mail_sent),
                        log.mail_to, log.mail_cc,
                        log.sent_at.isoformat(timespec="seconds") if log.sent_at else None,
                        log.status, log.fail_reason, log.operator, log.amount_cny,
                        now, log.invoice_no, log.remind_round,
                    ),
                )
                log.id = row["id"]
        return log

    def mark_closed(self, invoice_no: str, reason: str = "") -> int:
        now = dt.datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE reminder_log SET status=?, fail_reason=?, updated_at=?
                WHERE invoice_no=? AND status IN ({})
                """.format(",".join("?" * len(RemindStatus.ACTIVE))),
                (RemindStatus.CLOSED, reason or "账单已回款/核销，自动关闭", now,
                 invoice_no, *RemindStatus.ACTIVE),
            )
            return cur.rowcount

    # ------------------------------------------------------------------ 查询
    def query_by_invoice(self, invoice_no: str) -> list[ReminderLog]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reminder_log WHERE invoice_no=? ORDER BY remind_round",
                (invoice_no,),
            ).fetchall()
        return [_row_to_log(r) for r in rows]

    def latest(self, invoice_no: str) -> Optional[ReminderLog]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM reminder_log WHERE invoice_no=? "
                "ORDER BY remind_round DESC, id DESC LIMIT 1",
                (invoice_no,),
            ).fetchone()
        return _row_to_log(row) if row else None

    def latest_rounds(self, invoice_keys: list[str]) -> dict[str, ReminderLog]:
        result: dict[str, ReminderLog] = {}
        if not invoice_keys:
            return result
        with self._connect() as conn:
            for chunk in _chunks(list(invoice_keys), 400):
                holders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"""
                    SELECT r.* FROM reminder_log r
                    JOIN (
                        SELECT invoice_no, MAX(remind_round) AS mr
                        FROM reminder_log WHERE invoice_no IN ({holders})
                        GROUP BY invoice_no
                    ) m ON r.invoice_no = m.invoice_no AND r.remind_round = m.mr
                    """,
                    chunk,
                ).fetchall()
                for row in rows:
                    key = row["invoice_no"]
                    if key not in result or row["id"] > (result[key].id or 0):
                        result[key] = _row_to_log(row)
        return result

    def list_active(self) -> list[ReminderLog]:
        holders = ",".join("?" * len(RemindStatus.ACTIVE))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM reminder_log WHERE status IN ({holders}) "
                "ORDER BY remind_date DESC",
                RemindStatus.ACTIVE,
            ).fetchall()
        return [_row_to_log(r) for r in rows]

    def export(self, filters: Optional[dict] = None) -> pd.DataFrame:
        filters = filters or {}
        sql = "SELECT * FROM reminder_log WHERE 1=1"
        params: list = []
        if filters.get("status"):
            sql += " AND status=?"
            params.append(filters["status"])
        if filters.get("invoice_no"):
            sql += " AND invoice_no LIKE ?"
            params.append(f"%{filters['invoice_no']}%")
        if filters.get("date_from"):
            sql += " AND remind_date >= ?"
            params.append(str(filters["date_from"]))
        if filters.get("date_to"):
            sql += " AND remind_date <= ?"
            params.append(str(filters["date_to"]))
        sql += " ORDER BY remind_date DESC, id DESC"
        with self._connect() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    # ------------------------------------------------------------- 稍后提醒
    def snooze(self, invoice_no: str, business_date: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO snooze (invoice_no, biz_date, created_at) VALUES (?,?,?)",
                (invoice_no, business_date, dt.datetime.now().isoformat(timespec="seconds")),
            )

    def is_snoozed(self, invoice_no: str, business_date: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM snooze WHERE invoice_no=? AND biz_date=?",
                (invoice_no, business_date),
            ).fetchone()
        return row is not None

    def clear_snooze(self, business_date: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM snooze WHERE biz_date=?", (business_date,))

    # ------------------------------------------------------------ 扫描去重
    def scanned_today(self, business_date: str, source_hash: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT source_hash FROM scan_record WHERE biz_date=?", (business_date,)
            ).fetchone()
        return row is not None and row["source_hash"] == source_hash

    def record_scan(self, business_date: str, source_hash: str, hit_count: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO scan_record (biz_date, source_hash, scanned_at, hit_count)"
                " VALUES (?,?,?,?)",
                (business_date, source_hash,
                 dt.datetime.now().isoformat(timespec="seconds"), hit_count),
            )

    def last_scan(self) -> Optional[dt.datetime]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT scanned_at FROM scan_record ORDER BY biz_date DESC LIMIT 1"
            ).fetchone()
        if not row or not row["scanned_at"]:
            return None
        try:
            return dt.datetime.fromisoformat(row["scanned_at"])
        except ValueError:
            return None

    # ---------------------------------------------------------------- 统计
    def stats(self, business_date: str) -> dict:
        with self._connect() as conn:
            pending = conn.execute(
                "SELECT COUNT(*) c FROM reminder_log WHERE remind_date=? "
                "AND status IN ('PENDING','ESCALATE')", (business_date,)
            ).fetchone()["c"]
            sent = conn.execute(
                "SELECT COUNT(*) c FROM reminder_log WHERE remind_date=? AND mail_sent=1",
                (business_date,)
            ).fetchone()["c"]
            failed = conn.execute(
                "SELECT COUNT(*) c FROM reminder_log WHERE remind_date=? AND status='FAILED'",
                (business_date,)
            ).fetchone()["c"]
            amount = conn.execute(
                "SELECT COALESCE(SUM(amount_cny),0) s FROM reminder_log "
                "WHERE remind_date=? AND status IN ('PENDING','SUCCESS','FAILED','ESCALATE')",
                (business_date,)
            ).fetchone()["s"]
        return {"pending": pending, "sent": sent, "failed": failed, "amount_cny": float(amount)}


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]
