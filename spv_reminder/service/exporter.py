"""导出服务：逾期清单 xlsx、提醒日志 xlsx/csv。"""

from __future__ import annotations

import datetime as dt
import os
from typing import Optional

import pandas as pd

from ..constants import DISPLAY_COLUMNS, EXPORT_EXTRA_COLUMNS
from ..datasource.base import ROW_KEY


def _pick_columns(df: pd.DataFrame, columns: list[str]) -> list[str]:
    return [c for c in columns if c in df.columns]


def export_overdue_list(hits: pd.DataFrame, path: str,
                        extra_columns: Optional[list[str]] = None,
                        sheet_name: str = "逾期账单") -> str:
    """导出弹窗清单：展示列 + Overdue Days + 内部辅助列。"""
    columns = _pick_columns(hits, DISPLAY_COLUMNS)
    columns += _pick_columns(hits, extra_columns or EXPORT_EXTRA_COLUMNS)
    data = hits[columns].copy() if len(hits) else pd.DataFrame(columns=columns)
    data = _drop_internal(data)

    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        data.to_excel(writer, sheet_name=sheet_name, index=False)
        _autofit(writer.sheets[sheet_name], data)
    return path


def export_logs(logs: pd.DataFrame, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    logs = _drop_internal(logs)
    if path.lower().endswith(".csv"):
        logs.to_csv(path, index=False, encoding="utf-8-sig")
    else:
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            logs.to_excel(writer, sheet_name="提醒日志", index=False)
            _autofit(writer.sheets["提醒日志"], logs)
    return path


def default_export_path(prefix: str = "SPV逾期账单", ext: str = "xlsx",
                        out_dir: str = ".") -> str:
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, f"{prefix}_{dt.datetime.now():%Y%m%d_%H%M%S}.{ext}")


def _drop_internal(df: pd.DataFrame) -> pd.DataFrame:
    internal = {ROW_KEY, "escalated", "skip_reason"}
    return df.drop(columns=[c for c in df.columns if c in internal], errors="ignore")


def _autofit(worksheet, data: pd.DataFrame, max_width: int = 42) -> None:
    from openpyxl.utils import get_column_letter

    for i, column in enumerate(data.columns, start=1):
        try:
            longest = max([len(str(column))] +
                          [len(str(v)) for v in data[column].head(200).tolist()])
        except ValueError:
            longest = len(str(column))
        width = min(max(10, longest + 2), max_width)
        worksheet.column_dimensions[get_column_letter(i)].width = width
