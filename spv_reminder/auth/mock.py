"""本地测试用的免登录实现（设计文档 §5.2 MockAuthProvider）。"""

from __future__ import annotations

from ..config import AuthConfig
from .base import AuthProvider, UserInfo


class MockAuthProvider(AuthProvider):
    """免登录：直接返回配置中的假用户，支撑全链路离线演示。"""

    def __init__(self, cfg: AuthConfig):
        self.cfg = cfg
        self._user = UserInfo(
            user_id=cfg.mock_user_id,
            name=cfg.mock_user_name,
            mail=cfg.mock_user_mail,
            is_admin=cfg.mock_is_admin,
        )

    def login(self) -> UserInfo:
        return self._user

    def current_user(self) -> UserInfo | None:
        return self._user

    def logout(self) -> None:
        # Mock 用户不可注销，保持登录态以便离线演示
        pass
