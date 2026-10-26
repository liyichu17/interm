"""通用 UI 组件：统计卡片、DataFrame 表格填充、日志视图。"""

from __future__ import annotations

import datetime as dt

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..constants import C_AMOUNT_CNY, C_CASE_CATEGORY, C_PAYMENT_PLAN
from ..utils import fmt_money

HEADER_BG = QColor("#f2f6fa")
WARN_BG = QColor("#fff8e6")
ESCALATE_BG = QColor("#fdecea")
PLAN_BG = QColor("#eef7ee")


class StatCard(QFrame):
    """统计卡片：标题 + 数值。"""

    def __init__(self, title: str, value: str = "-", color: str = "#1f4e79", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "StatCard { border: 1px solid #d9e2ec; border-radius: 6px; background: #ffffff; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("color:#5c6b7a; font-size:12px;")
        self.value_label = QLabel(value)
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        self.value_label.setFont(font)
        self.value_label.setStyleSheet(f"color:{color};")
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


def fill_table(table: QTableWidget, df: pd.DataFrame, columns: list[str],
               row_marks: bool = True) -> None:
    """把 DataFrame 填充到 QTableWidget（含行内角标着色）。"""
    columns = [c for c in columns if c in df.columns] or list(df.columns)
    table.clear()
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setRowCount(len(df))

    from ..datasource.base import ROW_KEY

    for row_idx, (_, row) in enumerate(df.iterrows()):
        for col_idx, column in enumerate(columns):
            value = row.get(column)
            text = _format_cell(column, value)
            item = QTableWidgetItem(text)
            item.setData(Qt.UserRole, str(row.get(ROW_KEY, "")))
            if column == C_AMOUNT_CNY:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(row_idx, col_idx, item)
        if row_marks:
            _mark_row(table, row_idx, row, len(columns))
    table.resizeColumnsToContents()


def _format_cell(column: str, value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat() if isinstance(value, dt.date) else value.strftime("%Y-%m-%d %H:%M")
    if column == C_AMOUNT_CNY and isinstance(value, (int, float)):
        return fmt_money(value)
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def _mark_row(table: QTableWidget, row_idx: int, row, column_count: int) -> None:
    """行内标识：⚠ 争议、🔴 升级、📅 已有还款计划（§6.2）。"""
    background = None
    note = ""
    case_category = str(row.get(C_CASE_CATEGORY) or "")
    if str(row.get("escalated", False)).lower() in {"1", "true", "yes"}:
        background = ESCALATE_BG
        note = "🔴 已升级转主管"
    elif case_category and case_category != "未达催款节点":
        background = WARN_BG
        note = f"⚠ {case_category}"
    elif str(row.get(C_PAYMENT_PLAN) or "").strip():
        background = PLAN_BG
        note = "📅 已有还款计划"
    if background is None:
        return
    for col_idx in range(column_count):
        item = table.item(row_idx, col_idx)
        if item is not None:
            item.setBackground(background)
    if note and column_count:
        first = table.item(row_idx, 0)
        if first is not None:
            first.setToolTip(note)


def selected_row_keys(table: QTableWidget) -> list[str]:
    """取选中行的账单键（未选中任何行时视为全选）。"""
    rows = {item.row() for item in table.selectedItems()}
    if not rows:
        rows = set(range(table.rowCount()))
    keys = []
    for row in sorted(rows):
        item = table.item(row, 0)
        if item is not None:
            key = item.data(Qt.UserRole)
            if key:
                keys.append(str(key))
    return keys
