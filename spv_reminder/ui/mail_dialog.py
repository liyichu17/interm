"""邮件预览/编辑窗口（§6.3）：按客户聚合，支持编辑收件人/抄送与正文后发送。"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
    QPushButton, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from ..constants import RemindStatus
from ..models import DunningMail, SendResult
from ..utils import fmt_money

logger = logging.getLogger(__name__)


class MailPreviewDialog(QDialog):
    """左侧客户列表，右侧邮件内容编辑与预览。"""

    def __init__(self, mails: list[DunningMail], sender, log_repo, composer=None, parent=None):
        super().__init__(parent)
        self.mails = mails
        self.sender = sender
        self.log_repo = log_repo
        self.composer = composer
        self.results: list[tuple[DunningMail, SendResult]] = []
        self._loading = False
        self.setWindowTitle("催款邮件预览 / 编辑")
        self.resize(1180, 720)
        self._build_ui()
        if mails:
            self.mail_list.setCurrentRow(0)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)

        # 左：客户/邮件列表
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel(f"待发送邮件（{len(self.mails)} 封）"))
        self.mail_list = QListWidget()
        self.mail_list.currentRowChanged.connect(self.on_mail_selected)
        for mail in self.mails:
            self.mail_list.addItem(
                f"{mail.customer_name}　¥{fmt_money(mail.total_amount_cny)}　"
                f"{len(mail.invoices)} 张")
        left_layout.addWidget(self.mail_list, 1)
        splitter.addWidget(left)

        # 右：邮件内容
        right = QWidget()
        right_layout = QVBoxLayout(right)

        form = QHBoxLayout()
        form.addWidget(QLabel("收件人"))
        self.edit_to = QLineEdit()
        form.addWidget(self.edit_to, 3)
        form.addWidget(QLabel("抄送"))
        self.edit_cc = QLineEdit()
        form.addWidget(self.edit_cc, 3)
        right_layout.addLayout(form)

        subject_row = QHBoxLayout()
        subject_row.addWidget(QLabel("主题"))
        self.edit_subject = QLineEdit()
        subject_row.addWidget(self.edit_subject, 1)
        right_layout.addLayout(subject_row)

        self.body_edit = QTextEdit()
        self.body_edit.setAcceptRichText(True)
        right_layout.addWidget(self.body_edit, 1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#5c6b7a; font-size:12px;")
        right_layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.btn_prev = QPushButton("上一封")
        self.btn_next = QPushButton("下一封")
        self.btn_save_draft = QPushButton("保存草稿")
        self.btn_send_one = QPushButton("发送本封")
        self.btn_send_all = QPushButton("全部发送")
        self.btn_cancel = QPushButton("取消")
        for button in (self.btn_prev, self.btn_next, self.btn_save_draft,
                       self.btn_send_one, self.btn_send_all, self.btn_cancel):
            button.setMinimumHeight(32)
            buttons.addWidget(button)
        buttons.addStretch(1)
        right_layout.addLayout(buttons)

        self.btn_prev.clicked.connect(lambda: self._move(-1))
        self.btn_next.clicked.connect(lambda: self._move(1))
        self.btn_save_draft.clicked.connect(self.save_draft)
        self.btn_send_one.clicked.connect(self.send_current)
        self.btn_send_all.clicked.connect(self.send_all)
        self.btn_cancel.clicked.connect(self.reject)

        splitter.addWidget(right)
        splitter.setStretchFactor(1, 3)
        root.addWidget(splitter)

    # ------------------------------------------------------------------ 逻辑
    def on_mail_selected(self, row: int) -> None:
        if row < 0 or row >= len(self.mails):
            return
        mail = self.mails[row]
        self._loading = True
        self.edit_to.setText("; ".join(mail.to_addrs))
        self.edit_cc.setText("; ".join(mail.cc_addrs))
        self.edit_subject.setText(mail.subject)
        self.body_edit.setHtml(mail.html_body)
        self.status_label.setText(
            f"客户：{mail.customer_name}（{mail.customer_code}）　"
            f"账单 {len(mail.invoices)} 张　最长逾期 {mail.max_overdue_days} 天")
        self._loading = False

    def _apply_edits(self, mail: DunningMail) -> None:
        """把界面编辑同步回邮件对象。"""
        from ..utils import split_emails

        mail.to_addrs = split_emails(self.edit_to.text())
        mail.cc_addrs = split_emails(self.edit_cc.text())
        mail.subject = self.edit_subject.text()
        mail.html_body = self.body_edit.toHtml()

    def _move(self, step: int) -> None:
        row = self.mail_list.currentRow()
        target = min(max(row + step, 0), len(self.mails) - 1)
        if target != row:
            self.mail_list.setCurrentRow(target)

    def save_draft(self) -> None:
        """保存草稿：回写编辑内容并标记 mail_generated。"""
        row = self.mail_list.currentRow()
        if row < 0:
            return
        mail = self.mails[row]
        self._apply_edits(mail)
        self._write_log(mail, None)
        QMessageBox.information(self, "已保存", "草稿已保存（可在发件箱中继续编辑）。")

    def send_current(self) -> None:
        row = self.mail_list.currentRow()
        if row < 0:
            return
        mail = self.mails[row]
        self._apply_edits(mail)
        if not mail.to_addrs:
            QMessageBox.warning(self, "无法发送", "收件人为空，请补充客户邮箱后再发送。")
            return
        result = self.sender.send(mail)
        self.results.append((mail, result))
        self._write_log(mail, result)
        outcome = "发送成功" if result.success else "发送失败"
        QMessageBox.information(self, "发送结果",
                                f"{mail.customer_name}：{outcome}\n{result.message}")

    def send_all(self) -> None:
        ok = 0
        for mail in self.mails:
            if not mail.to_addrs:
                continue
            result = self.sender.send(mail)
            self.results.append((mail, result))
            self._write_log(mail, result)
            ok += 1 if result.success else 0
        failed = len(self.mails) - ok
        QMessageBox.information(
            self, "批量发送完成",
            f"共 {len(self.mails)} 封，成功 {ok} 封，失败 {failed} 封。\n"
            f"（收件人为空的邮件已跳过）")
        self.accept()

    def _write_log(self, mail: DunningMail, result: Optional[SendResult]) -> None:
        """回写每张账单对应日志的邮件状态（含失败原因）。"""
        for bill in mail.invoices:
            key = bill.raw.get("_row_key") or bill.invoice_no
            log = self.log_repo.latest(key)
            if log is None:
                continue
            log.mail_generated = True
            if result is not None:
                log.mail_to = "; ".join(mail.to_addrs)
                log.mail_cc = "; ".join(mail.cc_addrs)
                if result.success:
                    log.mail_sent = True
                    log.sent_at = result.sent_at
                    log.status = RemindStatus.SUCCESS
                    log.fail_reason = ""
                else:
                    log.status = RemindStatus.FAILED
                    log.fail_reason = result.message
            self.log_repo.save(log)
