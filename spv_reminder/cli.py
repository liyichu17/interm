"""命令行入口：离线跑通「扫描 → 日志 → 导出 → 生成邮件」全链路。

用法示例::

    python -m spv_reminder.cli scan                       # 按 config.yaml 扫描（写日志）
    python -m spv_reminder.cli scan --dry-run             # 只看结果不写日志
    python -m spv_reminder.cli scan --bu TIDES,RCS        # 临时覆盖 BU
    python -m spv_reminder.cli scan --business-date 2026-10-26
    python -m spv_reminder.cli export --out ./逾期清单.xlsx
    python -m spv_reminder.cli mail --send                # 生成并（按 mail.mode）发送
    python -m spv_reminder.cli logs --status SUCCESS
    python -m spv_reminder.cli stats
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from . import __version__
from .config import Config
from .datasource import build_data_source, LocalXlsxSource
from .repository import build_log_repository
from .service import export_logs, export_overdue_list
from .service.scanner import OverdueScanner
from .utils import business_date_now, fmt_money, setup_logging


def build_context(args) -> tuple[Config, OverdueScanner]:
    cfg = Config.load(getattr(args, "config", None))
    for item in getattr(args, "set", []) or []:
        if "=" not in item:
            raise SystemExit(f"--set 格式应为 section.key=value，收到：{item}")
        key, value = item.split("=", 1)
        cfg.apply_overrides({key: value})
    setup_logging(cfg.resolve_log_dir(), console=not getattr(args, "quiet", False))

    source = build_data_source(cfg)
    fallback = None
    if cfg.datasource.type == "database":
        fallback = LocalXlsxSource(cfg.resolve_xlsx_path(), cfg.datasource.xlsx_sheet)
    repo = build_log_repository(cfg)
    scanner = OverdueScanner(cfg, source, repo, fallback_source=fallback)
    return cfg, scanner


def _parse_date(text: str | None) -> dt.date | None:
    if not text:
        return None
    return dt.date.fromisoformat(text)


def cmd_scan(args) -> int:
    cfg, scanner = build_context(args)
    business_date = _parse_date(args.business_date) or business_date_now(
        cfg.scan.timezone_offset_hours)
    report = scanner.scan(business_date=business_date, write_log=not args.dry_run)
    if report.degraded:
        print(f"[降级] 主数据源不可用，已回退本地 xlsx：{report.degrade_reason}")

    print(f"业务日期：{report.business_date}　数据源：{report.data_source}")
    print(report.summary())
    if len(report.hits):
        columns = ["Customer Name", "Invoice NO.", "Due Date", "Overdue Days",
                   "Amount in CNY", "BU", "remind_round", "Owner"]
        columns = [c for c in columns if c in report.hits.columns]
        print("\n待提醒账单：")
        print(report.hits[columns].to_string(index=False))
    else:
        print("\n无待提醒账单。")

    if len(report.skipped):
        print(f"\n跳过 {len(report.skipped)} 条（逾期但被排除/未到下一轮）：")
        cols = [c for c in ["Customer Name", "Invoice NO.", "Overdue Days",
                            "skip_reason"] if c in report.skipped.columns]
        print(report.skipped[cols].to_string(index=False))

    stats = scanner.stats(business_date)
    print(f"\n当日统计：待提醒 {stats['pending']} / 已发 {stats['sent']} / "
          f"失败 {stats['failed']} / 金额 ¥{fmt_money(stats['amount_cny'])}")

    if args.export:
        path = export_overdue_list(report.hits, args.export)
        print(f"\n已导出：{path}")
    return 0


def cmd_export(args) -> int:
    cfg, scanner = build_context(args)
    business_date = _parse_date(args.business_date)
    report = scanner.scan(business_date=business_date, write_log=False)
    from .service.exporter import default_export_path

    out = args.out or default_export_path(
        "SPV逾期账单", "xlsx", out_dir=cfg.resolve_outbox_dir())
    path = export_overdue_list(report.hits, out)
    print(f"已导出 {report.hit_count} 条 → {path}")
    return 0


def cmd_mail(args) -> int:
    """基于待处理队列生成（并可选发送）催款邮件，回写日志。"""
    cfg, scanner = build_context(args)
    from .config import project_root
    from .constants import RemindStatus
    from .mail import build_mail_composer, build_mail_sender

    business_date = _parse_date(args.business_date)
    queue = scanner.pending_queue(business_date)
    if not queue:
        print("待处理队列为空：请先执行 scan，或当日提醒均已发送完成。")
        return 0

    bills = [bill for bill, _ in queue]
    composer = build_mail_composer(cfg, cfg.resolve_template_dir(project_root()))
    sender = build_mail_sender(cfg)
    mails = composer.compose(bills, language=cfg.app.language)
    print(f"按客户聚合生成 {len(mails)} 封邮件（共 {len(bills)} 张账单）")

    sent_count = 0
    for mail in mails:
        result = None
        if args.send and (mail.to_addrs or args.force):
            result = sender.send(mail)
            sent_count += 1 if result.success else 0
        target = (result.path if result and result.path
                  else (result.message if result else "（未发送，仅生成）"))
        print(f"- {mail.customer_name} | 收件人：{', '.join(mail.to_addrs) or '空'} | "
              f"金额 ¥{fmt_money(mail.total_amount_cny)} | {target}")

        # 回写每张账单对应日志的邮件状态
        logs_by_key = {log.invoice_no: log for _, log in queue}
        for bill in mail.invoices:
            log = logs_by_key.get(bill.raw.get("_row_key") or bill.invoice_no)
            if log is None:
                continue
            log.mail_generated = True
            if result and result.success:
                log.mail_sent = True
                log.sent_at = result.sent_at
                log.status = RemindStatus.SUCCESS
                log.mail_to = ", ".join(mail.to_addrs)
                log.mail_cc = ", ".join(mail.cc_addrs)
            elif result:
                log.status = RemindStatus.FAILED
                log.fail_reason = result.message
            if not args.dry_run:
                scanner.log_repo.save(log)
    print(f"发送成功 {sent_count} 封")
    return 0


def cmd_logs(args) -> int:
    cfg, _ = build_context(args)
    repo = build_log_repository(cfg)
    filters = {"status": args.status, "invoice_no": args.invoice,
               "date_from": args.date_from, "date_to": args.date_to}
    df = repo.export({k: v for k, v in filters.items() if v})
    if args.out:
        print(f"已导出 {len(df)} 条 → {export_logs(df, args.out)}")
    if len(df):
        cols = [c for c in ["invoice_no", "customer_name", "remind_round", "remind_date",
                            "status", "mail_sent", "amount_cny", "fail_reason"]
                if c in df.columns]
        print(df[cols].to_string(index=False))
    else:
        print("无日志记录。")
    return 0


def cmd_stats(args) -> int:
    cfg, scanner = build_context(args)
    business_date = _parse_date(args.business_date) or business_date_now(
        cfg.scan.timezone_offset_hours)
    stats = scanner.stats(business_date)
    print(f"业务日期：{business_date}")
    print(f"  待提醒：{stats['pending']}")
    print(f"  已发邮件：{stats['sent']}")
    print(f"  失败：{stats['failed']}")
    print(f"  累计逾期金额：¥{fmt_money(stats['amount_cny'])}")
    return 0


def cmd_info(args) -> int:
    cfg, scanner = build_context(args)
    ok, msg = scanner.datasource.health_check()
    print(f"版本：{__version__}")
    print(f"数据源：{scanner.datasource.describe()}")
    print(f"数据源状态：{'可用' if ok else '不可用'} {msg}")
    try:
        df = scanner.datasource.fetch_bills()
        print(f"账单行数：{len(df)}　列数：{len(df.columns)}")
    except Exception as exc:  # noqa: BLE001
        print(f"读取失败：{exc}")
    print(f"日志仓库：{cfg.log_repo.type}")
    print(f"扫描配置：逾期≥{cfg.scan.first_overdue_days}天，间隔{cfg.scan.re_remind_interval_days}天，"
          f"最多{cfg.scan.max_remind_rounds}轮，BU={cfg.scan.target_bu_list}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # 公共参数同时支持放在子命令前后（子命令侧用 SUPPRESS，避免覆盖全局值）
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=argparse.SUPPRESS,
                        help="配置文件路径（默认 ./config.yaml）")
    common.add_argument("--set", action="append", metavar="SECTION.KEY=VALUE",
                        default=argparse.SUPPRESS,
                        help="临时覆盖配置，如 --set scan.max_remind_rounds=2")
    common.add_argument("--business-date", default=argparse.SUPPRESS,
                        help="业务日期 yyyy-mm-dd（默认取当前 UTC+8 日期）")
    common.add_argument("--bu", default=argparse.SUPPRESS, help="临时覆盖目标 BU，逗号分隔")
    common.add_argument("--quiet", action="store_true", default=argparse.SUPPRESS,
                        help="不输出运行日志到控制台")

    parser = argparse.ArgumentParser(
        prog="spv_reminder", description="SPV 客户逾期账单提醒工具", parents=[common])
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="扫描逾期账单并写提醒日志", parents=[common])
    p_scan.add_argument("--dry-run", action="store_true", help="只扫描不写日志")
    p_scan.add_argument("--export", help="扫描后导出清单到指定 xlsx")
    p_scan.set_defaults(func=cmd_scan)

    p_export = sub.add_parser("export", help="导出当前逾期清单", parents=[common])
    p_export.add_argument("--out", help="输出文件路径")
    p_export.set_defaults(func=cmd_export)

    p_mail = sub.add_parser("mail", help="生成催款邮件", parents=[common])
    p_mail.add_argument("--send", action="store_true", help="按 mail.mode 发送（file/smtp）")
    p_mail.add_argument("--force", action="store_true", help="收件人为空也尝试发送")
    p_mail.add_argument("--dry-run", action="store_true")
    p_mail.set_defaults(func=cmd_mail)

    p_logs = sub.add_parser("logs", help="查询/导出提醒日志", parents=[common])
    p_logs.add_argument("--status", help="过滤状态")
    p_logs.add_argument("--invoice", help="账单号模糊匹配")
    p_logs.add_argument("--date-from")
    p_logs.add_argument("--date-to")
    p_logs.add_argument("--out", help="导出路径（xlsx/csv）")
    p_logs.set_defaults(func=cmd_logs)

    p_stats = sub.add_parser("stats", help="当日统计", parents=[common])
    p_stats.set_defaults(func=cmd_stats)

    p_info = sub.add_parser("info", help="显示数据源与配置自检信息", parents=[common])
    p_info.set_defaults(func=cmd_info)

    args = parser.parse_args(argv)
    if getattr(args, "bu", None):
        overridden = list(getattr(args, "set", []) or [])
        args.set = overridden + [f"scan.target_bu_list={args.bu}"]
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
