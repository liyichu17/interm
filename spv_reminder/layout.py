"""界面布局计算：主窗口屏幕适配与居中。"""

from __future__ import annotations


def compute_main_window_geometry(screen_x: int, screen_y: int,
                                 screen_width: int, screen_height: int) -> tuple[int, int, int, int]:
    """按屏幕可用区域计算主窗口几何，避免超屏并默认居中。"""
    width = min(screen_width, min(1180, max(720, int(screen_width * 0.92))))
    height = min(screen_height, min(760, max(520, int(screen_height * 0.9))))
    x = screen_x + max((screen_width - width) // 2, 0)
    y = screen_y + max((screen_height - height) // 2, 0)
    return x, y, width, height
