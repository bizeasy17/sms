# 回测历史弹窗参数列折叠与最大持仓天数展示需求（UAT）

## 背景
- 页面：`smartinvestor_fe/src/views/BacktestExecuteView.vue`
- 问题1：回测历史弹窗中的“参数设置”列文本过长，占用横向空间，影响浏览。
- 问题2：`max_holding_days` 在回测执行和参数回填中可用，但“参数设置”列未显示。

## 根因定位
- 前端参数列由 `compactParams(params)` 生成。
- `compactParams` 的 `selectedKeys` 未包含 `max_holding_days`，导致该字段即使存在也不会展示。

## 目标
1. “参数设置”列默认折叠展示，减少横向占用。
2. 用户可按行展开/收起完整参数内容。
3. 参数文本中包含 `max_holding_days`（有值时显示）。

## 非目标
- 不改动后端 API 协议。
- 不改动回测计算逻辑。
- 不改动参数回填逻辑。

## 方案（仅前端）
1. 在“手动回测”和“网格搜索”两张历史表的“参数设置”列中：
   - 默认显示折叠文本（单行或限定高度）。
   - 增加“展开/收起”交互，查看完整参数字符串。
2. 在 `compactParams(params)` 的 `selectedKeys` 中加入 `max_holding_days`。
3. 保持与现有样式一致，避免影响其他列宽和分页行为。

## 验收标准
1. 打开“查看回测历史”弹窗：参数列默认显著更紧凑。
2. 点击“展开”后可看到完整参数，点击“收起”恢复折叠。
3. 任一包含 `max_holding_days` 的历史记录，在参数列可见 `max_holding_days=...`。
4. 双击历史行加载回测结果与参数回填行为不受影响。

## 风险与回滚
- 风险：仅前端展示层变化，风险低。
- 回滚：回退 `BacktestExecuteView.vue` 的参数列模板和 `compactParams` 改动即可。
