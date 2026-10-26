"""扫描服务端到端测试：扫描 → 日志 → 队列 → 关闭（基于样例 xlsx）。"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from spv_reminder.config import Config
from spv_reminder.datasource import LocalXlsxSource
from spv_reminder.repository import SQLiteLogRepository
from spv_reminder.service.scanner import OverdueScanner

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_XLSX = str(PROJECT_ROOT / "data" / "bills.xlsx")

# 样例数据中出现的 BU（正式配置仅 STA DS / STA DP / TIDES，此处放宽以便覆盖多条数据）
DEMO_BU = ["TIDES", "RCS", "IVBU", "BAS", "MD", "DMPK"]


@pytest.fixture
def scanner(tmp_path):
    cfg = Config.from_dict({})
    cfg.scan.target_bu_list = DEMO_BU
    cfg.datasource.xlsx_path = SAMPLE_XLSX
    source = LocalXlsxSource(cfg.resolve_xlsx_path(), "Sheet1")
    repo = SQLiteLogRepository(str(tmp_path / "reminder.db"))
    return OverdueScanner(cfg, source, repo)


def test_scan_hits_and_skips(scanner):
    report = scanner.scan(business_date=dt.date(2026, 10, 26))
    assert report.scanned_rows == 11
    assert report.hit_count == 7
    # 唯一一条 Dunning Block = X 的账单应被跳过并记录原因
    assert len(report.skipped) == 1
    assert "Dunning Block" in report.skipped.iloc[0]["skip_reason"]
    assert report.overdue_keys  # 逾期清单用于自动关闭判定


def test_repeated_scan_same_day_is_idempotent(scanner):
    first = scanner.scan(business_date=dt.date(2026, 10, 26))
    second = scanner.scan(business_date=dt.date(2026, 10, 26))
    assert first.hit_count == 7
    assert second.hit_count == 0          # 同日不重复提醒
    assert second.closed_count == 0       # 仍在逾期清单，不得被关闭


def test_pending_queue_and_mark_processed(scanner):
    report = scanner.scan(business_date=dt.date(2026, 10, 26))
    queue = scanner.pending_queue(report.business_date)
    assert len(queue) == 7

    bill, log = queue[0]
    log.mail_sent = True
    scanner.log_repo.save(log)
    assert len(scanner.pending_queue(report.business_date)) == 6

    scanner.mark_processed(bill.raw["_row_key"], "人工已联系客户")
    latest = scanner.log_repo.latest(bill.raw["_row_key"])
    assert latest.status == "CLOSED"


def test_auto_close_when_no_longer_overdue(scanner):
    scanner.scan(business_date=dt.date(2026, 10, 26))
    # 业务日期早于所有到期日 → 全部账单不在逾期清单 → 日志自动关闭
    report = scanner.scan(business_date=dt.date(2026, 1, 1))
    assert report.hit_count == 0
    assert report.closed_count == 7
    assert scanner.pending_queue(dt.date(2026, 1, 1)) == []


def test_escalate_after_max_rounds(scanner):
    dates = [dt.date(2026, 10, 26), dt.date(2026, 11, 16),
             dt.date(2026, 12, 7), dt.date(2026, 12, 28)]
    for day in dates:
        scanner.scan(business_date=day, write_log=True)
    escalated = [log for log in scanner.log_repo.list_active()
                 if log.status == "ESCALATE"]
    # 10-26 首批 7 条账单经历 1→2→3 轮后，在 12-28 达到上限并升级
    assert len(escalated) == 7
    assert all(log.remind_round == 3 for log in escalated)
    assert {log.remind_date for log in escalated} == {dt.date(2026, 12, 7)}


def test_report_summary_and_amount(scanner):
    report = scanner.scan(business_date=dt.date(2026, 10, 26))
    assert "待提醒 7 条" in report.summary()
    assert report.total_amount_cny == pytest.approx(391373.99)
