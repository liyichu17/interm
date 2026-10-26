"""本地 xlsx 数据源（默认实现，适用于 POC / 离线演示）。

支持热加载：文件 mtime/size 变化后自动重读，无需重启程序。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os

import pandas as pd

from .base import DataSource, DataSourceError


class LocalXlsxSource(DataSource):
    """读取本地 xlsx 账单表。"""

    def __init__(self, path: str, sheet: str = "Sheet1"):
        self.path = os.path.normpath(path)
        self.sheet = sheet
        self._cache: pd.DataFrame | None = None
        self._stamp: tuple | None = None

    # ---------------------------------------------------------------- 接口
    def fetch_bills(self) -> pd.DataFrame:
        if not os.path.exists(self.path):
            raise DataSourceError(f"账单文件不存在：{self.path}")
        stamp = self._file_stamp()
        if self._cache is not None and self._stamp == stamp:
            return self._cache
        try:
            df = pd.read_excel(self.path, sheet_name=self.sheet, engine="openpyxl")
        except Exception as exc:  # noqa: BLE001
            raise DataSourceError(f"读取账单文件失败：{self.path} -> {exc}") from exc
        df = self.normalize_columns(df)
        df = self.with_row_key(df)
        self._cache = df
        self._stamp = stamp
        return df

    def describe(self) -> str:
        stamp = self._file_stamp() if os.path.exists(self.path) else None
        size = stamp[0] if stamp else 0
        mtime = dt.datetime.fromtimestamp(stamp[1]).strftime("%Y-%m-%d %H:%M:%S") if stamp else "-"
        return f"xlsx://{self.path} (sheet={self.sheet}, {size}B, mtime={mtime})"

    def source_hash(self) -> str:
        stamp = self._file_stamp() if os.path.exists(self.path) else (0, 0, self.path)
        return hashlib.md5(f"{stamp}|{self.sheet}".encode("utf-8")).hexdigest()

    def reload(self) -> pd.DataFrame:
        """强制重读（界面「重新加载数据源」使用）。"""
        self._cache = None
        return self.fetch_bills()

    @property
    def row_count(self) -> int:
        try:
            return len(self.fetch_bills())
        except Exception:  # noqa: BLE001
            return 0

    # ---------------------------------------------------------------- 内部
    def _file_stamp(self) -> tuple:
        stat = os.stat(self.path)
        return (stat.st_size, int(stat.st_mtime), self.path)
