"""领域模型：账单 Bill、提醒日志 ReminderLog、催款邮件 DunningMail。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Optional

from .constants import (
    C_AGING,
    C_AMOUNT,
    C_AMOUNT_CNY,
    C_BD,
    C_BU,
    C_CASE_CATEGORY,
    C_CC_CLIENT,
    C_COMMENTS,
    C_COMPANY_CODE,
    C_COMPANY_NAME,
    C_CREDIT_RANK,
    C_CUST_CURR,
    C_CUSTOMER_CODE,
    C_CUSTOMER_NAME,
    C_DIRECTOR,
    C_DISPUTE_CATEGORY,
    C_DUNNING_BLOCK,
    C_DUE_DATE,
    C_FOLLOW_UP_TEAM,
    C_INVOICE_DATE,
    C_INVOICE_NO,
    C_LAST_FOLLOW_UP,
    C_MAPPING,
    C_ORG_L2,
    C_ORG_L5,
    C_OWNER,
    C_PAYMENT_PLAN,
    C_PO_NUMBER,
    C_PROJECT_ID,
    C_PS_PM,
    C_SPV_CUSTOMER,
    C_BILLED,
    C_CN_INVOICE,
    C_TO_CLIENT,
)
from .utils import norm_text, parse_date, to_float


@dataclass
class Bill:
    """一条账单记录（源表一行 + 计算列）。

    ``raw`` 保留原始行全部 44 字段，导出与模板渲染时可取用未建模字段。
    """

    invoice_no: str = ""
    customer_code: str = ""
    customer_name: str = ""
    company_name: str = ""
    company_code: str = ""
    bu: str = ""
    project_id: str = ""
    po_number: str = ""
    invoice_date: Optional[dt.date] = None
    due_date: Optional[dt.date] = None
    aging: str = ""
    currency: str = ""
    amount: float = 0.0
    amount_cny: float = 0.0
    to_client: str = ""
    cc_client: str = ""
    owner: str = ""
    ps_pm: str = ""
    bd: str = ""
    director: str = ""
    case_category: str = ""
    dispute_category: str = ""
    comments: str = ""
    credit_rank: str = ""
    dunning_block: str = ""
    cn_invoice: str = ""
    billed_flag: str = ""
    spv_customer: str = ""
    mapping: str = ""
    follow_up_team: str = ""
    org_l5: str = ""
    org_l2: str = ""
    payment_plan: str = ""
    last_follow_up: Optional[dt.date] = None

    overdue_days: Optional[int] = None
    remind_round: int = 0
    is_escalated: bool = False

    raw: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ 构造
    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Bill":
        return cls(
            invoice_no=norm_text(row.get(C_INVOICE_NO)),
            customer_code=norm_text(row.get(C_CUSTOMER_CODE)),
            customer_name=norm_text(row.get(C_CUSTOMER_NAME)),
            company_name=norm_text(row.get(C_COMPANY_NAME)),
            company_code=norm_text(row.get(C_COMPANY_CODE)),
            bu=norm_text(row.get(C_BU)),
            project_id=norm_text(row.get(C_PROJECT_ID)),
            po_number=norm_text(row.get(C_PO_NUMBER)),
            invoice_date=parse_date(row.get(C_INVOICE_DATE)),
            due_date=parse_date(row.get(C_DUE_DATE)),
            aging=norm_text(row.get(C_AGING)),
            currency=norm_text(row.get(C_CUST_CURR)),
            amount=to_float(row.get(C_AMOUNT)),
            amount_cny=to_float(row.get(C_AMOUNT_CNY)),
            to_client=norm_text(row.get(C_TO_CLIENT)),
            cc_client=norm_text(row.get(C_CC_CLIENT)),
            owner=norm_text(row.get(C_OWNER)),
            ps_pm=norm_text(row.get(C_PS_PM)),
            bd=norm_text(row.get(C_BD)),
            director=norm_text(row.get(C_DIRECTOR)),
            case_category=norm_text(row.get(C_CASE_CATEGORY)),
            dispute_category=norm_text(row.get(C_DISPUTE_CATEGORY)),
            comments=norm_text(row.get(C_COMMENTS)),
            credit_rank=norm_text(row.get(C_CREDIT_RANK)),
            dunning_block=norm_text(row.get(C_DUNNING_BLOCK)),
            cn_invoice=norm_text(row.get(C_CN_INVOICE)),
            billed_flag=norm_text(row.get(C_BILLED)),
            spv_customer=norm_text(row.get(C_SPV_CUSTOMER)),
            mapping=norm_text(row.get(C_MAPPING)),
            follow_up_team=norm_text(row.get(C_FOLLOW_UP_TEAM)),
            org_l5=norm_text(row.get(C_ORG_L5)),
            org_l2=norm_text(row.get(C_ORG_L2)),
            payment_plan=norm_text(row.get(C_PAYMENT_PLAN)),
            last_follow_up=parse_date(row.get(C_LAST_FOLLOW_UP)),
            raw=dict(row),
        )

    @property
    def key(self) -> str:
        """业务主键（账单号）。"""
        return self.invoice_no

    @property
    def has_dispute(self) -> bool:
        """是否争议账单（用于弹窗角标 ⚠）。"""
        category = self.case_category.strip()
        if not category or category == "未达催款节点":
            return False
        return True

    @property
    def has_payment_plan(self) -> bool:
        """是否已有还款计划（用于 📅 角标与降优先级）。"""
        return bool(self.payment_plan.strip())

    def to_display_dict(self) -> dict[str, Any]:
        """弹窗/导出用字典（展示列 + 计算列）。"""
        return {
            C_COMPANY_NAME: self.company_name,
            C_COMPANY_CODE: self.company_code,
            C_CUSTOMER_CODE: self.customer_code,
            C_CUSTOMER_NAME: self.customer_name,
            C_PROJECT_ID: self.project_id,
            C_PO_NUMBER: self.po_number,
            C_INVOICE_DATE: self.invoice_date.isoformat() if self.invoice_date else "",
            C_MAPPING: self.mapping,
            C_INVOICE_NO: self.invoice_no,
            C_DUE_DATE: self.due_date.isoformat() if self.due_date else "",
            C_AGING: self.aging,
            "Overdue Days": self.overdue_days if self.overdue_days is not None else "",
            C_CUST_CURR: self.currency,
            C_AMOUNT: self.amount,
            C_AMOUNT_CNY: self.amount_cny,
            C_TO_CLIENT: self.to_client,
            C_CC_CLIENT: self.cc_client,
        }


@dataclass
class ReminderLog:
    """提醒日志（设计文档 §4.2）。"""

    invoice_no: str = ""
    customer_code: str = ""
    customer_name: str = ""
    bu: str = ""
    remind_round: int = 0
    remind_date: Optional[dt.date] = None
    status: str = "PENDING"
    popup_shown: bool = False
    popup_shown_at: Optional[dt.datetime] = None
    mail_generated: bool = False
    mail_sent: bool = False
    mail_to: str = ""
    mail_cc: str = ""
    sent_at: Optional[dt.datetime] = None
    fail_reason: str = ""
    operator: str = ""
    amount_cny: float = 0.0
    id: Optional[int] = None
    created_at: Optional[dt.datetime] = None
    updated_at: Optional[dt.datetime] = None


@dataclass
class DunningMail:
    """一封催款邮件（按客户聚合）。"""

    customer_code: str = ""
    customer_name: str = ""
    to_addrs: list[str] = field(default_factory=list)
    cc_addrs: list[str] = field(default_factory=list)
    subject: str = ""
    html_body: str = ""
    text_body: str = ""
    invoices: list[Bill] = field(default_factory=list)
    language: str = "zh"
    bu: str = ""

    @property
    def total_amount_cny(self) -> float:
        return round(sum(b.amount_cny for b in self.invoices), 2)

    @property
    def max_overdue_days(self) -> int:
        return max((b.overdue_days or 0) for b in self.invoices) if self.invoices else 0


@dataclass
class SendResult:
    """邮件发送结果。"""

    success: bool
    message: str = ""
    sent_at: Optional[dt.datetime] = None
    path: str = ""  # FileMailSender 落盘路径
