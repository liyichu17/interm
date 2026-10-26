"""通用工具：日期解析、业务日期、数值与文本归一化、日志。"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Excel 日期序列号基准（Windows 1900 日期系统，含 1900 闰年 bug 修正）
_EXCEL_EPOCH = "1899-12-30"

_DATE_PATTERNS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%d-%m-%Y",
    "%Y%m%d",
)


# --------------------------------------------------------------------- 日期
def parse_date(value: Any) -> Optional[dt.date]:
    """把源表单元格值解析为 date。

    兼容：date/datetime、``yyyy-mm-dd`` 字符串、Excel 日期序列号、空值。
    解析失败返回 ``None``（调用方按「无到期日 → 不参与逾期计算」处理）。
    """
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Excel 日期序列号
        try:
            return (pd.Timestamp(_EXCEL_EPOCH) + pd.Timedelta(days=float(value))).date()
        except (ValueError, OverflowError, TypeError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"nan", "nat", "none", "-", "--", "/"}:
            return None
        for pattern in _DATE_PATTERNS:
            try:
                return dt.datetime.strptime(text, pattern).date()
            except ValueError:
                continue
        # 形如 2026-10-24T00:00:00
        iso = text.replace("T", " ")
        for pattern in _DATE_PATTERNS:
            try:
                return dt.datetime.strptime(iso, pattern).date()
            except ValueError:
                continue
        logger.debug("无法解析日期：%r", value)
    return None


def parse_date_series(series: pd.Series) -> pd.Series:
    """向量化解析日期列，返回 ``datetime64[ns]``（无法解析为 NaT）。

    先按数值/日期类型快速处理，其余走字符串解析（逐个 parse_date）。
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_datetime(series, unit="D", origin=_EXCEL_EPOCH, errors="coerce")
    try:
        return pd.to_datetime(series.astype("string").str.strip(),
                              format="mixed", errors="coerce")
    except (ValueError, TypeError):
        return series.map(parse_date).pipe(pd.to_datetime, errors="coerce")


def business_date_now(tz_offset_hours: int = 8) -> dt.date:
    """当前业务日期（默认 UTC+8，设计文档 §7 时区约定）。"""
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=tz_offset_hours)))
    return now.date()


def overdue_days(due: Optional[dt.date], today: dt.date) -> Optional[int]:
    """逾期天数 = 业务日期 − Due Date（负数表示未到期）。"""
    if due is None:
        return None
    return (today - due).days


# --------------------------------------------------------------------- 数值
def to_float(value: Any, default: float = 0.0) -> float:
    """金额归一化：兼容千分位、括号负数、货币符号、空值。"""
    if value is None:
        return default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "-", "--"}:
        return default
    negative = text.startswith("(") and text.endswith(")")
    text = re.sub(r"[^\d.\-+eE]", "", text)
    if not text or text in {"-", "+", "."}:
        return default
    try:
        number = float(text)
    except ValueError:
        return default
    return -number if negative else number


def to_float_series(series: pd.Series) -> pd.Series:
    """金额列向量化归一化（无法解析 → 0.0）。"""
    if pd.api.types.is_numeric_dtype(series):
        return series.fillna(0.0).astype("float64")
    return pd.to_numeric(
        series.astype("string").str.replace(r"[^\d.\-+eE]", "", regex=True),
        errors="coerce",
    ).fillna(0.0)


# --------------------------------------------------------------------- 文本
def norm_text(value: Any) -> str:
    """文本归一化：空值 → 空串，去除首尾空白与不可见字符。"""
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = str(value).replace("\u00a0", " ").strip()
    return "" if text.lower() in {"nan", "nat", "none"} else text


def norm_text_series(series: pd.Series) -> pd.Series:
    """文本列向量化归一化（NaN → 空串，去首尾空白与占位符）。

    走 pandas 字符串向量化而非逐行 map，保证 10 万行级筛选性能（§7）。
    """
    text = series.astype("string").fillna("")
    text = text.str.replace("\u00a0", " ", regex=False).str.strip()
    return text.mask(text.str.lower().isin({"nan", "nat", "none"}), "")


def upper_in(values: pd.Series, allowed: set) -> pd.Series:
    """大小写不敏感 + 去空白的成员判断。"""
    return norm_text_series(values).str.upper().isin({a.upper() for a in allowed})


def split_emails(value: Any) -> list[str]:
    """拆分收件人/抄送（支持 ; , 与换行分隔），去重且保序。"""
    text = norm_text(value)
    if not text:
        return []
    parts = re.split(r"[;,\n\r]+", text)
    result: list[str] = []
    for part in parts:
        mail = part.strip()
        if mail and mail not in result:
            result.append(mail)
    return result


def fmt_money(value: Any, currency: str = "") -> str:
    """金额展示：千分位两位小数。"""
    number = to_float(value)
    text = f"{number:,.2f}"
    return f"{currency} {text}".strip() if currency else text


# --------------------------------------------------------------------- 日志
def setup_logging(log_dir: str, level: int = logging.INFO,
                  console: bool = True) -> logging.Logger:
    """配置文件日志（按天切分保留）+ 控制台输出。"""
    import os

    os.makedirs(log_dir, exist_ok=True)
    root = logging.getLogger("spv_reminder")
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(
        os.path.join(log_dir, f"app_{dt.date.today():%Y%m%d}.log"),
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        root.addHandler(stream)
    return root
