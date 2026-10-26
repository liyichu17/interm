"""GUI 启动装配：配置 → 组件 → 首次自检 → 主窗口。"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Optional

from .. import __version__
from ..auth import build_auth_provider
from ..config import Config, app_data_dir, project_root
from ..datasource import LocalXlsxSource, build_data_source
from ..repository import build_log_repository
from ..service.scanner import OverdueScanner
from ..utils import business_date_now, setup_logging
from .main_window import MainWindow


def first_run_self_check(cfg: Config) -> list[str]:
    """首次运行自检：配置 / 模板 / 日志目录 / 数据源（§7 打包部署）。"""
    problems = []
    if not os.path.exists(cfg.resolve_xlsx_path()) and cfg.datasource.type == "xlsx":
        problems.append(f"账单文件不存在：{cfg.resolve_xlsx_path()}")
    template_dir = cfg.resolve_template_dir(project_root())
    if not os.path.isdir(template_dir):
        problems.append(f"邮件模板目录缺失：{template_dir}")
    elif not os.path.exists(os.path.join(template_dir, "dunning_default.html")):
        problems.append("缺少默认邮件模板 dunning_default.html")
    for directory in (cfg.resolve_log_dir(), cfg.resolve_outbox_dir()):
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            problems.append(f"目录不可写：{directory}（{exc}）")
    return problems


def build_context(cfg: Config) -> tuple[OverdueScanner, object, object, object, object]:
    """按配置装配数据源 / 日志仓库 / 鉴权 / 扫描器。"""
    source = build_data_source(cfg)
    fallback = None
    if cfg.datasource.type == "database":
        fallback = LocalXlsxSource(cfg.resolve_xlsx_path(), cfg.datasource.xlsx_sheet)
    repo = build_log_repository(cfg)
    auth = build_auth_provider(cfg)
    user = auth.login() if not cfg.auth.sso_enabled else None
    scanner = OverdueScanner(cfg, source, repo, fallback_source=fallback, user=user)
    return scanner, source, repo, auth, user


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="SPV 客户逾期账单提醒工具（GUI）")
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--minimized", action="store_true",
                        help="开机自启模式：静默驻留，同日已扫描则跳过弹窗")
    parser.add_argument("--scan-now", action="store_true", help="启动后立即执行一次扫描")
    args = parser.parse_args(argv)

    cfg = Config.load(args.config)
    setup_logging(cfg.resolve_log_dir(),
                  level=getattr(logging, cfg.app.log_level.upper(), logging.INFO),
                  console=False)
    logger = logging.getLogger(__name__)
    logger.info("启动 SPV 逾期提醒工具 v%s（数据目录：%s）", __version__, app_data_dir())

    for problem in first_run_self_check(cfg):
        logger.warning("自检问题：%s", problem)

    scanner, source, repo, auth, user = build_context(cfg)

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("SPV Overdue Reminder")
    app.setStyle("Fusion")

    window = MainWindow(cfg, scanner, source, repo, user, auth)
    if args.minimized:
        # 开机自启：同日已用同一数据源成功扫描则跳过（§3.3 防重复）
        business_date = business_date_now(cfg.scan.timezone_offset_hours)
        if hasattr(repo, "scanned_today") and repo.scanned_today(
                business_date.isoformat(), source.source_hash()):
            logger.info("业务日期 %s 已扫描过同一数据源，开机自启跳过", business_date)
        else:
            window.run_scan()
        window.hide()
    else:
        window.show()
        if args.scan_now:
            window.run_scan()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
