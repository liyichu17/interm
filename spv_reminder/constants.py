"""字段常量与枚举定义。

字段名与 data_part.xlsx / 设计文档 §4.1 保持逐一对齐，避免各处硬编码字符串。
"""

# ---------------------------------------------------------------- 数据源字段
C_ORG_L5 = "OrgL5"
C_BU = "BU"
C_IC = "IC"
C_COMPANY_NAME = "Company Name"
C_COMPANY_CODE = "Company Code"
C_CUSTOMER_CODE = "Customer Code"
C_CUSTOMER_NAME = "Customer Name"
C_PROJECT_ID = "Project ID"
C_PO_NUMBER = "PO Number"
C_INVOICE_DATE = "Invoice date/GL date"
C_MAPPING = "Mapping"
C_INVOICE_NO = "Invoice NO."
C_DUE_DATE = "Due Date"
C_AGING = "Aging"
C_CUST_CURR = "Cust Curr"
C_AMOUNT = "Amount 的总和"
C_EX_RATIO = "Ex. Ratio"
C_AMOUNT_CNY = "Amount in CNY"
C_CREDIT_RANK = "Credit Rank"
C_IDM = "IDM"
C_PS_PM = "PS/PM"
C_BD = "BD"
C_DIRECTOR = "Director"
C_TO_CLIENT = "To client"
C_CC_CLIENT = "Cc client"
C_OWNER = "Owner"
C_BROKEN_PTP = "Broken PTP"
C_DUNNING_BLOCK = "Dunning Block"
C_NOTIFICATION_SENT = "Notification Sent"
C_LAST_FOLLOW_UP = "Last Follow-Up Date"
C_FOLLOW_UP_TEAM = "Follow-up team"
C_CASE_CATEGORY = "Case Category"
C_DISPUTE_CATEGORY = "Dispute Category"
C_PAYMENT_PLAN = "Payment plan/Resubmission (yyyy-mm-dd)"
C_COMMENTS = "Comments"
C_CN_INVOICE = "CN/Invoice"
C_BILLED = "Billed/Unbilled"
C_DELIVERY_METHOD = "DELIVERY_METHOD"
C_AUTHORIZED_BY = "AUTHORIZED_BY"
C_SPV_CUSTOMER = "SPV_Customer"
C_ORG_L2 = "OrgL2"
C_RECLASS_TYPE = "CustomerReclassType"
C_RECLASS_ACCOUNT = "ReclassAccountType"
C_RESTATED_AMOUNT = "RestatedAmount"

# ------------------------------------------------------------ 计算/衍生字段
C_OVERDUE_DAYS = "Overdue Days"      # 计算列：业务日期 − Due Date
C_REMIND_ROUND = "remind_round"      # 计算列：本轮提醒轮次
C_ROW_STATE = "state"                # 计算列：PENDING / ROUND_n / ESCALATE

# -------------------------------------------------------------- 弹窗展示列
DISPLAY_COLUMNS = [
    C_COMPANY_NAME,
    C_COMPANY_CODE,
    C_CUSTOMER_CODE,
    C_CUSTOMER_NAME,
    C_PROJECT_ID,
    C_PO_NUMBER,
    C_INVOICE_DATE,
    C_MAPPING,
    C_INVOICE_NO,
    C_DUE_DATE,
    C_AGING,
    C_OVERDUE_DAYS,
    C_CUST_CURR,
    C_AMOUNT,
    C_AMOUNT_CNY,
    C_TO_CLIENT,
    C_CC_CLIENT,
]

# 导出 xlsx 时在展示列基础上补充的内部辅助列
EXPORT_EXTRA_COLUMNS = [
    C_BU,
    C_OWNER,
    C_PS_PM,
    C_BD,
    C_CASE_CATEGORY,
    C_DISPUTE_CATEGORY,
    C_COMMENTS,
    C_REMIND_ROUND,
]

# ------------------------------------------------------------- 业务取值常量
SPV_YES = "Y"
DUNNING_BLOCKED = "X"
CN_CREDIT_NOTE = "Credit Note"
BILLED = "Billed"
UNBILLED = "Unbilled"

# Case Category 中代表「无争议/正常」的值，用于行内角标判定
NEUTRAL_CASE_CATEGORIES = {"未达催款节点", "", None}

# ------------------------------------------------------------------- 状态枚举


class RemindStatus:
    """reminder_log.status 取值（设计文档 §4.2）。"""

    PENDING = "PENDING"      # 已识别待提醒（弹窗已推送，尚未处理）
    SUCCESS = "SUCCESS"      # 邮件发送成功
    FAILED = "FAILED"        # 邮件发送失败
    SKIPPED = "SKIPPED"      # 命中逾期但被排除规则跳过
    CLOSED = "CLOSED"        # 已回款/核销或人工关闭（终态）
    ESCALATE = "ESCALATE"    # 达到最大轮次，升级转主管

    ALL = (PENDING, SUCCESS, FAILED, SKIPPED, CLOSED, ESCALATE)
    # 处于这些状态的账单仍需在弹窗中持续跟进
    ACTIVE = (PENDING, SUCCESS, FAILED, ESCALATE)
    # 终态：不再自动提醒
    TERMINAL = (CLOSED,)


# --------------------------------------------------------------- 跳过原因枚举
SKIP_DUNNING_BLOCK = "Dunning Block 已设催收冻结"
SKIP_CREDIT_NOTE = "贷记凭证（Credit Note）金额为负，不催收"
SKIP_NO_MAIL = "客户邮箱为空，转人工处理队列"
SKIP_UNBILLED = "未开票（Unbilled），不在本工具职责范围"
SKIP_TOO_SOON = "距上次提醒不足 {days} 天，尚未到达下一轮"
SKIP_CLOSED = "账单已关闭（回款/核销/人工处理）"
SKIP_MAX_ROUND = "已达最大提醒轮次，转主管处理"
