"""主窗口（§6.1）：控制区 + 统计卡片 + 实时日志 + 状态栏 + 系统托盘。"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Optional

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
    QMenu, QMessageBox, QPushButton, QStatusBar, QSystemTrayIcon, QTextEdit,
    QTimeEdit, QVBoxLayout, QWidget,
)

from .. import __version__
from ..auth.base import UserInfo
from ..config import Config, project_root
from ..mail import build_mail_composer, build_mail_sender
from ..service import (
    export_overdue_list, is_autostart_enabled, set_autostart,
)
from ..service.exporter import default_export_path
from ..service.scanner import OverdueScanner, ScanReport
from ..service.scheduler import ReminderScheduler
from ..utils import business_date_now, fmt_money
from .log_dialog import LogViewerDialog
from .mail_dialog import MailPreviewDialog
from .popup_dialog import ReminderPopupDialog
from .widgets import StatCard
from .workers import ScanWorker

logger = logging.getLogger(__name__)


class QtLogHandler(logging.Handler):
    """把运行日志实时输出到界面的日志区（§6.1 日志窗口）。"""

    def __init__(self, sink: Signal):
        super().__init__()
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        try:
            self.sink.emit(self.format(record))
        except Exception:  # noqa: BLE001 - 日志输出失败不得影响主流程
            pass


class MainWindow(QMainWindow):
    """应用主窗口。"""

    def __init__(self, cfg: Config, scanner: OverdueScanner, datasource, log_repo,
                 auth_user: Optional[UserInfo] = None, auth_provider=None):
        super().__init__()
        self.cfg = cfg
        self.scanner = scanner
        self.datasource = datasource
        self.log_repo = log_repo
        self.user = auth_user
        self.auth_provider = auth_provider
        self.composer = build_mail_composer(cfg, cfg.resolve_template_dir(project_root()))
        self.sender = build_mail_sender(cfg)
        self.scheduler = ReminderScheduler(
            cfg.scan.daily_scan_time, cfg.app.daily_scan_enabled,
            cfg.scan.timezone_offset_hours)
        self.last_report: Optional[ScanReport] = None

        self.setWindowTitle(f"SPV 客户逾期账单提醒工具 v{__version__}")
        self.resize(1180, 760)
        self._build_ui()
        self._build_tray()
        self._start_timers()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 10, 12, 10)

        layout.addLayout(self._build_header())
        layout.addWidget(self._build_controls())
        layout.addLayout(self._build_stats())
        layout.addWidget(self._build_log_area(), 1)
        self.setCentralWidget(central)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.refresh_status()

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.user_label = QLabel()
        self.user_label.setStyleSheet("font-weight:600; color:#1f4e79;")
        row.addWidget(self.user_label)

        self.btn_login = QPushButton("登录")
        self.btn_logout = QPushButton("注销")
        self.btn_login.clicked.connect(self.do_login)
        self.btn_logout.clicked.connect(self.do_logout)
        row.addWidget(self.btn_login)
        row.addWidget(self.btn_logout)

        row.addStretch(1)
        row.addWidget(QLabel("数据源："))
        self.source_light = QLabel("●")
        self.source_label = QLabel()
        self.btn_reload = QPushButton("重新加载")
        self.btn_reload.clicked.connect(self.reload_source)
        row.addWidget(self.source_light)
        row.addWidget(self.source_label)
        row.addWidget(self.btn_reload)
        self.refresh_user()
        self.refresh_source()
        return row

    def _build_controls(self) -> QGroupBox:
        group = QGroupBox("扫描控制")
        row = QHBoxLayout(group)

        self.check_autostart = QCheckBox("开机自启")
        self.check_autostart.setChecked(self.cfg.app.autostart and is_autostart_enabled())
        self.check_autostart.stateChanged.connect(self.toggle_autostart)
        row.addWidget(self.check_autostart)

        self.check_daily = QCheckBox("每日定时扫描")
        self.check_daily.setChecked(self.cfg.app.daily_scan_enabled)
        self.check_daily.stateChanged.connect(self.toggle_daily)
        row.addWidget(self.check_daily)

        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        hour, minute = (self.cfg.scan.daily_scan_time or "09:00").split(":")
        self.time_edit.setTime(dt.time(int(hour), int(minute)))
        self.time_edit.timeChanged.connect(self.change_scan_time)
        row.addWidget(self.time_edit)

        self.btn_scan = QPushButton("立即执行")
        self.btn_scan.setMinimumHeight(32)
        self.btn_scan.clicked.connect(self.run_scan)
        row.addWidget(self.btn_scan)

        self.btn_export = QPushButton("导出当前清单")
        self.btn_export.clicked.connect(self.export_current)
        row.addWidget(self.btn_export)

        self.btn_logs = QPushButton("提醒日志")
        self.btn_logs.clicked.connect(self.open_logs)
        row.addWidget(self.btn_logs)

        self.btn_about = QPushButton("关于")
        self.btn_about.clicked.connect(self.show_about)
        row.addWidget(self.btn_about)
        row.addStretch(1)
        return group

    def _build_stats(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.card_pending = StatCard("今日待提醒", "0")
        self.card_sent = StatCard("今日已发邮件", "0", "#1f7a3f")
        self.card_failed = StatCard("今日失败", "0", "#b3261e")
        self.card_amount = StatCard("累计逾期金额(CNY)", "¥0.00", "#8a5a00")
        for card in (self.card_pending, self.card_sent, self.card_failed, self.card_amount):
            card.setMinimumWidth(200)
            row.addWidget(card)
        return row

    def _build_log_area(self) -> QGroupBox:
        group = QGroupBox("运行日志")
        layout = QVBoxLayout(group)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QTextEdit.NoWrap)
        self.log_view.setStyleSheet("font-family:Consolas,Menlo,monospace; font-size:12px;")
        layout.addWidget(self.log_view)

        handler = QtLogHandler(self.append_log)
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s",
                                               datefmt="%H:%M:%S"))
        logging.getLogger("spv_reminder").addHandler(handler)
        return group

    def append_log(self, text: str) -> None:
        self.log_view.append(text)
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_view.setTextCursor(cursor)

    # -------------------------------------------------------------- 托盘/定时器
    def _build_tray(self) -> None:
        # 未打包时无资源图标，生成一个纯色图标避免托盘无图标告警
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor("#1f4e79"))
        self.tray = QSystemTrayIcon(QIcon(pixmap), self)
        self.tray.setToolTip("SPV 逾期账单提醒")
        menu = QMenu()
        menu.addAction(QAction("立即扫描", self, triggered=self.run_scan))
        menu.addAction(QAction("显示主窗口", self, triggered=self.showNormal))
        menu.addSeparator()
        menu.addAction(QAction("退出", self, triggered=self.quit_app))
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.showNormal()
            if reason == QSystemTrayIcon.DoubleClick else None)
        self.tray.show()

    def _start_timers(self) -> None:
        self.tick_timer = QTimer(self)
        self.tick_timer.setInterval(1000 * 30)  # 每 30s 检查一次定时触发点
        self.tick_timer.timeout.connect(self.on_tick)
        self.tick_timer.start()

    def on_tick(self) -> None:
        if self.scheduler.should_run():
            logger.info("到达定时扫描时间 %s，自动执行", self.cfg.scan.daily_scan_time)
            self.scheduler.mark_run()
            self.run_scan()
        self.refresh_status()

    # ------------------------------------------------------------------ 刷新
    def refresh_user(self) -> None:
        user = self.user
        self.user_label.setText(f"当前操作人：{user.display}" if user else "未登录")
        self.btn_logout.setEnabled(user is not None)
        self.btn_login.setEnabled(user is None)

    def refresh_source(self) -> None:
        ok, message = self.datasource.health_check()
        color = "#1f7a3f" if ok else "#b3261e"
        self.source_light.setStyleSheet(f"color:{color}; font-size:16px;")
        self.source_light.setToolTip(message)
        self.source_label.setText(self.datasource.describe())

    def refresh_stats(self) -> None:
        business_date = business_date_now(self.cfg.scan.timezone_offset_hours)
        stats = self.scanner.stats(business_date)
        self.card_pending.set_value(str(stats["pending"]))
        self.card_sent.set_value(str(stats["sent"]))
        self.card_failed.set_value(str(stats["failed"]))
        self.card_amount.set_value(f"¥{fmt_money(stats['amount_cny'])}")

    def refresh_status(self) -> None:
        business_date = business_date_now(self.cfg.scan.timezone_offset_hours)
        last = self.log_repo.last_scan() if hasattr(self.log_repo, "last_scan") else None
        next_run = self.scheduler.next_run_at()
        enabled = "已开启" if self.scheduler.enabled else "已关闭"
        self.status_bar.showMessage(
            f"业务日期 {business_date}　|　上次扫描 {last:%Y-%m-%d %H:%M:%S}"
            if last else f"业务日期 {business_date}　|　尚未扫描",
            3000)
        self.status_bar.showMessage(
            f"业务日期 {business_date}　|　上次扫描 "
            f"{last.strftime('%Y-%m-%d %H:%M:%S') if last else '—'}　|　"
            f"下次定时 {next_run:%Y-%m-%d %H:%M}（{enabled}）　|　"
            f"操作人 {self.user.user_id if self.user else '—'}")

    # ------------------------------------------------------------------ 动作
    def run_scan(self) -> None:
        if getattr(self, "_worker", None) and self._worker.isRunning():
            QMessageBox.information(self, "提示", "扫描正在进行中，请稍候。")
            return
        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("扫描中…")
        self._worker = ScanWorker(self.scanner, parent=self)
        self._worker.finished.connect(self.on_scan_finished)
        self._worker.failed.connect(self.on_scan_failed)
        self._worker.start()

    def on_scan_finished(self, report: ScanReport) -> None:
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("立即执行")
        self.last_report = report
        self.refresh_stats()
        self.refresh_status()
        self.append_log(f"[扫描] {report.summary()}")

        if getattr(self.log_repo, "record_scan", None):
            self.log_repo.record_scan(report.business_date.isoformat(),
                                      self.datasource.source_hash(), report.hit_count)

        items = self._popup_items(report)
        if not items:
            QMessageBox.information(self, "扫描完成", "未发现需要提醒的逾期账单。")
            return

        dialog = ReminderPopupDialog(report, self.scanner, self.cfg, self)
        if dialog.exec() and dialog.selected_mails:
            self.open_mail_dialog(dialog.selected_mails)

    def _popup_items(self, report: ScanReport):
        """弹窗清单 = 本轮命中 ∪ 历史未关闭且未发信的账单（含升级标红）。"""
        bills = list(report.bills)
        known = {b.raw.get("_row_key") or b.invoice_no for b in bills}
        for bill, _log in self.scanner.pending_queue(report.business_date, include_escalated=True):
            key = bill.raw.get("_row_key") or bill.invoice_no
            if key not in known:
                bills.append(bill)
                known.add(key)
        return bills

    def open_mail_dialog(self, bills) -> None:
        mails = self.composer.compose(bills, language=self.cfg.app.language)
        if not mails:
            QMessageBox.information(self, "提示", "没有可生成邮件的账单。")
            return
        dialog = MailPreviewDialog(mails, self.sender, self.log_repo, self.composer, self)
        dialog.exec()
        self.refresh_stats()

    def on_scan_failed(self, message: str) -> None:
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("立即执行")
        QMessageBox.critical(self, "扫描失败", message)

    def export_current(self) -> None:
        report = self.last_report
        if report is None or not len(report.hits):
            QMessageBox.information(self, "提示", "请先执行一次扫描。")
            return
        default = default_export_path("SPV逾期账单", "xlsx",
                                      out_dir=self.cfg.resolve_outbox_dir())
        path, _ = QFileDialog.getSaveFileName(self, "导出逾期清单", default, "Excel (*.xlsx)")
        if not path:
            return
        export_overdue_list(report.hits, path)
        QMessageBox.information(self, "导出完成", f"已导出：\n{path}")

    def open_logs(self) -> None:
        LogViewerDialog(self.log_repo, self).exec()

    def show_about(self) -> None:
        QMessageBox.about(
            self, "关于",
            f"SPV 客户逾期账单提醒工具\n版本 {__version__}\n\n"
            f"逾期阈值 ≥ {self.cfg.scan.first_overdue_days} 天；"
            f"再提醒间隔 {self.cfg.scan.re_remind_interval_days} 天；"
            f"最大 {self.cfg.scan.max_remind_rounds} 轮\n"
            f"目标 BU：{', '.join(self.cfg.scan.target_bu_list)}\n"
            f"数据源：{self.datasource.describe()}\n"
            f"邮件模式：{self.cfg.mail.mode}")

    # ------------------------------------------------------------ 控制区回调
    def toggle_autostart(self) -> None:
        enabled = self.check_autostart.isChecked()
        ok = set_autostart(enabled)
        if not ok:
            QMessageBox.warning(self, "开机自启", "当前平台不支持或写入失败，请手动添加启动项。")
        self.cfg.app.autostart = enabled and ok

    def toggle_daily(self) -> None:
        self.scheduler.enabled = self.check_daily.isChecked()
        self.refresh_status()

    def change_scan_time(self) -> None:
        text = self.time_edit.time().toString("HH:mm")
        self.scheduler.scan_time = self.scheduler._parse_time(text)
        self.cfg.scan.daily_scan_time = text
        self.refresh_status()

    def reload_source(self) -> None:
        if hasattr(self.datasource, "reload"):
            self.datasource.reload()
        self.refresh_source()
        self.append_log(f"[数据源] 已重新加载：{self.datasource.describe()}")

    def do_login(self) -> None:
        if self.auth_provider is None:
            return
        try:
            self.user = self.auth_provider.login()
            self.scanner.user = self.user
            self.refresh_user()
            self.refresh_status()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "登录失败", str(exc))

    def do_logout(self) -> None:
        if self.auth_provider:
            self.auth_provider.logout()
        self.user = None
        self.scanner.user = None
        self.refresh_user()

    # ------------------------------------------------------------------ 关闭
    def quit_app(self) -> None:
        """托盘「退出」：真正结束进程。"""
        self._quitting = True
        from PySide6.QtWidgets import QApplication

        QApplication.quit()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 约定
        if getattr(self, "_quitting", False):
            event.accept()
            return
        self.hide()
        self.tray.showMessage("SPV 逾期提醒", "程序已最小化到托盘，继续后台监控。",
                              QSystemTrayIcon.Information, 2500)
        event.ignore()
