"""登录鉴权抽象接口（设计文档 §5.2）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class UserInfo:
    """当前登录用户。"""

    user_id: str = ""
    name: str = ""
    mail: str = ""
    is_admin: bool = False

    def match_owner(self, owner: str, ps_pm: str = "") -> bool:
        """判断账单是否归属当前用户（工号或邮箱匹配）。"""
        if self.is_admin:
            return True
        candidates = {owner or "", ps_pm or ""}
        return bool({self.user_id, self.name, self.mail} & candidates)

    @property
    def display(self) -> str:
        return f"{self.name}（{self.user_id}）" if self.name else self.user_id


class AuthProvider(ABC):
    @abstractmethod
    def login(self) -> UserInfo:
        """执行登录流程，返回用户信息。"""

    @abstractmethod
    def current_user(self) -> UserInfo | None:
        """当前已登录用户（未登录返回 None）。"""

    @abstractmethod
    def logout(self) -> None:
        """注销（清除内存中的凭据）。"""
