"""数据接入层。"""

from .base import ROW_KEY, DataSource, DataSourceError
from .db_source import DbSource
from .xlsx_source import LocalXlsxSource

__all__ = ["DataSource", "DataSourceError", "LocalXlsxSource", "DbSource", "ROW_KEY"]


def build_data_source(cfg) -> DataSource:
    """按配置构建数据源（xlsx / database）。"""
    if cfg.datasource.type == "database":
        return DbSource(cfg.datasource.db_url, cfg.datasource.db_view,
                        cfg.datasource.db_timeout_seconds)
    return LocalXlsxSource(cfg.resolve_xlsx_path(), cfg.datasource.xlsx_sheet)
