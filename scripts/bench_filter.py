"""筛选引擎性能基准：验证 10 万行级账单筛选 < 5s（设计文档 §7 性能）。

    python scripts/bench_filter.py            # 默认 10 万行
    python scripts/bench_filter.py 200000     # 指定行数
"""

from __future__ import annotations

import datetime as dt
import random
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from spv_reminder.config import Config  # noqa: E402
from spv_reminder.datasource import LocalXlsxSource  # noqa: E402
from spv_reminder.filters import filter_overdue_bills  # noqa: E402

BU_POOL = ["STA DS", "STA DP", "TIDES", "RCS", "IVBU", "BAS", "MD", "DMPK"]


def build_rows(count: int, today: dt.date) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    due_offset = rng.integers(-120, 60, size=count)
    due_dates = [today - dt.timedelta(days=int(d)) for d in due_offset]
    return pd.DataFrame({
        "Invoice NO.": [f"INV-{i:08d}" for i in range(count)],
        "Customer Code": [f"CUST-{i % 5000:05d}" for i in range(count)],
        "Customer Name": [f"客户{i % 5000}" for i in range(count)],
        "Company Code": ["3002"] * count,
        "Project ID": [f"PRJ-{i % 900}" for i in range(count)],
        "Due Date": due_dates,
        "Invoice date/GL date": due_dates,
        "Aging": ["31 - 60 Days"] * count,
        "Cust Curr": ["CNY"] * count,
        "Amount 的总和": rng.uniform(-5000, 500000, size=count).round(2),
        "Amount in CNY": rng.uniform(0, 500000, size=count).round(2),
        "BU": rng.choice(BU_POOL, size=count),
        "SPV_Customer": rng.choice(["Y", "Y", "Y", "N"], size=count),
        "Dunning Block": rng.choice([None, None, None, "X"], size=count),
        "CN/Invoice": rng.choice(["Invoice", "Invoice", "Credit Note"], size=count),
        "Billed/Unbilled": rng.choice(["Billed", "Billed", "Unbilled"], size=count),
        "To client": [f"c{i}@example.com" if i % 97 else "" for i in range(count)],
        "Cc client": ["cc@example.com"] * count,
        "Owner": [f"staff{i % 50}" for i in range(count)],
        "PS/PM": [f"pm{i % 50}@example.com" for i in range(count)],
        "Case Category": ["未达催款节点"] * count,
    })


def main() -> int:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
    today = dt.date.today()
    cfg = Config.from_dict({})

    print(f"生成 {count:,} 行测试数据…")
    df = LocalXlsxSource.with_row_key(build_rows(count, today))

    started = time.perf_counter()
    result = filter_overdue_bills(df, cfg, today)
    elapsed = time.perf_counter() - started

    print(f"扫描行数：{result.scanned_rows:,}　逾期命中：{result.overdue_rows:,}　"
          f"待提醒：{result.hit_count:,}　跳过：{len(result.skipped):,}")
    print(f"筛选耗时：{elapsed:.3f}s　（要求 < 5s，{'通过' if elapsed < 5 else '未达标'}）")
    return 0 if elapsed < 5 else 1


if __name__ == "__main__":
    sys.exit(main())
