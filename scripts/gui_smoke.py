"""GUI 冒烟测试：无显示器环境下启动应用、执行一次扫描并安全退出。

    QT_QPA_PLATFORM=offscreen python scripts/gui_smoke.py
    xvfb-run -a python scripts/gui_smoke.py        # 有 Xvfb 时可用真实窗口

用于验证「装配 + 扫描 + 弹窗 + 邮件窗口」链路无运行时异常，不阻塞 CI。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from spv_reminder.config import Config
from spv_reminder.ui.app import build_context, first_run_self_check
from spv_reminder.ui.mail_dialog import MailPreviewDialog
from spv_reminder.ui.popup_dialog import ReminderPopupDialog

# 屏蔽阻塞式弹窗，便于自动化冒烟
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.critical = staticmethod(lambda *a, **k: None)
ReminderPopupDialog.exec = lambda self: 0
MailPreviewDialog.exec = lambda self: 0


def main() -> int:
    cfg = Config.load("config.local.yaml")
    problems = first_run_self_check(cfg)
    print("自检问题：", problems or "无")
    scanner, source, repo, auth, user = build_context(cfg)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from spv_reminder.ui.main_window import MainWindow

    window = MainWindow(cfg, scanner, source, repo, user, auth)
    window.show()
    window.run_scan()

    def finish() -> None:
        report = window.last_report
        print("扫描结果：", report.summary() if report else "无")
        print("统计卡片：", window.card_pending.value_label.text(),
              window.card_sent.value_label.text())
        app.quit()

    QTimer.singleShot(6000, finish)
    code = app.exec()
    print("GUI 冒烟结束，退出码", code)
    return 0


if __name__ == "__main__":
    sys.exit(main())
