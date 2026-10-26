"""登录鉴权层。"""

from .base import AuthProvider, UserInfo
from .mock import MockAuthProvider
from .sso import SSOAuthProvider

__all__ = ["AuthProvider", "UserInfo", "MockAuthProvider", "SSOAuthProvider"]


def build_auth_provider(cfg) -> AuthProvider:
    """按配置构建鉴权实现（sso_enabled=true 走 SSO，否则 Mock 免登录）。"""
    if cfg.auth.sso_enabled:
        return SSOAuthProvider(cfg.auth)
    return MockAuthProvider(cfg.auth)
