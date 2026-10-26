"""催款邮件生成器：Jinja2 模板渲染 + 按客户聚合（设计文档 §6.3 / §6.4）。"""

from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Iterable

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from ..models import Bill, DunningMail
from ..utils import fmt_money, split_emails
from .base import MailComposer

logger = logging.getLogger(__name__)

SUBJECT_ZH = "【WuXi AppTec】Payment Reminder – Overdue Invoice(s) – {customer}"
SUBJECT_EN = "【WuXi AppTec】Payment Reminder – Overdue Invoice(s) – {customer}"


class JinjaMailComposer(MailComposer):
    """模板文件化渲染，支持按语言 / BU 定制变体。

    模板查找顺序（``templates/`` 目录）：
    1. ``dunning_{template}_{bu}.html``
    2. ``dunning_{template}.html``
    3. ``dunning_default.html``
    """

    def __init__(self, template_dir: str, template_name: str = "default_dunning",
                 sender_name: str = "WuXi AppTec AR Team"):
        self.template_dir = template_dir
        self.template_name = (
            template_name.replace("dunning_", "").replace("default", "default_dunning")
            if template_name.startswith("dunning_") else template_name)
        self.sender_name = sender_name
        self.env = Environment(
            loader=FileSystemLoader(template_dir, encoding="utf-8"),
            autoescape=select_autoescape(["html", "xml"]),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters["money"] = fmt_money

    # ------------------------------------------------------------------ 渲染
    def compose(self, bills: Iterable[Bill], language: str = "zh") -> list[DunningMail]:
        groups: dict[str, list[Bill]] = {}
        for bill in bills:
            key = bill.customer_code or bill.customer_name or bill.invoice_no
            groups.setdefault(key, []).append(bill)

        mails: list[DunningMail] = []
        for key, items in groups.items():
            items = sorted(items, key=lambda b: (b.due_date or dt.date.min))
            first = items[0]
            subject = (SUBJECT_ZH if language == "zh" else SUBJECT_EN).format(
                customer=first.customer_name or first.customer_code)
            html = self.render(first, items, language)
            mails.append(DunningMail(
                customer_code=first.customer_code,
                customer_name=first.customer_name,
                to_addrs=split_emails(first.to_client),
                cc_addrs=split_emails(first.cc_client),
                subject=subject,
                html_body=html,
                text_body=self._to_plain_text(items, first, language),
                invoices=items,
                language=language,
                bu=first.bu,
            ))
        return mails

    def render(self, customer_bill: Bill, items: list[Bill], language: str = "zh") -> str:
        template = self._load_template(customer_bill.bu)
        contact = customer_bill.ps_pm or customer_bill.owner or customer_bill.bd
        return template.render(
            customer_name=customer_bill.customer_name,
            customer_code=customer_bill.customer_code,
            company_name=customer_bill.company_name,
            invoices=items,
            total_cny=round(sum(b.amount_cny for b in items), 2),
            total_original=round(sum(b.amount for b in items), 2),
            currency=customer_bill.currency,
            max_overdue=max((b.overdue_days or 0) for b in items),
            today=dt.date.today(),
            sender_name=self.sender_name,
            contact=contact,
            owner=customer_bill.owner,
            lang=language,
            comments=customer_bill.comments,
        )

    # ------------------------------------------------------------------ 内部
    def _load_template(self, bu: str):
        candidates = []
        if bu:
            safe_bu = "".join(ch if ch.isalnum() else "_" for ch in bu)
            candidates.append(f"dunning_{self.template_name}_{safe_bu}.html")
        candidates.append(f"dunning_{self.template_name}.html")
        candidates.append("dunning_default.html")
        for name in candidates:
            path = os.path.join(self.template_dir, name)
            if os.path.exists(path):
                return self.env.get_template(name)
        raise FileNotFoundError(
            f"未找到邮件模板，已尝试：{candidates}（目录：{self.template_dir}）")

    @staticmethod
    def _to_plain_text(items: list[Bill], first: Bill, language: str) -> str:
        lines = [
            f"Dear {first.customer_name}," if language != "zh" else f"{first.customer_name} 您好，",
            "以下账单已逾期，请协助安排付款："
            if language == "zh" else "The following invoices are overdue. Please arrange payment:",
        ]
        for bill in items:
            lines.append(
                f"- {bill.invoice_no} | Due {bill.due_date} | Overdue {bill.overdue_days}d | "
                f"{fmt_money(bill.amount, bill.currency)} (CNY {fmt_money(bill.amount_cny)})"
            )
        lines.append(f"Total (CNY): {fmt_money(sum(b.amount_cny for b in items))}")
        lines.append("Best regards,\nWuXi AppTec AR Team")
        return "\n".join(lines)
