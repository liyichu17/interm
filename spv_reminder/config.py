"""配置中心：config.yaml 加载、默认值、运行期覆盖。

设计文档 §4.3。所有业务阈值均为配置项，扩展 BU / 调整轮次无需改代码。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from typing import Any, Optional

import yaml

DEFAULT_CONFIG_NAME = "config.yaml"

_DEFAULT_YAML = """
scan:
  first_overdue_days: 10
  re_remind_interval_days: 20
  max_remind_rounds: 3
  daily_scan_time: "09:00"
  target_bu_list: ["STA DS", "STA DP", "TIDES"]
  timezone_offset_hours: 8
datasource:
  type: xlsx                      # xlsx | database
  xlsx_path: "./data/bills.xlsx"
  xlsx_sheet: "Sheet1"
  db_url: ""                      # 例：mysql+pymysql://user:pwd@host:3306/ar?charset=utf8mb4
  db_view: "v_overdue_bills"
  db_timeout_seconds: 15
log_repo:
  type: sqlite                    # sqlite | database
  sqlite_path: "{appdata}/reminder.db"
  db_url: ""
mail:
  smtp_template: "default_dunning"
  sender_name: "WuXi AppTec AR Team"
  smtp_host: ""
  smtp_port: 587
  smtp_use_tls: true
  smtp_username: ""
  smtp_password_env: "SPV_SMTP_PASSWORD"   # 密码从环境变量/钥匙串读取，不落盘
  outbox_dir: "./outbox"          # FileMailSender 输出目录
  mode: file                      # file | smtp
auth:
  sso_enabled: false
  mock_user_id: "local_user"
  mock_user_name: "本地测试用户"
  mock_user_mail: "local_user@example.com"
  mock_is_admin: true
  sso_authorize_url: ""
  sso_token_url: ""
  sso_client_id: ""
  sso_redirect_port: 8765
app:
  autostart: true
  daily_scan_enabled: true
  log_dir: "./logs"
  log_level: "INFO"
  language: "zh"                  # zh | en
  version: "1.0.0"
"""


def app_data_dir() -> str:
    """应用数据目录（Windows: %APPDATA%/spv_reminder；其他: ~/.spv_reminder）。"""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "spv_reminder")
    os.makedirs(path, exist_ok=True)
    return path


@dataclass
class ScanConfig:
    first_overdue_days: int = 10
    re_remind_interval_days: int = 20
    max_remind_rounds: int = 3
    daily_scan_time: str = "09:00"
    target_bu_list: list[str] = field(default_factory=lambda: ["STA DS", "STA DP", "TIDES"])
    timezone_offset_hours: int = 8


@dataclass
class DataSourceConfig:
    type: str = "xlsx"
    xlsx_path: str = "./data/bills.xlsx"
    xlsx_sheet: str = "Sheet1"
    db_url: str = ""
    db_view: str = "v_overdue_bills"
    db_timeout_seconds: int = 15


@dataclass
class LogRepoConfig:
    type: str = "sqlite"
    sqlite_path: str = "{appdata}/reminder.db"
    db_url: str = ""


@dataclass
class MailConfig:
    smtp_template: str = "default_dunning"
    sender_name: str = "WuXi AppTec AR Team"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_use_tls: bool = True
    smtp_username: str = ""
    smtp_password_env: str = "SPV_SMTP_PASSWORD"
    outbox_dir: str = "./outbox"
    mode: str = "file"


@dataclass
class AuthConfig:
    sso_enabled: bool = False
    mock_user_id: str = "local_user"
    mock_user_name: str = "本地测试用户"
    mock_user_mail: str = "local_user@example.com"
    mock_is_admin: bool = True
    sso_authorize_url: str = ""
    sso_token_url: str = ""
    sso_client_id: str = ""
    sso_redirect_port: int = 8765


@dataclass
class AppConfig:
    autostart: bool = True
    daily_scan_enabled: bool = True
    log_dir: str = "./logs"
    log_level: str = "INFO"
    language: str = "zh"
    version: str = "1.0.0"


@dataclass
class Config:
    scan: ScanConfig = field(default_factory=ScanConfig)
    datasource: DataSourceConfig = field(default_factory=DataSourceConfig)
    log_repo: LogRepoConfig = field(default_factory=LogRepoConfig)
    mail: MailConfig = field(default_factory=MailConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    app: AppConfig = field(default_factory=AppConfig)

    # ------------------------------------------------------------ 加载/保存
    @classmethod
    def load(cls, path: Optional[str] = None) -> "Config":
        """从 yaml 加载；文件不存在时创建默认配置文件后再加载。"""
        path = path or default_config_path()
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(_DEFAULT_YAML.lstrip())
        with open(path, "r", encoding="utf-8") as fp:
            raw = yaml.safe_load(fp) or {}
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict) -> "Config":
        return cls(
            scan=_build(ScanConfig, raw.get("scan")),
            datasource=_build(DataSourceConfig, raw.get("datasource")),
            log_repo=_build(LogRepoConfig, raw.get("log_repo")),
            mail=_build(MailConfig, raw.get("mail")),
            auth=_build(AuthConfig, raw.get("auth")),
            app=_build(AppConfig, raw.get("app")),
        )

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name).__dict__ for f in fields(self)}

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fp:
            yaml.safe_dump(self.to_dict(), fp, allow_unicode=True, sort_keys=False)

    # -------------------------------------------------------------- 工具方法
    def resolve_sqlite_path(self) -> str:
        return _expand(self.log_repo.sqlite_path)

    def resolve_xlsx_path(self) -> str:
        return _expand(self.datasource.xlsx_path)

    def resolve_log_dir(self) -> str:
        return _expand(self.app.log_dir)

    def resolve_outbox_dir(self) -> str:
        return _expand(self.mail.outbox_dir)

    def resolve_template_dir(self, base_dir: str) -> str:
        return os.path.join(base_dir, "templates")

    def apply_overrides(self, overrides: dict[str, Any]) -> None:
        """按 ``section.key`` 覆盖配置（CLI --set 使用）。"""
        for key, value in overrides.items():
            if "." not in key:
                raise ValueError(f"配置项格式应为 section.key，收到：{key}")
            section, name = key.split(".", 1)
            holder = getattr(self, section, None)
            if holder is None or not hasattr(holder, name):
                raise ValueError(f"未知配置项：{key}")
            current = getattr(holder, name)
            if isinstance(current, bool):
                value = str(value).lower() in {"1", "true", "yes", "y", "on"}
            elif isinstance(current, int) and not isinstance(current, bool):
                value = int(value)
            elif isinstance(current, list):
                value = [v.strip() for v in str(value).split(",") if v.strip()]
            setattr(holder, name, value)


def _build(cls, raw: Optional[dict]):
    raw = raw or {}
    valid = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in raw.items() if k in valid})


def _expand(path: str) -> str:
    """展开 ``{appdata}`` 占位符与相对路径（相对于项目根目录）。"""
    path = path.replace("{appdata}", app_data_dir())
    if not os.path.isabs(path):
        path = os.path.join(project_root(), path)
    return os.path.normpath(path)


def project_root() -> str:
    """项目根目录（含 config.yaml 的目录）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_config_path() -> str:
    return os.path.join(project_root(), DEFAULT_CONFIG_NAME)
