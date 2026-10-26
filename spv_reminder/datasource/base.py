"""数据接入抽象接口（设计文档 §5.1）。

本地 xlsx 与生产数据库两套实现可热插拔，业务层只依赖本接口。
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

import pandas as pd

from ..constants import C_CUSTOMER_CODE, C_INVOICE_NO, C_PROJECT_ID
from ..utils import norm_text_series

ROW_KEY = "_row_key"  # 内部唯一键（脱敏样例中存在重复账单号，用于保证日志幂等）


class DataSourceError(RuntimeError):
    """数据源不可用（文件缺失、连接失败等）。"""


class DataSource(ABC):
    """账单数据源。"""

    @abstractmethod
    def fetch_bills(self) -> pd.DataFrame:
        """返回全量账单 DataFrame，列名与 data_part.xlsx 一致。"""

    @abstractmethod
    def describe(self) -> str:
        """数据源描述（用于界面状态栏展示）。"""

    def health_check(self) -> tuple[bool, str]:
        """健康检查，返回 (是否可用, 说明)。"""
        try:
            self.fetch_bills()
            return True, "ok"
        except Exception as exc:  # noqa: BLE001 - 健康检查需要兜住全部异常
            return False, str(exc)

    def source_hash(self) -> str:
        """数据源指纹，用于同日重复扫描去重。"""
        return hashlib.md5(self.describe().encode("utf-8")).hexdigest()

    # ------------------------------------------------------------- 公共工具
    @staticmethod
    def with_row_key(df: pd.DataFrame) -> pd.DataFrame:
        """补算内部唯一键 ``_row_key``。

        正常情况取账单号；当账单号缺失或在表内重复（脱敏数据常见）时，
        追加客户代码 / 项目号 / 行号构成复合键，保证日志唯一约束可生效。
        """
        inv = norm_text_series(df[C_INVOICE_NO]) if C_INVOICE_NO in df else pd.Series(
            [""] * len(df), index=df.index, dtype="string")
        dup = inv.duplicated(keep=False) | (inv == "")
        if not dup.any():
            df[ROW_KEY] = inv
            return df
        cust = norm_text_series(df[C_CUSTOMER_CODE]) if C_CUSTOMER_CODE in df else ""
        proj = norm_text_series(df[C_PROJECT_ID]) if C_PROJECT_ID in df else ""
        suffix = df.index.astype(str)
        keys = inv.where(~dup, inv + "|" + cust.astype(str) + "|" + proj.astype(str)
                         + "|" + suffix)
        df[ROW_KEY] = keys
        return df

    @staticmethod
    def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
        """列名去空白，去掉 Unnamed 空列。"""
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]
        df = df.loc[:, [c for c in df.columns if c and not c.startswith("Unnamed")]]
        return df
