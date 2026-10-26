"""弹窗提醒窗口（§6.2）：展示待跟进逾期账单清单。"""

from __future__ import annotations

import logging

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QMessageBox, QPushButton, QTableWidget, QVBoxLayout,
)

from ..constants import DISPLAY_COLUMNS, EXPORT_EXTRA_COLUMNS
from ..datasource.base import ROW_KEY
from ..service.exporter import default_export_path
from ..service.exporter import export_overdue_list
from ..utils import fmt_money
from .widgets import fill_table, selected_row_keys

logger = logging.getLogger(__name__)


class ReminderPopupDialog(QDialog):
    """待提醒账单弹窗：支持导出 / 生成邮件 / 标记已处理 / 稍后提醒。"""

    def __init__(self, report, scanner, cfg, parent=None):
        super().__init__(parent)
        self.report = report
        self.scanner = scanner
        self.cfg = cfg
        self.selected_mails: list = []
        self.setWindowTitle("SPV 逾期账单提醒")
        self.resize(1280, 620)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-size:14px; font-weight:600; color:#1f4e79;")
        layout.addWidget(self.title_label)

        tips = QLabel("行内标识：⚠ 争议账单　🔴 已达最大轮次（转主管）　📅 已有还款计划　"
                      "（默认按折人民币金额降序，点击表头可排序）")
        tips.setStyleSheet("color:#5c6b7a; font-size:12px;")
        layout.addWidget(tips)

        self.table = QTableWidget()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        layout.addWidget(self.table, 1)

        button_row = QHBoxLayout()
        self.btn_export = QPushButton("下载表格")
        self.btn_mail = QPushButton("生成邮件")
        self.btn_processed = QPushButton("标记已处理")
        self.btn_snooze = QPushButton("稍后提醒")
        self.btn_close = QPushButton("关闭")
        for button in (self.btn_export, self.btn_mail, self.btn_processed,
                       self.btn_snooze, self.btn_close):
            button.setMinimumHeight(32)
            button_row.addWidget(button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.btn_export.clicked.connect(self.export_table)
        self.btn_mail.clicked.connect(self.generate_mails)
        self.btn_processed.clicked.connect(self.mark_processed)
        self.btn_snooze.clicked.connect(self.snooze)
        self.btn_close.clicked.connect(self.accept)

        self.refresh(self.report)

    def refresh(self, report) -> None:
        self.report = report
        hits: pd.DataFrame = report.hits
        self.title_label.setText(
            f"业务日期 {report.business_date}　待跟进 {len(hits)} 张账单　"
            f"合计 ¥{fmt_money(report.total_amount_cny)}"
            + ("　（数据源降级：本地 xlsx）" if report.degraded else ""))
        columns = [c for c in DISPLAY_COLUMNS if c in hits.columns]
        columns += ["remind_round"] if "remind_round" in hits.columns else []
        columns += [c for c in EXPORT_EXTRA_COLUMNS if c in hits.columns and c not in columns]
        fill_table(self.table, hits, columns)

    # -------------------------------------------------------------- 业务动作
    def _current_keys(self) -> list[str]:
        return selected_row_keys(self.table)

    def _rows_by_keys(self, keys: list[str]) -> pd.DataFrame:
        hits = self.report.hits
        if ROW_KEY not in hits.columns:
            return hits.iloc[0:0]
        return hits[hits[ROW_KEY].astype(str).isin(keys)]

    def export_table(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        default = default_export_path("SPV逾期账单", "xlsx",
                                      out_dir=self.cfg.resolve_outbox_dir())
        path, _ = QFileDialog.getSaveFileName(self, "导出逾期清单", default, "Excel (*.xlsx)")
        if not path:
            return
        rows = self._rows_by_keys(self._current_keys())
        export_overdue_list(rows if len(rows) else self.report.hits, path)
        exported = len(rows) if len(rows) else len(self.report.hits)
        QMessageBox.information(self, "导出完成", f"已导出 {exported} 条：\n{path}")

    def generate_mails(self) -> None:
        """把勾选账单交给邮件预览窗口（按客户聚合）。"""
        keys = self._current_keys()
        rows = self._rows_by_keys(keys)
        if not len(rows):
            QMessageBox.information(self, "提示", "请先在表格中勾选需要生成邮件的账单。")
            return
        from ..models import Bill

        bills = []
        for _, row in rows.iterrows():
            bill = Bill.from_row(row.to_dict())
            overdue = row.get("Overdue Days")
            bill.overdue_days = int(overdue) if pd.notna(overdue) and overdue is not None else None
            bill.remind_round = int(row.get("remind_round") or 1)
            bill.is_escalated = bool(row.get("escalated"))
            bills.append(bill)
        # 已达最大轮次的账单不再自动生成邮件（§3.2）
        bills = [b for b in bills if not b.is_escalated]
        if not bills:
            QMessageBox.information(self, "提示", "所选账单均已达最大轮次（转主管处理），不再自动生成邮件。")
            return
        self.selected_mails = bills
        self.accept()

    def mark_processed(self) -> None:
        keys = self._current_keys()
        if not keys:
            return
        reason, ok = QInputDialog.getText(self, "标记已处理", "关闭原因（写入日志）：",
                                          text="人工已联系客户，确认付款安排")
        if not ok:
            return
        for key in keys:
            self.scanner.mark_processed(key, f"人工标记已处理：{reason}")
        remaining = self.report.hits[~self.report.hits[ROW_KEY].astype(str).isin(keys)]
        self.report.hits = remaining.reset_index(drop=True)
        self.refresh(self.report)
        QMessageBox.information(self, "已处理", f"已关闭 {len(keys)} 条账单提醒。")

    def snooze(self) -> None:
        keys = self._current_keys()
        for key in keys:
            self.scanner.snooze(key, self.report.business_date)
        remaining = self.report.hits[~self.report.hits[ROW_KEY].astype(str).isin(keys)]
        self.report.hits = remaining.reset_index(drop=True)
        self.refresh(self.report)
        if not len(self.report.hits):
            self.accept()
