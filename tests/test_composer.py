"""邮件生成单元测试：按客户聚合、模板渲染、本地 .eml 落盘。"""

from __future__ import annotations

import datetime as dt

import pytest

from spv_reminder.config import project_root
from spv_reminder.mail import JinjaMailComposer, FileMailSender
from spv_reminder.models import Bill


def _bill(**overrides) -> Bill:
    bill = Bill(
        invoice_no="INV-001", customer_code="CUST-1", customer_name="客户甲",
        company_name="测试主体", bu="TIDES", project_id="PRJ-1", po_number="PO-1",
        invoice_date=dt.date(2026, 8, 1), due_date=dt.date(2026, 9, 1),
        currency="CNY", amount=1000.0, amount_cny=1000.0,
        to_client="client@example.com", cc_client="cc@example.com",
        owner="staff1", ps_pm="pm@example.com", overdue_days=55, remind_round=1,
    )
    for key, value in overrides.items():
        setattr(bill, key, value)
    bill.raw = {"_row_key": bill.invoice_no}
    return bill


@pytest.fixture
def composer() -> JinjaMailComposer:
    from spv_reminder.config import Config

    cfg = Config.load()
    return JinjaMailComposer(cfg.resolve_template_dir(project_root()),
                             "default_dunning", "WuXi AppTec AR Team")


def test_compose_groups_by_customer(composer):
    bills = [_bill(), _bill(invoice_no="INV-002", amount=500, amount_cny=500),
             _bill(customer_code="CUST-2", customer_name="客户乙", invoice_no="INV-003")]
    mails = composer.compose(bills, language="zh")
    assert len(mails) == 2
    first = next(m for m in mails if m.customer_code == "CUST-1")
    assert len(first.invoices) == 2
    assert first.total_amount_cny == 1500.0
    assert first.max_overdue_days == 55


def test_rendered_mail_contains_key_elements(composer):
    mail = composer.compose([_bill(comments="客户承诺本月付款")], language="zh")[0]
    assert mail.subject.startswith("【WuXi AppTec】Payment Reminder")
    assert "客户甲" in mail.subject
    assert mail.to_addrs == ["client@example.com"]
    assert mail.cc_addrs == ["cc@example.com"]
    for token in ("INV-001", "2026-09-01", "55", "1,000.00", "客户承诺本月付款"):
        assert token in mail.html_body
    assert "客户甲" in mail.text_body


def test_english_variant(composer):
    mail = composer.compose([_bill()], language="en")[0]
    assert "Dear 客户甲" in mail.html_body


def test_file_sender_writes_eml(tmp_path):
    sender = FileMailSender(str(tmp_path))
    mail = composer_fallback_mail()
    result = sender.send(mail)
    assert result.success and result.path.endswith(".eml")
    content = open(result.path, encoding="utf-8", errors="ignore").read()
    assert content.startswith("Subject:")   # 中文主题按 RFC2047 编码，仅校验头存在
    assert "client@example.com" in content
    assert "<p>test</p>" in content        # HTML 正文作为 alternative 写入


def composer_fallback_mail():
    from spv_reminder.models import DunningMail

    return DunningMail(customer_code="CUST-1", customer_name="客户甲",
                       to_addrs=["client@example.com"], cc_addrs=["cc@example.com"],
                       subject="【WuXi AppTec】Payment Reminder – 客户甲",
                       html_body="<p>test</p>", text_body="test", invoices=[_bill()])
