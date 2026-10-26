"""生产数据源：通过数据库视图拉取账单（设计文档 §5.1 DbSource）。

依赖 SQLAlchemy（可选安装）。未提供 db_url 或连接失败时抛出 DataSourceError，
由服务层回退本地 xlsx 数据源（降级可用，§2）。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import threading
import time

import pandas as pd

from .base import DataSource, DataSourceError


class DbSource(DataSource):
    """通过 SQL 视图拉取；带连接池与超时熔断。"""

    def __init__(self, db_url: str, view: str = "v_overdue_bills",
                 timeout_seconds: int = 15, cache_ttl_seconds: int = 60):
        if not db_url:
            raise DataSourceError("未配置 datasource.db_url")
        self.db_url = db_url
        self.view = view
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self._engine = None
        self._cache: pd.DataFrame | None = None
        self._cache_at = 0.0
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- 接口
    def fetch_bills(self) -> pd.DataFrame:
        with self._lock:
            now = time.time()
            if self._cache is not None and now - self._cache_at < self.cache_ttl_seconds:
                return self._cache
            df = self._query()
            df = self.normalize_columns(df)
            df = self.with_row_key(df)
            if self._cache is None:
                self._cache = df
            self._cache_at = now
            return df

    def describe(self) -> str:
        host_part = self.db_url.split("@")[-1] if "@" in self.db_url else self.db_url
        return f"db://{host_part}/{self.view}"

    def source_hash(self) -> str:
        return hashlib.md5(f"{self.db_url}|{self.view}|{dt.date.today()}".encode()).hexdigest()

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    # ---------------------------------------------------------------- 内部
    def _query(self) -> pd.DataFrame:
        try:
            import sqlalchemy
        except ImportError as exc:  # pragma: no cover - 可选依赖
            raise DataSourceError("使用 database 数据源需安装 sqlalchemy / 数据库驱动") from exc
        try:
            if self._engine is None:
                kwargs = {"pool_pre_ping": True, "pool_recycle": 1800}
                if self.db_url.startswith("mysql"):
                    kwargs["connect_args"] = {"connect_timeout": self.timeout_seconds}
                self._engine = sqlalchemy.create_engine(self.db_url, **kwargs)
            sql = sqlalchemy.text(f"SELECT * FROM {self.view}")
            with self._engine.connect() as conn:
                return pd.read_sql(sql, conn)
        except Exception as exc:  # noqa: BLE001 - 统一封装为数据源异常
            self._engine = None
            raise DataSourceError(f"数据库查询失败：{exc}") from exc
