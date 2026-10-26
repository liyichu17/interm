"""桌面应用入口（GUI）。

    python main.py                  # 打开主窗口
    python main.py --scan-now       # 打开并立即扫描
    python main.py --minimized      # 开机自启模式（静默驻留托盘）
    python main.py --config config.local.yaml
"""

from __future__ import annotations

import sys

from spv_reminder.ui.app import main

if __name__ == "__main__":
    sys.exit(main())
