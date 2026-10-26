"""提醒日志仓库单元测试：幂等写入、轮次查询、关闭与统计。"""

from __future__ import annotations

import datetime as dt

import pytest

from spv_reminder.constants import RemindStatus
from spv_reminder.models import ReminderLog
from spv_reminder.repository import SQLiteLogRepository


@pytest.fixture
def repo(tmp_path) -> SQLiteLogRepository:
    return SQLiteLogRepository(str(tmp_path / "reminder.db"))


def _log(invoice: str = "INV-001", rnd: int = 1, status: str = RemindStatus.PENDING,
         remind_date: dt.date = dt.date(2026, 10, 26)) -> ReminderLog:
    return ReminderLog(invoice_no=invoice, customer_code="C1", customer_name="客户A",
                       bu="TIDES", remind_round=rnd, remind_date=remind_date,
                       status=status, amount_cny=100.0, operator="staff1")


def test_save_is_idempotent_for_same_round(repo):
    first = repo.save(_log())
    again = repo.save(_log(status=RemindStatus.SUCCESS))
    assert first.id == again.id
    assert len(repo.query_by_invoice("INV-001")) == 1
    assert repo.latest("INV-001").status == RemindStatus.SUCCESS


def test_different_rounds_create_separate_records(repo):
    repo.save(_log(rnd=1))
    repo.save(_log(rnd=2, remind_date=dt.date(2026, 11, 16)))
    assert len(repo.query_by_invoice("INV-001")) == 2
    assert repo.latest("INV-001").remind_round == 2


def test_latest_rounds_batch(repo):
    repo.save(_log("INV-001", rnd=1))
    repo.save(_log("INV-001", rnd=2))
    repo.save(_log("INV-002", rnd=1))
    mapping = repo.latest_rounds(["INV-001", "INV-002", "INV-404"])
    assert mapping["INV-001"].remind_round == 2
    assert mapping["INV-002"].remind_round == 1
    assert "INV-404" not in mapping


def test_mark_closed_only_affects_active(repo):
    repo.save(_log(rnd=1, status=RemindStatus.SUCCESS))
    repo.save(_log(rnd=2, status=RemindStatus.PENDING))
    closed = repo.mark_closed("INV-001", "已回款")
    assert closed == 2
    assert all(log.status == RemindStatus.CLOSED for log in repo.query_by_invoice("INV-001"))
    # 重复关闭不产生副作用
    assert repo.mark_closed("INV-001") == 0


def test_list_active_excludes_closed(repo):
    repo.save(_log("INV-001", status=RemindStatus.PENDING))
    repo.save(_log("INV-002", status=RemindStatus.CLOSED))
    active = repo.list_active()
    assert [log.invoice_no for log in active] == ["INV-001"]


def test_stats(repo):
    repo.save(_log("INV-001", status=RemindStatus.PENDING))
    sent = _log("INV-002", status=RemindStatus.SUCCESS)
    sent.mail_sent = True
    repo.save(sent)
    stats = repo.stats("2026-10-26")
    assert stats["pending"] == 1
    assert stats["sent"] == 1
    assert stats["amount_cny"] == pytest.approx(200.0)  # 两张账单各 100


def test_snooze_is_per_day(repo):
    repo.snooze("INV-001", "2026-10-26")
    assert repo.is_snoozed("INV-001", "2026-10-26") is True
    assert repo.is_snoozed("INV-001", "2026-10-27") is False
    repo.clear_snooze("2026-10-26")
    assert repo.is_snoozed("INV-001", "2026-10-26") is False


def test_scan_record_dedup(repo):
    assert repo.scanned_today("2026-10-26", "hash-1") is False
    repo.record_scan("2026-10-26", "hash-1", 5)
    assert repo.scanned_today("2026-10-26", "hash-1") is True
    assert repo.scanned_today("2026-10-26", "hash-2") is False  # 数据源变更需重扫


def test_export_filters(repo):
    repo.save(_log("INV-001", status=RemindStatus.SUCCESS))
    repo.save(_log("INV-002", status=RemindStatus.FAILED))
    df = repo.export({"status": RemindStatus.FAILED})
    assert len(df) == 1
    assert len(repo.export({"invoice_no": "INV-00"})) == 2
