# SPV 客户逾期账单提醒工具

依据《SPV客户逾期提醒功能设计文档 v2》实现的桌面应用：自动扫描 SPV 客户逾期账单 → 弹窗提醒 → 按客户生成催款邮件 → 全量提醒日志可追溯。

- **语言/框架**：Python 3.11 + PySide6（Qt）+ pandas
- **数据来源**：`data/bills.xlsx`（样例，44 字段，与 `data_part_desensitized.xlsx` 一致）
- **默认运行模式**：本地 xlsx 数据源 + SQLite 日志 + 本地 `.eml` 邮件（**全链路离线可演示**，不真实外发）

---

## 1. 快速开始

```bash
cd spv_overdue_reminder
pip install -r requirements.txt

# ① 命令行：离线跑通扫描 → 日志 → 导出
python -m spv_reminder.cli scan --config config.local.yaml

# ② 生成催款邮件（默认落盘到 outbox/，不真实发送）
python -m spv_reminder.cli mail --config config.local.yaml --send

# ③ 桌面应用
python main.py --config config.local.yaml --scan-now
```

> 样例数据仅含 TIDES / RCS / IVBU 等 BU，生产配置 `config.yaml` 的目标 BU 为
> `STA DS / STA DP / TIDES`。因此**演示请使用 `config.local.yaml`**（已放开 BU 列表以便看到多条命中），
> 正式运行使用 `config.yaml`。

---

## 2. 目录结构

```
spv_overdue_reminder/
├── config.yaml                  # 生产配置（BU=STA DS/STA DP/TIDES）
├── config.local.yaml            # 本地演示配置（放开 BU，日志落在 ./logs）
├── main.py                      # GUI 入口
├── requirements.txt
├── data/bills.xlsx              # 账单样例
├── templates/dunning_default.html   # 催款邮件模板（Jinja2，中英双语）
├── scripts/
│   ├── bench_filter.py          # 10 万行筛选性能基准
│   └── gui_smoke.py             # 无显示器环境的 GUI 冒烟测试
├── tests/                       # 61 条单元测试（筛选/工具/仓库/邮件/端到端）
└── spv_reminder/
    ├── constants.py             # 字段名与状态枚举（与源表列名逐一对应）
    ├── utils.py                 # 日期/金额/文本归一化、日志
    ├── config.py                # 配置中心（yaml + 运行期覆盖）
    ├── models.py                # Bill / ReminderLog / DunningMail
    ├── filters.py               # ★ 核心筛选纯函数（§3.1/§3.2）
    ├── cli.py                   # 命令行入口
    ├── datasource/              # DataSource：LocalXlsxSource / DbSource
    ├── repository/              # LogRepository：SQLite / Database
    ├── auth/                    # AuthProvider：Mock / SSO(OAuth2)
    ├── mail/                    # JinjaMailComposer / FileMailSender / SmtpMailSender
    ├── service/                 # OverdueScanner / ReminderScheduler / 开机自启 / 导出
    └── ui/                      # 主窗口 / 弹窗 / 邮件预览 / 日志窗口 / 工作线程
```

---

## 3. 命令行用法

| 命令 | 说明 | 常用参数 |
| --- | --- | --- |
| `scan` | 扫描逾期账单并写提醒日志 | `--dry-run`、`--export 路径` |
| `export` | 导出当前逾期清单 xlsx | `--out` |
| `mail` | 按客户聚合生成催款邮件 | `--send`、`--force` |
| `logs` | 查询/导出提醒日志 | `--status`、`--invoice`、`--out` |
| `stats` | 当日统计（待提醒/已发/失败/金额） | — |
| `info` | 数据源与配置自检 | — |

公共参数（可放在子命令前后）：`--config`、`--set section.key=value`、`--business-date`、`--bu`、`--quiet`。

```bash
# 指定业务日期回看历史口径
python -m spv_reminder.cli scan --config config.local.yaml --business-date 2026-10-26

# 临时覆盖阈值，不改配置文件
python -m spv_reminder.cli scan --set scan.first_overdue_days=30 --set scan.max_remind_rounds=2

# 只导出跳过原因清单做人工复核
python -m spv_reminder.cli logs --config config.local.yaml --status SKIPPED --out 跳过清单.xlsx
```

---

## 4. 界面功能

