"""主窗口布局测试：屏幕适配与居中计算。"""

from __future__ import annotations

from spv_reminder.layout import compute_main_window_geometry


def test_geometry_uses_default_size_on_large_screen():
    x, y, width, height = compute_main_window_geometry(0, 0, 1920, 1080)
    assert (width, height) == (1180, 760)
    assert (x, y) == ((1920 - 1180) // 2, (1080 - 760) // 2)


def test_geometry_scales_down_on_medium_screen():
    x, y, width, height = compute_main_window_geometry(0, 0, 1000, 700)
    assert width == int(1000 * 0.92)
    assert height == int(700 * 0.9)
    assert x == (1000 - width) // 2
    assert y == (700 - height) // 2


def test_geometry_never_exceeds_small_screen():
    _, _, width, height = compute_main_window_geometry(0, 0, 640, 480)
    assert width == 640
    assert height == 480


def test_geometry_keeps_screen_offset_when_centering():
    x, y, width, height = compute_main_window_geometry(100, 50, 1400, 900)
    assert (width, height) == (1180, 760)
    assert x == 100 + (1400 - 1180) // 2
    assert y == 50 + (900 - 760) // 2
