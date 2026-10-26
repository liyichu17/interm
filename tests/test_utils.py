"""工具函数单元测试：日期解析、金额归一化、邮箱拆分（§7 数据兼容）。"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from spv_reminder.utils import (
    fmt_money, norm_text, parse_date, parse_date_series, split_emails,
    to_float, to_float_series, upper_in,
)


@pytest.mark.parametrize("value,expected", [
    ("2026-10-24", dt.date(2026, 10, 24)),
    ("2026/10/24", dt.date(2026, 10, 24)),
    ("2026-10-24 00:00:00", dt.date(2026, 10, 24)),
    (dt.datetime(2026, 10, 24, 13, 5), dt.date(2026, 10, 24)),
    (dt.date(2026, 10, 24), dt.date(2026, 10, 24)),
    (None, None),
    ("", None),
    ("-", None),
    ("不是日期", None),
])
def test_parse_date_supports_common_formats(value, expected):
    assert parse_date(value) == expected


def test_parse_excel_serial_number():
    """Excel 日期序列号 46000 → 2025-12-10 附近（1900 日期系统）。"""
    result = parse_date(46000)
    assert isinstance(result, dt.date)
    assert abs((result - dt.date(2025, 12, 10)).days) <= 2


def test_parse_date_series_handles_mixed_types():
    series = pd.Series(["2026-10-01", None, "bad", "2026-11-12"])
    parsed = parse_date_series(series)
    assert parsed.iloc[0] == pd.Timestamp("2026-10-01")
    assert pd.isna(parsed.iloc[1]) and pd.isna(parsed.iloc[2])


@pytest.mark.parametrize("value,expected", [
    (1000, 1000.0),
    ("1,234.56", 1234.56),
    ("¥ 2,000", 2000.0),
    ("(500)", -500.0),
    ("", 0.0),
    (None, 0.0),
    ("abc", 0.0),
])
def test_to_float(value, expected):
    assert to_float(value) == expected


def test_to_float_series():
    series = pd.Series(["100", None, "2,000.5"])
    assert to_float_series(series).tolist() == [100.0, 0.0, 2000.5]


def test_norm_text_handles_nan_and_blank():
    assert norm_text(None) == ""
    assert norm_text(float("nan")) == ""
    assert norm_text("  abc ") == "abc"


def test_upper_in_is_case_insensitive():
    series = pd.Series(["Y", "y", "n", None])
    assert upper_in(series, {"Y"}).tolist() == [True, True, False, False]


def test_split_emails():
    assert split_emails("a@x.com; b@x.com,c@x.com") == ["a@x.com", "b@x.com", "c@x.com"]
    assert split_emails("") == []
    assert split_emails("a@x.com;a@x.com") == ["a@x.com"]


def test_fmt_money():
    assert fmt_money(1234.5) == "1,234.50"
    assert fmt_money(1234.5, "CNY") == "CNY 1,234.50"