| 窗口 | 内容 |
| --- | --- |
| 主窗口 | 登录状态、数据源状态灯、开机自启/定时扫描开关与时间、「立即执行」「导出当前清单」「提醒日志」「关于」、四张统计卡片、实时滚动日志、状态栏（上次/下次扫描时间、操作人） |
| 弹窗提醒 | 展示 17 个展示列 + 计算列（Overdue Days / 轮次）；默认按「Amount in CNY」降序、可点表头排序；行内角标 ⚠ 争议 / 🔴 已升级 / 📅 已有还款计划；支持「下载表格」「生成邮件」「标记已处理」「稍后提醒」 |
| 邮件预览 | 按客户聚合（同客户多账单合并一封）；可编辑收件人/抄送/主题/HTML 正文；「发送本封」「全部发送」「保存草稿」；发送结果回写日志（含失败原因） |
| 日志查看 | 按状态/账单号过滤、按账单号追溯全部提醒历史、导出 xlsx/csv |

后台行为：扫描与发送放工作线程（信号槽回 UI）；程序驻留系统托盘；到达定时点自动扫描；
开机自启时以「业务日期 + 数据源哈希」去重，同日不重复打扰。

---

## 5. 核心业务规则实现位置

| 设计文档条目 | 实现 |
| --- | --- |
| §3.1 筛选条件（逾期≥10 天 / BU / SPV=Y） | `filters.base_mask` |
| §3.1 排除条件 a~d | `filters.exclusion_reasons` |
| §3.2 提醒状态机（ROUND_n / ESCALATE / CLOSED） | `filters.decide_remind_round`、`scanner._auto_close` |
| §3.3 定时/开机自启/防重复 | `service.scheduler`、`service.autostart`、`SQLiteLogRepository.scanned_today` |
| §4.2 提醒日志表与唯一约束 | `repository/sqlite_repo.py`（`UNIQUE(invoice_no, remind_round)`） |
| §5.1~5.4 四个抽象接口 | `datasource/`、`repository/`、`auth/`、`mail/` 各自的 base + 双实现 |
| §6.4 邮件模板 | `templates/dunning_default.html`（Jinja2，支持 `dunning_{template}_{BU}.html` 变体） |
| §7 数据兼容 | `utils.parse_date`（字符串/Excel 序列号）、`to_float`（负数/千分位） |

**幂等性**：同一账单同一轮次唯一约束，重复扫描不产生重复日志，不重复发信。
**降级**：数据库数据源不可达时自动回退本地 xlsx 并在界面提示；邮件发送失败仅记日志，不阻塞扫描。

---

## 6. 测试与性能

```bash
python -m pytest tests -q                 # 61 passed
python scripts/bench_filter.py 100000     # 10 万行筛选 ≈2.5s（要求 < 5s）
QT_QPA_PLATFORM=offscreen python scripts/gui_smoke.py   # GUI 链路冒烟
```

测试覆盖：逾期天数与阈值边界、四类排除规则、轮次递进与 20 天间隔、满轮升级、CLOSED 终态、
日志幂等与批量轮次查询、自动关闭、日期/金额/邮箱解析、邮件聚合与模板渲染、端到端扫描链路。

---

## 7. 生产接入对照

| 能力 | 本地/测试（默认） | 生产切换方式 |
| --- | --- | --- |
| 数据源 | `LocalXlsxSource` | `datasource.type: database` + `db_url`（SQL 视图 `v_overdue_bills`） |
| 日志 | `SQLiteLogRepository` | `log_repo.type: database`（标准 SQL，兼容 MySQL/PG/SQL Server） |
| 登录 | `MockAuthProvider`（免登录） | `auth.sso_enabled: true` + IdP 的 authorize/token/client_id |
| 邮件 | `FileMailSender`（生成 .eml） | `mail.mode: smtp` + SMTP 主机/端口；密码走环境变量或系统钥匙串，不落盘 |
| 权限 | 管理员可见全部 | SSO 用户按 `Owner / PS/PM` 匹配，仅见自己名下账单 |

打包为单文件 exe（可选）：

```bash
pip install pyinstaller
pyinstaller --noconfirm --windowed --onefile --name SPVOverdueReminder \
            --add-data "templates;templates" --add-data "config.yaml;." main.py
```
