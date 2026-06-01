# 买入策略 CLI 运行手册（无前台）

本文档用于在没有前端页面的情况下，通过 Django command 完成买入候选筛选、结果导出与快速回测验证。

## 1. 适用场景

- 仅有后端环境（服务器/容器）
- 需要定时任务自动产出候选池
- 需要离线查看候选明细和规则命中原因

## 2. 前置条件

1. 完成数据库迁移：

```bash
python manage.py migrate
```

2. 具备交易日行情与估值快照数据：

- 行情来自 `datastore_stocktradinghistory`
- 估值快照来自 `prediction_stockvaluationsnapshot`

3. 可选：若要在快照缺失时实时估值，需要可访问 TuShare。

## 3. 当日选股命令

命令入口：

```bash
python manage.py pickbuycandidates
```

常用参数：

- `--trade-date YYYY-MM-DD`：指定交易日，不传则自动使用日频最新交易日
- `--scope 688`：股票池范围（支持 `ALL` 或前缀列表，如 `60,0,3`）
- `--valuation-band-pct 0.1`：低估偏离带
- `--risk-profile medium`：风险档位，支持 `none/medium/strict`
- `--risk-lookback-days 20`：风控回看窗口（交易日）
- `--top 30`：控制终端展示前 N 条
- `--output-csv xxx.csv`：导出结果

### 3.1 推荐命令（生产基线）

> 使用已验证的买入规则版本 `baseline_v20260319`，并启用中等风控。

```bash
python manage.py pickbuycandidates ^
  --trade-date 2026-03-18 ^
  --scope 688 ^
  --valuation-band-pct 0.1 ^
  --risk-profile medium ^
  --risk-lookback-days 20 ^
  --top 50 ^
  --output-csv output/pick_688_2026-03-18.csv
```

### 3.2 快照缺失时启用实时估值

```bash
python manage.py pickbuycandidates ^
  --trade-date 2026-03-18 ^
  --scope 688 ^
  --use-live-valuation ^
  --cache-batch-key pick_2026-03-18 ^
  --output-csv output/pick_live_688_2026-03-18.csv
```

说明：

- 实时估值结果会写入 `prediction_backtestvaluationsnapshot`（按 `batch_key` 隔离）
- 下次同批次可复用缓存，加速命令执行
- `--refresh-cache` 可强制重算

## 4. 输出结果解读

命令会在终端打印：

- `universe`：本次扫描股票数
- `candidates`：通过候选规则与风控后的数量
- `risk_profile`：本次使用的风控档位
- `top_candidates`：按低估分排序的候选预览

关键字段：

- `undervalue_score`：低估强度（越高越强）
- `composite_gap_pct`：组合估值相对现价的上行空间（%）
- `conservative_gap_pct`：保守估值相对现价的上行空间（%）
- `core_under_count`：核心估值方法中被判低估的方法数量
- `trailing_vol_pct`：入场前窗口波动率（%）
- `trailing_drawdown_pct`：入场前窗口回撤（%）
- `buy_candidate_rule_version`：候选规则版本（用于复现）
- `buy_candidate_reason`：命中原因文本

## 5. 回测验证（建议）

当日策略应用前，建议用相同参数做样本回测：

```bash
python manage.py backtestbuycandidates ^
  --start-date 2026-01-15 ^
  --end-date 2026-03-18 ^
  --scope 688 ^
  --horizons 5,10,20 ^
  --mode live ^
  --cache-batch-key bt_688_v20260319 ^
  --valuation-band-pct 0.1 ^
  --max-trailing-vol-pct 3.5 ^
  --max-trailing-drawdown-pct 12.0 ^
  --output-csv output/backtest_688_v20260319.csv
```

建议关注：

- 20 日平均收益与胜率
- 候选数量是否过少（信号过窄）
- 不同风险阈值下收益/回撤权衡

## 6. 运维建议

1. 日常执行使用固定 `batch_key` 命名规范（日期 + 策略版本）
2. 每次参数变更都记录 `rule_version + risk_profile + band_pct`
3. 定期清理过旧临时缓存批次，避免表体积无上限增长
4. 生产任务优先输出 CSV，便于审计与复盘

## 7. 故障排查

1. 报“指定日期和范围内没有可选股票”：
   - 检查该日 `StockTradingHistory(freq='D')` 是否有数据
   - 检查 `scope` 前缀是否写错

2. 候选为 0：
   - 先用 `--risk-profile none` 确认是否被风控二筛全部挡掉
   - 适度放宽 `--valuation-band-pct` 或风险阈值

3. 执行慢：
   - 避免每次都 `--refresh-cache`
   - 对 live 模式设置稳定 `--cache-batch-key` 复用结果
   - 使用 `--code-offset/--code-limit` 做抽样排查

## 8. 自动命名 bat（任务计划推荐）

已提供脚本：`daily_pick_candidates.bat`

功能：

- 自动以“日期 + 策略版本”命名输出 CSV 与日志
- 默认策略版本：`baseline_v20260319`
- 默认范围：`688`，默认风险档位：`medium`

输出示例：

- `output/pick_688_2026-03-19_baseline_v20260319.csv`
- `output/logs/pick_688_2026-03-19_baseline_v20260319.log`

直接运行：

```bash
daily_pick_candidates.bat
```

已接入现有日常流程：

- `daily_funda_prediction.bat` 在 `predict --freq=D` 成功后，会自动调用 `daily_pick_candidates.bat`
- 若选股失败，daily 流程会返回非 0 退出码，便于任务计划捕获失败

如需调整策略版本或参数，编辑 bat 顶部变量：

- `STRATEGY_VERSION`
- `SCOPE`
- `RISK_PROFILE`
- `VALUATION_BAND_PCT`
- `RISK_LOOKBACK_DAYS`

## 9. 日常任务链路（推荐）

当前建议的日常链路：

1. 运行 `daily_trading.bat`（日线行情）
2. 运行 `daily_cost.bat`（成本数据）
3. 运行 `daily_funda_prediction.bat`（财务 + 预测 + 自动选股）

说明：

- `daily_funda_prediction.bat` 内部已串联：`predict --freq=D` -> `daily_pick_candidates.bat`
- 当 `predict` 或 `daily_pick_candidates` 任一步骤失败时，脚本返回非 0
- 可直接用于 Windows Task Scheduler 的失败告警判定

### 9.1 Task Scheduler 配置建议（Windows）

- Program/script：`C:\Windows\System32\cmd.exe`
- Add arguments：`/c daily_funda_prediction.bat`
- Start in：项目目录（例如 `C:\Users\HANJ29\Development\code\sms\smartinvestor_be`）

建议开启：

- 失败重试（例如 10 分钟后重试 1 次）
- 失败时邮件或企业IM告警

## 10. 模板刷新进度可视化（syncswvaluation）

在仅同步估值参数模板（`--params-only`）时，任务可能持续较久。为避免中途“静默执行”难以判断状态，建议开启进度打印。

示例命令：

```bash
python manage.py syncswvaluation ^
  --params-only ^
  --progress-every 10
```

参数说明：

- `--progress-every N`：每处理 N 个申万 L3 行业打印一次进度
- `N=1`：最细粒度，几乎每个行业都打印
- `N=0`：关闭进度打印（保持默认安静模式）

快速验证（小样本）：

```bash
python manage.py syncswvaluation ^
  --params-only ^
  --max-industries 3 ^
  --sample-size 1 ^
  --progress-every 1 ^
  --dry-run
```

预期会看到：

- 启动提示（开始执行同步）
- 连续进度行（如 `params_l3 1/3`, `2/3`, `3/3`）
- 最终汇总（`申万估值同步完成`）
