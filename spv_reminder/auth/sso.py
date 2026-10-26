"""企业 SSO 登录实现（OAuth2/OIDC 授权码 + 本地回环回调）。

token 仅内存驻留不落盘（§7 安全）。生产环境启用：``auth.sso_enabled: true``。
"""

from __future__ import annotations

import logging
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from ..config import AuthConfig
from .base import AuthProvider, UserInfo

logger = logging.getLogger(__name__)


class SSOAuthProvider(AuthProvider):
    """OAuth2 授权码模式：拉起浏览器 → IdP 认证 → 本地端口回调取 code → 换 token。"""

    def __init__(self, cfg: AuthConfig, scope: str = "openid profile email"):
        self.cfg = cfg
        self.scope = scope
        self._user: UserInfo | None = None
        self._token: dict | None = None

    # ------------------------------------------------------------------ 接口
    def login(self) -> UserInfo:
        if not self.cfg.sso_authorize_url or not self.cfg.sso_token_url:
            raise RuntimeError("未配置 sso_authorize_url / sso_token_url，无法启用 SSO 登录")
        code = self._authorize()
        token = self._exchange_token(code)
        self._token = token
        self._user = self._parse_user(token)
        logger.info("SSO 登录成功：%s", self._user.display)
        return self._user

    def current_user(self) -> UserInfo | None:
        return self._user

    def logout(self) -> None:
        self._user = None
        self._token = None

    # ------------------------------------------------------------------ 内部
    def _authorize(self) -> str:
        """启动本地临时 HTTP 服务接收回调，拉起浏览器完成认证。"""
        port = self.cfg.sso_redirect_port
        redirect_uri = f"http://localhost:{port}/callback"
        params = {
            "response_type": "code",
            "client_id": self.cfg.sso_client_id,
            "redirect_uri": redirect_uri,
            "scope": self.scope,
        }
        url = f"{self.cfg.sso_authorize_url}?{urlencode(params)}"

        result: dict[str, str] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - HTTP 方法名由框架约定
                query = parse_qs(urlparse(self.path).query)
                if "code" in query:
                    result["code"] = query["code"][0]
                    self._respond("登录成功，请返回应用程序。")
                else:
                    self._respond("登录失败：未获取到授权码。")
                threading.Thread(target=server.shutdown, daemon=True).start()

            def _respond(self, text: str) -> None:
                body = text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # 静音默认访问日志
                pass

        server = HTTPServer(("127.0.0.1", port), Handler)
        webbrowser.open(url)
        server.serve_forever()
        server.server_close()
        if "code" not in result:
            raise RuntimeError("SSO 登录被取消或失败")
        return result["code"]

    def _exchange_token(self, code: str) -> dict:
        port = self.cfg.sso_redirect_port
        response = requests.post(
            self.cfg.sso_token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self.cfg.sso_client_id,
                "redirect_uri": f"http://localhost:{port}/callback",
            },
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    def _parse_user(self, token: dict) -> UserInfo:
        """解析 token：优先解析 id_token 载荷，其次用 userinfo 风格字段。"""
        claims: dict = {}
        id_token = token.get("id_token")
        if id_token:
            import base64
            import json

            payload = id_token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            try:
                claims = json.loads(base64.urlsafe_b64decode(payload))
            except Exception:  # noqa: BLE001 - token 解析失败不阻断登录
                logger.warning("id_token 解析失败，回退顶层字段")
        claims = {**token, **claims}
        staff_id = claims.get("staff_id") or claims.get("employee_id") or claims.get("sub")
        return UserInfo(
            user_id=str(staff_id or ""),
            name=str(claims.get("name") or claims.get("display_name") or ""),
            mail=str(claims.get("email") or claims.get("mail") or ""),
            is_admin=bool(claims.get("is_admin", False)),
        )
