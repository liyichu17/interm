"""测试公共夹具：配置对象与样例账单 DataFrame。"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spv_reminder.config import Config  # noqa: E402
from spv_reminder.datasource import LocalXlsxSource, ROW_KEY  # noqa: E402

SAMPLE_COLUMNS = [
    "Company Name", "Company Code", "Customer Code", "Customer Name", "Project ID",
    "PO Number", "Invoice date/GL date", "Mapping", "Invoice NO.", "Due Date", "Aging",
    "Cust Curr", "Amount 的总和", "Amount in CNY", "BU", "Owner", "PS/PM", "To client",
    "Cc client", "SPV_Customer", "Dunning Block", "CN/Invoice", "Billed/Unbilled",
    "Case Category", "Payment plan/Resubmission (yyyy-mm-dd)", "Comments",
]


def make_row(**overrides) -> dict:
    """默认一行「逾期 30 天、SPV、Billed、有邮箱」的账单。"""
    row = {c: None for c in SAMPLE_COLUMNS}
    row.update({
        "Company Name": "测试主体", "Company Code": "3002",
        "Customer Code": "CUST-T1", "Customer Name": "测试客户",
        "Project ID": "PRJ-1", "PO Number": "PO-1",
        "Invoice date/GL date": "2026-08-01", "Invoice NO.": "INV-001",
        "Due Date": "2026-09-26", "Aging": "31 - 60 Days",
        "Cust Curr": "CNY", "Amount 的总和": 10000, "Amount in CNY": 10000,
        "BU": "TIDES", "Owner": "staff1", "PS/PM": "pm@example.com",
        "To client": "client@example.com", "Cc client": "cc@example.com",
        "SPV_Customer": "Y", "Dunning Block": None, "CN/Invoice": "Invoice",
        "Billed/Unbilled": "Billed", "Case Category": "未达催款节点",
    })
    row.update(overrides)
    return row


@pytest.fixture
def cfg() -> Config:
    config = Config.from_dict({})
    config.scan.target_bu_list = ["STA DS", "STA DP", "TIDES"]
    config.scan.first_overdue_days = 10
    config.scan.re_remind_interval_days = 20
    config.scan.max_remind_rounds = 3
    return config


@pytest.fixture
def business_date() -> dt.date:
    return dt.date(2026, 10, 26)  # 相对 2026-09-26 到期日 → 逾期 30 天


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """6 行样例：覆盖命中、各排除条件、未达阈值、非目标 BU。"""
    rows = [
        make_row(),                                                   # 命中
        make_row(**{"Invoice NO.": "INV-002", "Dunning Block": "X"}),  # a 催收冻结
        make_row(**{"Invoice NO.": "INV-003", "CN/Invoice": "Credit Note",
                    "Amount 的总和": -100, "Amount in CNY": -100}),     # b 贷记凭证
        make_row(**{"Invoice NO.": "INV-004", "To client": ""}),        # c 无邮箱
        make_row(**{"Invoice NO.": "INV-005", "Billed/Unbilled": "Unbilled"}),  # d 未开票
        make_row(**{"Invoice NO.": "INV-006", "Due Date": "2026-10-20"}),       # 逾期 6 天
        make_row(**{"Invoice NO.": "INV-007", "BU": "RCS"}),                    # 非目标 BU
        make_row(**{"Invoice NO.": "INV-008", "SPV_Customer": "N"}),            # 非 SPV
    ]
    df = pd.DataFrame(rows, columns=SAMPLE_COLUMNS)
    return LocalXlsxSource.with_row_key(df)
