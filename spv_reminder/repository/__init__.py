"""提醒日志仓库层。"""

from .base import LogRepository
from .db_repo import DbLogRepository
from .sqlite_repo import SQLiteLogRepository

__all__ = ["LogRepository", "SQLiteLogRepository", "DbLogRepository"]


def build_log_repository(cfg) -> LogRepository:
    """按配置构建日志仓库（sqlite / database）。"""
    if cfg.log_repo.type == "database":
        return DbLogRepository(cfg.log_repo.db_url)
    return SQLiteLogRepository(cfg.resolve_sqlite_path())
