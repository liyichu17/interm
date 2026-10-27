"""提醒日志查看窗口：过滤、追溯单张账单全部提醒历史、导出。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QVBoxLayout, QFileDialog,
)

from ..constants import RemindStatus
from ..service.exporter import export_logs
from .widgets import fill_table

LOG_COLUMNS = [
    "id",
    "remind_date",
    "invoice_no",
    "customer_code",
    "customer_name",
    "bu",
    "remind_round",
    "status",
    "popup_shown",
    "popup_shown_at",
    "mail_generated",
    "mail_sent",
    "mail_to",
    "mail_cc",
    "sent_at",
    "amount_cny",
    "operator",
    "fail_reason",
    "created_at",
    "updated_at",
]


class LogViewerDialog(QDialog):
    """日志查看：支持状态过滤、账单号查询、导出 xlsx/csv。"""

    def __init__(self, log_repo, parent=None, invoice_no: str = ""):
        super().__init__(parent)
        self.log_repo = log_repo
        self.setWindowTitle("提醒日志")
        self.resize(1120, 620)
        self._build_ui()
        if invoice_no:
            self.edit_invoice.setText(invoice_no)
        self.reload()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("状态"))
        self.combo_status = QComboBox()
        self.combo_status.addItems(["全部"] + list(RemindStatus.ALL))
        self.combo_status.currentTextChanged.connect(self.reload)
        filters.addWidget(self.combo_status)

        filters.addWidget(QLabel("账单号"))
        self.edit_invoice = QLineEdit()
        self.edit_invoice.setPlaceholderText("支持模糊匹配")
        self.edit_invoice.returnPressed.connect(self.reload)
        filters.addWidget(self.edit_invoice, 1)

        self.btn_query = QPushButton("查询")
        self.btn_query.clicked.connect(self.reload)
        self.btn_export = QPushButton("导出")
        self.btn_export.clicked.connect(self.export_logs)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.accept)
        for button in (self.btn_query, self.btn_export, self.btn_close):
            filters.addWidget(button)
        layout.addLayout(filters)

        self.table = QTableWidget()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color:#5c6b7a; font-size:12px;")
        layout.addWidget(self.summary_label)

    # ------------------------------------------------------------------ 数据
    def _filters(self) -> dict:
        filters = {}
        status = self.combo_status.currentText()
        if status and status != "全部":
            filters["status"] = status
        if self.edit_invoice.text().strip():
            filters["invoice_no"] = self.edit_invoice.text().strip()
        return filters

    def reload(self) -> None:
        df = self.log_repo.export(self._filters())
        columns = [c for c in LOG_COLUMNS if c in df.columns]
        columns += [c for c in df.columns if c not in columns]
        fill_table(self.table, df, columns, row_marks=False)
        self.summary_label.setText(f"共 {len(df)} 条记录　（选中行可查看 tooltip 中的完整信息）")

    def export_logs(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "导出提醒日志", "提醒日志.xlsx", "Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return
        df = self.log_repo.export(self._filters())
        export_logs(df, path)
        QMessageBox.information(self, "导出完成", f"已导出 {len(df)} 条：\n{path}")
