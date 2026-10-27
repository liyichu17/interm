"""核心筛选逻辑（设计文档 §3.1）。

全部为**纯函数**：输入 DataFrame/配置/业务日期，输出命中与跳过结果，
不依赖 GUI、数据库与文件系统，便于单元测试（§7 可测试性）。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .constants import (
    C_AMOUNT_CNY,
    C_BILLED,
    C_BU,
    C_CN_INVOICE,
    C_DUE_DATE,
    C_DUNNING_BLOCK,
    C_OVERDUE_DAYS,
    C_SPV_CUSTOMER,
    C_TO_CLIENT,
    C_AMOUNT,
    CN_CREDIT_NOTE,
    DUNNING_BLOCKED,
    SKIP_CREDIT_NOTE,
    SKIP_DUNNING_BLOCK,
    SKIP_MAX_ROUND,
    SKIP_NO_MAIL,
    SKIP_CLOSED,
    SKIP_TOO_SOON,
    SKIP_UNBILLED,
    RemindStatus,
    UNBILLED,
)
from .datasource.base import ROW_KEY
from .models import Bill, ReminderLog
from .utils import norm_text_series, parse_date_series, to_float_series, upper_in

SKIP_REASON = "skip_reason"


@dataclass
class Decision:
    """单条账单的扫描决策。"""

    bill: Bill
    included: bool
    remind_round: int = 0
    reason: str = ""
    escalated: bool = False
    log: Optional[ReminderLog] = field(default=None)

    @property
    def state(self) -> str:
        if not self.included:
            return "SKIPPED"
        if self.escalated:
            return RemindStatus.ESCALATE
        return f"ROUND_{self.remind_round}_SENT"


@dataclass
class FilterResult:
    """整表筛选结果。"""

    hits: pd.DataFrame            # 待提醒账单（含 Overdue Days / remind_round 计算列）
    skipped: pd.DataFrame         # 命中逾期但被排除/未到提醒时点的账单（含 skip_reason）
    scanned_rows: int = 0         # 扫描总行数
    overdue_rows: int = 0         # 满足「逾期 + BU + SPV」的行数
    overdue_keys: set = field(default_factory=set)
    # 仍在逾期清单中的账单键：用于判定「已回款/核销 → 自动关闭」，
    # 未到下一轮提醒时点的账单仍属逾期清单，不应被关闭。

    @property
    def hit_count(self) -> int:
        return len(self.hits)


# --------------------------------------------------------------------- 基础过滤
def compute_overdue_days(df: pd.DataFrame, business_date: dt.date) -> pd.Series:
    """向量化计算逾期天数（业务日期 − Due Date），无到期日为 NaN。"""
    due = parse_date_series(df[C_DUE_DATE])
    delta = (pd.Timestamp(business_date) - due).dt.days
    return delta.astype("Int64")  # 无到期日为 <NA>，展示与导出均为整数


def base_mask(df: pd.DataFrame, cfg, business_date: dt.date) -> pd.Series:
    """§3.1 筛选条件 1~3：逾期 ≥ N 天、BU 命中、SPV = Y。"""
    overdue = compute_overdue_days(df, business_date)
    mask_overdue = overdue.fillna(-1) >= cfg.scan.first_overdue_days
    mask_bu = upper_in(df[C_BU], set(cfg.scan.target_bu_list))
    mask_spv = upper_in(df[C_SPV_CUSTOMER], {"Y"})
    return (mask_overdue & mask_bu & mask_spv).fillna(False).astype(bool)


def exclusion_reasons(df: pd.DataFrame) -> pd.Series:
    """§3.1 排除条件 a~d，返回每行原因（未命中为空串）。"""
    dunning = upper_in(df[C_DUNNING_BLOCK], {DUNNING_BLOCKED}).fillna(False)
    amount = to_float_series(df[C_AMOUNT])
    credit_note = upper_in(df[C_CN_INVOICE], {CN_CREDIT_NOTE}).fillna(False) & (amount <= 0)
    no_mail = norm_text_series(df[C_TO_CLIENT]).fillna("").eq("")
    unbilled = upper_in(df[C_BILLED], {UNBILLED}).fillna(False)
    conditions = [dunning.to_numpy(), credit_note.to_numpy(),
                  no_mail.to_numpy(), unbilled.to_numpy()]
    choices = [SKIP_DUNNING_BLOCK, SKIP_CREDIT_NOTE, SKIP_NO_MAIL, SKIP_UNBILLED]
    reasons = np.select(conditions, choices, default="")
    return pd.Series(reasons, index=df.index, dtype="object")


# ----------------------------------------------------------------- 轮次决策
def decide_remind_round(bill: Bill, cfg, business_date: dt.date,
                        latest: Optional[ReminderLog]) -> tuple[bool, int, str, bool]:
    """判定本轮是否提醒、轮次、跳过原因、是否升级。

    返回 ``(included, remind_round, reason, escalated)``。

    规则（§3.2 状态机）：
    - 无历史  → 第 1 轮
    - CLOSED  → 终态，不再提醒
    - 已 ESCALATE → 继续展示（标红），不再自动发邮件
    - 已达最大轮次 → 升级 ESCALATE，仍展示
    - 距上次提醒 ≥ 间隔 且 轮次 < 上限 → 下一轮
    - 距上次提醒 < 间隔 → 本轮跳过
    """
    if latest is None:
        return True, 1, "", False

    if latest.status == RemindStatus.CLOSED:
        return False, latest.remind_round, SKIP_CLOSED, False

    if latest.status == RemindStatus.ESCALATE:
        return True, latest.remind_round, SKIP_MAX_ROUND, True

    max_rounds = cfg.scan.max_remind_rounds
    if latest.remind_round >= max_rounds:
        return True, latest.remind_round, SKIP_MAX_ROUND, True

    if latest.remind_date is None:
        return True, latest.remind_round + 1, "", False

    elapsed = (business_date - latest.remind_date).days
    # 首次提醒后若员工尚未处理（PENDING/FAILED 且未发送成功），
    # 在再提醒间隔内，立即扫描仍应继续出现在待跟进清单；
    # 超过间隔后按原有轮次规则推进。
    if latest.status in (RemindStatus.PENDING, RemindStatus.FAILED) and not latest.mail_sent:
        if elapsed < cfg.scan.re_remind_interval_days:
            round_no = latest.remind_round if latest.remind_round > 0 else 1
            return True, round_no, "", False

    if elapsed < cfg.scan.re_remind_interval_days:
        reason = SKIP_TOO_SOON.format(days=cfg.scan.re_remind_interval_days)
        return False, latest.remind_round, reason, False

    return True, latest.remind_round + 1, "", False


# ------------------------------------------------------------------ 整表筛选
def filter_overdue_bills(df: pd.DataFrame, cfg, business_date: dt.date,
                         latest_logs: Optional[dict[str, ReminderLog]] = None
                         ) -> FilterResult:
    """执行 §3.1 完整筛选：基础条件 → 排除条件 → 轮次决策。

    ``latest_logs`` 为 {账单键: 最新日志}，由日志仓库批量提供；为空表示全部首次提醒。
    """
    latest_logs = latest_logs or {}
    if df is None or len(df) == 0:
        return FilterResult(hits=df.iloc[0:0].copy(), skipped=df.iloc[0:0].copy(),
                            scanned_rows=0, overdue_rows=0, overdue_keys=set())

    work = df.copy()
    work[C_OVERDUE_DAYS] = compute_overdue_days(work, business_date)

    base = base_mask(work, cfg, business_date)
    overdue_df = work[base].copy()

    # ---- 排除条件：向量化判定原因，命中即跳过
    if len(overdue_df):
        reasons = exclusion_reasons(overdue_df)
        excluded = reasons.ne("")
        skipped_df = overdue_df[excluded].copy()
        skipped_df[SKIP_REASON] = reasons[excluded].to_numpy()
        candidates = overdue_df[~excluded].copy()
    else:
        skipped_df = overdue_df.copy()
        skipped_df[SKIP_REASON] = pd.Series(dtype="object")
        candidates = overdue_df.copy()

    # ---- 轮次决策：候选集规模可控，逐行结合日志判定
    hit_rows, skip_rows = [], []

    for idx in candidates.index:
        row = candidates.loc[idx]
        bill = Bill.from_row(row.to_dict())
        bill.overdue_days = _safe_int(row.get(C_OVERDUE_DAYS))
        key = row.get(ROW_KEY) or bill.invoice_no
        included, rnd, reason, escalated = decide_remind_round(
            bill, cfg, business_date, latest_logs.get(key))
        bill.remind_round = rnd
        bill.is_escalated = escalated
        row = row.copy()
        row["remind_round"] = rnd
        row["escalated"] = escalated
        row[ROW_KEY] = key
        if included:
            hit_rows.append(row)
        else:
            row[SKIP_REASON] = reason
            skip_rows.append(row)

    # 注意：不可限定 columns，否则逐行追加的 remind_round / escalated 会被丢弃
    hits = pd.DataFrame(hit_rows) if hit_rows else candidates.iloc[0:0].copy()
    if skip_rows:
        extra = pd.DataFrame(skip_rows)
        skipped_df = pd.concat([skipped_df, extra], ignore_index=True)

    # 默认按折人民币金额降序（§6.2）
    if len(hits):
        hits = hits.sort_values(by=[C_AMOUNT_CNY], ascending=False, kind="mergesort")

    overdue_keys = set(candidates[ROW_KEY].astype(str)) if ROW_KEY in candidates else set()

    return FilterResult(hits=hits.reset_index(drop=True),
                        skipped=skipped_df.reset_index(drop=True),
                        scanned_rows=len(work), overdue_rows=len(overdue_df),
                        overdue_keys=overdue_keys)


def _safe_int(value) -> Optional[int]:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
