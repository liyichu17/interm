"""核心筛选逻辑单元测试（设计文档 §3.1 / §3.2）。"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from spv_reminder.constants import (
    SKIP_DUNNING_BLOCK, SKIP_NO_MAIL, SKIP_UNBILLED, RemindStatus,
)
from spv_reminder.datasource import ROW_KEY
from spv_reminder.filters import (
    SKIP_REASON, base_mask, compute_overdue_days, decide_remind_round,
    exclusion_reasons, filter_overdue_bills,
)
from spv_reminder.models import Bill, ReminderLog

from .conftest import make_row


def _hit_invoices(result) -> list[str]:
    return result.hits["Invoice NO."].tolist() if len(result.hits) else []


# ------------------------------------------------------------------- 基础条件
def test_base_filter_only_keeps_overdue_target_bu_spv(cfg, sample_df, business_date):
    result = filter_overdue_bills(sample_df, cfg, business_date)
    assert _hit_invoices(result) == ["INV-001"]
    assert result.scanned_rows == len(sample_df)


def test_overdue_days_calculation(cfg, sample_df, business_date):
    overdue = compute_overdue_days(sample_df, business_date)
    assert overdue.iloc[0] == 30          # 2026-09-26 → 2026-10-26
    assert overdue.iloc[5] == 6           # 未达 10 天阈值
    assert pd.isna(overdue.iloc[5] + 0) is False


def test_unpaid_invoice_not_due_is_excluded(cfg, business_date):
    df = pd.DataFrame([make_row(**{"Due Date": "2026-11-30"})])
    df = _with_key(df)
    result = filter_overdue_bills(df, cfg, business_date)
    assert len(result.hits) == 0


def test_bu_config_is_driven_by_configuration(cfg, sample_df, business_date):
    cfg.scan.target_bu_list = ["RCS"]
    result = filter_overdue_bills(sample_df, cfg, business_date)
    assert _hit_invoices(result) == ["INV-007"]


def test_spv_flag_must_be_yes(cfg, sample_df, business_date):
    cfg.scan.target_bu_list = ["TIDES"]
    result = filter_overdue_bills(sample_df, cfg, business_date)
    assert "INV-008" not in _hit_invoices(result)


# ------------------------------------------------------------------- 排除规则
@pytest.mark.parametrize("overrides,expect_reason", [
    ({"Dunning Block": "X"}, SKIP_DUNNING_BLOCK),
    ({"To client": None}, SKIP_NO_MAIL),
    ({"Billed/Unbilled": "Unbilled"}, SKIP_UNBILLED),
])
def test_exclusion_rules_produce_skip_records(cfg, business_date, overrides, expect_reason):
    df = _with_key(pd.DataFrame([make_row(**overrides)]))
    result = filter_overdue_bills(df, cfg, business_date)
    assert len(result.hits) == 0
    assert result.skipped.iloc[0][SKIP_REASON] == expect_reason


def test_credit_note_with_negative_amount_skipped(cfg, business_date):
    from spv_reminder.constants import SKIP_CREDIT_NOTE

    df = _with_key(pd.DataFrame([make_row(**{
        "CN/Invoice": "Credit Note", "Amount 的总和": -500, "Amount in CNY": -500})]))
    result = filter_overdue_bills(df, cfg, business_date)
    assert result.skipped.iloc[0][SKIP_REASON] == SKIP_CREDIT_NOTE


def test_positive_credit_note_is_not_skipped(cfg, business_date):
    """金额为正的贷记凭证仍属应收，不应被排除。"""
    df = _with_key(pd.DataFrame([make_row(**{
        "CN/Invoice": "Credit Note", "Amount 的总和": 500, "Amount in CNY": 500})]))
    result = filter_overdue_bills(df, cfg, business_date)
    assert len(result.hits) == 1


# --------------------------------------------------------------------- 轮次
def test_first_remind_is_round_one(cfg, business_date):
    bill = Bill.from_row(make_row())
    included, rnd, reason, escalated = decide_remind_round(bill, cfg, business_date, None)
    assert (included, rnd, reason, escalated) == (True, 1, "", False)


def test_too_soon_after_last_remind(cfg, business_date):
    latest = ReminderLog(invoice_no="INV-001", remind_round=1,
                         remind_date=dt.date(2026, 10, 20), status=RemindStatus.SUCCESS)
    bill = Bill.from_row(make_row())
    included, rnd, reason, _ = decide_remind_round(bill, cfg, business_date, latest)
    assert included is False and rnd == 1 and "20" in reason


def test_next_round_after_interval(cfg, business_date):
    latest = ReminderLog(invoice_no="INV-001", remind_round=1,
                         remind_date=dt.date(2026, 10, 1), status=RemindStatus.SUCCESS)
    bill = Bill.from_row(make_row())
    included, rnd, reason, _ = decide_remind_round(bill, cfg, business_date, latest)
    assert (included, rnd, reason) == (True, 2, "")


def test_escalate_when_max_round_reached(cfg, business_date):
    latest = ReminderLog(invoice_no="INV-001", remind_round=3,
                         remind_date=dt.date(2026, 9, 1), status=RemindStatus.SUCCESS)
    bill = Bill.from_row(make_row())
    included, rnd, _, escalated = decide_remind_round(bill, cfg, business_date, latest)
    assert included is True and escalated is True and rnd == 3


def test_closed_is_terminal(cfg, business_date):
    latest = ReminderLog(invoice_no="INV-001", remind_round=1,
                         remind_date=dt.date(2026, 9, 1), status=RemindStatus.CLOSED)
    bill = Bill.from_row(make_row())
    included, _, reason, _ = decide_remind_round(bill, cfg, business_date, latest)
    assert included is False and reason


def test_failed_mail_still_counts_as_reminded(cfg, business_date):
    """发送失败的账单仍占用一轮，避免当日重复轰炸客户。"""
    latest = ReminderLog(invoice_no="INV-001", remind_round=1,
                         remind_date=dt.date(2026, 10, 25), status=RemindStatus.FAILED)
    bill = Bill.from_row(make_row())
    included, *_ = decide_remind_round(bill, cfg, business_date, latest)
    assert included is False


# ----------------------------------------------------------------- 排序/输出
def test_hits_sorted_by_amount_cny_desc(cfg, business_date):
    rows = [make_row(**{"Invoice NO.": "INV-A", "Amount in CNY": 100}),
            make_row(**{"Invoice NO.": "INV-B", "Amount in CNY": 9000}),
            make_row(**{"Invoice NO.": "INV-C", "Amount in CNY": 500})]
    df = _with_key(pd.DataFrame(rows))
    result = filter_overdue_bills(df, cfg, business_date)
    assert _hit_invoices(result) == ["INV-B", "INV-C", "INV-A"]
    assert "remind_round" in result.hits.columns


def test_empty_dataframe_is_safe(cfg, business_date):
    df = _with_key(pd.DataFrame(columns=[*make_row().keys()]))
    result = filter_overdue_bills(df, cfg, business_date)
    assert len(result.hits) == 0 and len(result.skipped) == 0


def test_mask_helpers(cfg, sample_df, business_date):
    mask = base_mask(sample_df, cfg, business_date)
    assert mask.sum() >= 1
    reasons = exclusion_reasons(sample_df)
    assert reasons.iloc[0] == ""            # 第一行无排除原因
    assert reasons.iloc[1] == SKIP_DUNNING_BLOCK


def _with_key(df: pd.DataFrame) -> pd.DataFrame:
    from spv_reminder.datasource import LocalXlsxSource

    return LocalXlsxSource.with_row_key(df)
