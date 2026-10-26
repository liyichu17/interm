"""开机自启管理（§3.3）：Windows 注册表 Run / macOS LaunchAgent / Linux autostart。"""

from __future__ import annotations

import logging
import os
import sys
import textwrap

logger = logging.getLogger(__name__)

APP_NAME = "SPVOverdueReminder"


def is_supported() -> bool:
    return sys.platform in {"win32", "darwin", "linux"}


def executable_command() -> str:
    """生成开机自启命令行（打包后的 exe 或开发模式的 python -m）。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    entry = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    return f'"{sys.executable}" "{entry}" --minimized'


# ------------------------------------------------------------------- Windows
def _win_reg_key() -> tuple:
    import winreg

    return winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"


def _win_enable() -> bool:
    import winreg

    root, path = _win_reg_key()
    with winreg.CreateKeyEx(root, path, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, executable_command())
    return True


def _win_disable() -> bool:
    import winreg

    root, path = _win_reg_key()
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
    except FileNotFoundError:
        pass
    return True


def _win_is_enabled() -> bool:
    import winreg

    root, path = _win_reg_key()
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except (FileNotFoundError, OSError):
        return False


# --------------------------------------------------------------------- macOS
def _mac_plist_path() -> str:
    return os.path.expanduser(f"~/Library/LaunchAgents/com.wuxi.{APP_NAME.lower()}.plist")


def _mac_enable() -> bool:
    path = _mac_plist_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cmd = executable_command()
    program, *args = _split_command(cmd)
    args_xml = "".join(f"        <string>{a}</string>\n" for a in args)
    content = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
         "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
          <key>Label</key>
          <string>com.wuxi.{APP_NAME.lower()}</string>
          <key>ProgramArguments</key>
          <array>
            <string>{program}</string>
        {args_xml}  </array>
          <key>RunAtLoad</key>
          <true/>
        </dict>
        </plist>
    """)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(content)
    return True


def _mac_disable() -> bool:
    path = _mac_plist_path()
    if os.path.exists(path):
        os.remove(path)
    return True


def _mac_is_enabled() -> bool:
    return os.path.exists(_mac_plist_path())


# --------------------------------------------------------------------- Linux
def _linux_desktop_path() -> str:
    return os.path.expanduser(f"~/.config/autostart/{APP_NAME}.desktop")


def _linux_enable() -> bool:
    path = _linux_desktop_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(textwrap.dedent(f"""\
            [Desktop Entry]
            Type=Application
            Name={APP_NAME}
            Exec={executable_command()}
            Hidden=false
            NoDisplay=false
            X-GNOME-Autostart-enabled=true
        """))
    return True


def _linux_disable() -> bool:
    path = _linux_desktop_path()
    if os.path.exists(path):
        os.remove(path)
    return True


def _linux_is_enabled() -> bool:
    return os.path.exists(_linux_desktop_path())


# -------------------------------------------------------------------- 统一入口
def set_autostart(enabled: bool) -> bool:
    """开启/关闭开机自启；不支持的平台或失败时返回 False（不阻断主流程）。"""
    try:
        if sys.platform == "win32":
            return _win_enable() if enabled else _win_disable()
        if sys.platform == "darwin":
            return _mac_enable() if enabled else _mac_disable()
        if sys.platform == "linux":
            return _linux_enable() if enabled else _linux_disable()
    except Exception as exc:  # noqa: BLE001
        logger.warning("设置开机自启失败：%s", exc)
        return False
    return False


def is_autostart_enabled() -> bool:
    try:
        if sys.platform == "win32":
            return _win_is_enabled()
        if sys.platform == "darwin":
            return _mac_is_enabled()
        if sys.platform == "linux":
            return _linux_is_enabled()
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取开机自启状态失败：%s", exc)
    return False


def _split_command(cmd: str) -> list[str]:
    """简单拆分命令行（支持双引号包裹的参数）。"""
    import shlex

    return shlex.split(cmd, posix=(os.name != "nt"))
