<template>
  <DefaultLayout>
    <div class="backtest-execute-page">
      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <span>回测执行（模板 + 批量扫描）</span>
          </div>
        </template>

        <el-row :gutter="12" class="row-gap">
          <el-col :xs="24" :md="8">
            <el-select v-model="selectedTemplateId" placeholder="策略模板" style="width: 100%" @change="handleTemplateChanged">
              <el-option label="不使用模板（手动参数）" value="" />
              <el-option
                v-for="item in templates"
                :key="item.template_id"
                :label="item.template_name"
                :value="item.template_id"
              />
            </el-select>
          </el-col>
          <el-col :xs="24" :md="16" class="actions-left">
            <el-button type="primary" :loading="runningSingle" :disabled="runningSingle" @click="executeSingleRun">执行单次回测（异步日志）</el-button>
            <el-button type="warning" :loading="submittingScan" :disabled="submittingScan" @click="submitScanTask">提交批量扫描</el-button>
            <el-button
              type="primary"
              @click="openSaveWeeklyStrategyDialog"
            >
              保存为周选股策略
            </el-button>
            <el-button @click="openRunHistoryDialog">查看回测历史</el-button>
          </el-col>
        </el-row>

        <el-row :gutter="12" class="row-gap">
          <el-col :xs="24" :md="6">
            <el-form-item label="执行模式" label-position="top">
              <el-select v-model="form.mode" style="width: 100%">
                <el-option label="账户模式" value="account" />
                <el-option label="信号模式" value="signal" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="开始日期" label-position="top" :error="fieldErrors.start_date || ''">
              <el-date-picker v-model="form.start_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="结束日期" label-position="top" :error="fieldErrors.end_date || ''">
              <el-date-picker v-model="form.end_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="最低分数" label-position="top">
              <el-input-number v-model="form.min_score" :min="0" :max="100" :step="1" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="估值带宽" label-position="top">
              <el-input-number v-model="form.band_pct" :min="0.01" :max="1" :step="0.01" :precision="2" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="风险等级" label-position="top">
              <el-input v-model="form.risk_level" placeholder="LOW 或 LOW,MEDIUM" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">止盈策略</el-divider>

        <el-row :gutter="12" class="row-gap">
          <el-col :xs="24" :md="6">
            <el-form-item label="止盈模式" label-position="top">
              <el-select v-model="form.take_profit_mode" style="width: 100%">
                <el-option label="固定止盈" value="fixed" />
                <el-option label="动态止盈" value="dynamic" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="止盈阈值" label-position="top">
              <el-input-number v-model="form.take_profit_pct" :min="0" :max="1" :step="0.01" :precision="2" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="3">
            <el-form-item label="趋势止盈开关" label-position="top">
              <el-switch v-model="form.trend_take_profit_enabled" inline-prompt active-text="开" inactive-text="关" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="3">
            <el-form-item label="趋势仓比例" label-position="top" :error="fieldErrors.trend_position_pct || ''">
              <el-input-number v-model="form.trend_position_pct" :min="0" :max="1" :step="0.01" :precision="2" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="3">
            <el-form-item label="趋势止盈激活阈值" label-position="top" :error="fieldErrors.trend_activation_profit || ''">
              <el-input-number v-model="form.trend_activation_profit" :min="0" :max="1" :step="0.01" :precision="2" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="3">
            <el-form-item label="目标价止盈" label-position="top">
              <el-switch
                v-model="form.disable_target_hit"
                :active-value="false"
                :inactive-value="true"
                inline-prompt
                active-text="开"
                inactive-text="关"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12" class="row-gap">
          <el-col :xs="24" :md="6">
            <el-form-item label="趋势止盈MA周期" label-position="top">
              <el-input-number v-model="form.trend_ma_period" :min="2" :max="250" :step="1" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="趋势止盈确认天数" label-position="top">
              <el-input-number v-model="form.trend_confirm_days" :min="1" :max="20" :step="1" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="最大持有天数" label-position="top">
              <el-input-number v-model="form.max_holding_days" :min="0" :max="3650" :step="1" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="阶梯止盈配置" label-position="top" :error="fieldErrors.take_profit_tiers_text || ''">
              <el-input
                v-model="form.take_profit_tiers_text"
                placeholder="示例: 0.15:0.4,0.25:0.3"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">止损策略</el-divider>

        <el-row :gutter="12" class="row-gap">
          <el-col :xs="24" :md="6">
            <el-form-item label="止损模式" label-position="top">
              <el-select v-model="form.stop_loss_mode" style="width: 100%">
                <el-option label="固定止损" value="fixed" />
                <el-option label="移动止损" value="trailing" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="止损阈值" label-position="top" :error="fieldErrors.stop_loss_pct || ''">
              <el-input-number v-model="form.stop_loss_pct" :min="0" :max="1" :step="0.01" :precision="2" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="追踪止损回撤" label-position="top">
              <el-input-number v-model="form.trailing_stop_pct" :min="0" :max="1" :step="0.01" :precision="2" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="止损作用域" label-position="top" :error="fieldErrors.stop_loss_scope || ''">
              <el-select v-model="form.stop_loss_scope" style="width: 100%">
                <el-option label="单票止损" value="position" />
                <el-option label="账户止损（净值）" value="account" :disabled="form.mode !== 'account'" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12" class="row-gap">
        <el-divider content-position="left">基本面策略</el-divider>
          <el-col :xs="24" :md="6">
            <el-form-item label="净利YoY最小值" label-position="top">
              <el-input-number v-model="form.min_netprofit_yoy" :min="-100" :max="300" :step="1" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="EBITYoY最小值" label-position="top">
              <el-input-number v-model="form.min_ebit_yoy" :min="-100" :max="300" :step="1" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="上一年净利不为负" label-position="top">
              <el-switch v-model="form.require_positive_prev_netprofit" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="上一年EBIT不为负" label-position="top">
              <el-switch v-model="form.require_positive_prev_ebit" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">技术面策略</el-divider>

        <el-row :gutter="12" class="row-gap">
          <el-col :xs="24" :md="4">
            <el-form-item label="启用技术过滤" label-position="top">
              <el-switch v-model="form.technical_strategy_enabled" inline-prompt active-text="开" inactive-text="关" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="4">
            <el-form-item label="回看窗口" label-position="top" :error="fieldErrors.technical_lookback_days || ''">
              <el-select v-model="form.technical_lookback_days" style="width: 100%" :disabled="!form.technical_strategy_enabled">
                <el-option label="30天" :value="30" />
                <el-option label="60天" :value="60" />
                <el-option label="90天" :value="90" />
                <el-option label="120天" :value="120" />
                <el-option label="200天" :value="200" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="16">
            <el-form-item label="低分位因子（10%）" label-position="top" :error="fieldErrors.technical_factors || ''">
              <el-radio-group v-model="form.technical_factors" :disabled="!form.technical_strategy_enabled">
                <el-radio-button label="price">股价</el-radio-button>
                <el-radio-button label="pe">PE</el-radio-button>
                <el-radio-button label="pb">PB</el-radio-button>
                <el-radio-button label="ps">PS</el-radio-button>
                <el-radio-button label="turnover_rate_f">换手率</el-radio-button>
                <el-radio-button label="volume_ratio">量比</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </el-col>
        </el-row>

        <template v-if="form.mode === 'account'">
          <el-divider content-position="left">账户与仓位</el-divider>
          <el-row :gutter="12" class="row-gap">
            <el-col :xs="24" :md="6">
              <el-form-item label="账户资金" label-position="top" :error="fieldErrors.starting_capital || ''">
                <el-input-number v-model="form.starting_capital" :min="10000" :step="10000" style="width: 100%" />
              </el-form-item>
            </el-col>

            <el-col :xs="24" :md="6">
              <el-form-item label="单票仓位上限" label-position="top" :error="fieldErrors.max_position_pct || ''">
                <el-input-number v-model="form.max_position_pct" :min="0.01" :max="1" :step="0.01" :precision="2" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :md="6">
              <el-form-item label="首次建仓比例" label-position="top" :error="fieldErrors.first_entry_pct || ''">
                <el-input-number v-model="form.first_entry_pct" :min="0.01" :max="1" :step="0.01" :precision="2" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :md="6">
              <el-form-item label="每日最多新开仓" label-position="top">
                <el-input-number v-model="form.max_buy_per_day" :min="1" :max="20" :step="1" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>

          <el-row :gutter="12" class="row-gap">
            <el-col :xs="24" :md="6">
              <el-form-item label="首次加仓比例" label-position="top" :error="fieldErrors.add_on_entry_pct || ''">
                <el-input-number v-model="form.add_on_entry_pct" :min="0" :max="1" :step="0.01" :precision="2" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :md="6">
              <el-form-item label="首次加仓触发跌幅" label-position="top">
                <el-input-number v-model="form.add_on_drop_pct" :min="0" :max="0.5" :step="0.01" :precision="2" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :md="6">
              <el-form-item label="二次加仓触发跌幅" label-position="top" :error="fieldErrors.add_on2_drop_pct || ''">
                <el-input-number v-model="form.add_on2_drop_pct" :min="0" :max="0.5" :step="0.01" :precision="2" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :md="6">
              <el-form-item label="二次补满剩余仓位" label-position="top" :error="fieldErrors.add_on2_fill_remaining || ''">
                <el-switch v-model="form.add_on2_fill_remaining" inline-prompt active-text="开" inactive-text="关" />
              </el-form-item>
            </el-col>
          </el-row>

          <el-row :gutter="12" class="row-gap">
            <el-col :xs="24" :md="8">
              <el-form-item label="优先策略" label-position="top">
                <el-select v-model="form.priority_policy" style="width: 100%">
                  <el-option label="低估高分优先" value="score_desc" />
                  <el-option label="折价空间优先" value="deep_discount_first" />
                  <el-option label="组合目标折价优先" value="target_discount_first" />
                  <el-option label="高股价优先" value="high_price_first" />
                  <el-option label="低股价优先" value="low_price_first" />
                  <el-option label="低风险高分优先" value="low_risk_high_score" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :xs="24" :md="8">
              <el-form-item label="仓位梯度分配" label-position="top">
                <el-input v-model="form.buy_weight_ladder_text" placeholder="例如: 0.2,0.15,0.1；按优先策略排名分配" clearable />
              </el-form-item>
            </el-col>
          </el-row>
        </template>

        <el-divider content-position="left">批量扫描参数（网格搜索）</el-divider>

        <el-alert
          type="info"
          :closable="false"
          show-icon
          class="row-gap"
          title="批量扫描会复用上方回测参数，并按分数/带宽/止盈模式/止盈/止损/风险网格做组合扫描。"
        />

        <el-row :gutter="12" class="row-gap">
          <el-col :xs="24" :md="6">
            <el-form-item label="分数网格" label-position="top">
              <el-input v-model="scanGrid.min_score" placeholder="例如: 85,90,95" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="带宽网格" label-position="top">
              <el-input v-model="scanGrid.band_pct" placeholder="例如: 0.05,0.08,0.1,0.12" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="止盈模式网格" label-position="top">
              <el-input v-model="scanGrid.take_profit_mode" placeholder="例如: fixed,dynamic" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="止盈网格" label-position="top">
              <el-input v-model="scanGrid.take_profit_pct" placeholder="例如: 0.15,0.25,0.5,0.75,1" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="止损网格" label-position="top">
              <el-input v-model="scanGrid.stop_loss_pct" placeholder="例如: 0,0.03,0.05" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="风险网格" label-position="top">
              <el-input v-model="scanGrid.risk_level" placeholder="例如: LOW,MEDIUM（两档）或 LOW+MEDIUM（组合档）" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12" class="row-gap">
          <el-col :xs="24" :md="24">
            <el-form-item label="分级止盈网格（动态止盈）" label-position="top">
              <el-input
                v-model="scanGrid.take_profit_tiers"
                type="textarea"
                :rows="2"
                placeholder="每组用 ; 分隔。支持 触发:卖出比|趋势仓比例。示例：0.15:0.2,0.3:0.3,0.5:0.5|0.8; 0.1:0.2,0.25:0.3,0.4:0.5|0.7"
              />
            </el-form-item>
          </el-col>
        </el-row>
        <div class="muted" style="font-size: 12px; margin-top: -4px;">参数示例：85,90,95 / 0.05,0.08,0.1,0.12 / fixed / 0.15,0.25,0.5,0.75,1 / 0,0.03,0.05,0.1,0.15,0.2,0.25 / LOW,MEDIUM（默认两档=840组）</div>

        <div v-if="message" class="message-row row-gap">
          <el-alert
            :title="message"
            :type="messageType"
            :closable="false"
            show-icon
            class="message-alert"
          />
          <el-button
            v-if="lastRunId && messageType === 'success'"
            size="small"
            :type="isRunFavorited(lastRunId) ? 'warning' : 'default'"
            @click="toggleFavoriteRun(lastRunId)"
          >
            {{ isRunFavorited(lastRunId) ? '取消收藏本次回测' : '收藏本次回测' }}
          </el-button>
        </div>
      </el-card>

      <el-card shadow="never" v-if="showScanTaskDetails">
        <template #header>
          <div class="card-header">
            <span>批量任务执行过程</span>
            <div class="actions-left">
              <span class="muted" v-if="activeTaskId">当前 task_id={{ activeTaskId }}</span>
              <el-button size="small" :loading="loadingTasks" @click="refreshTaskListAndDetail">刷新</el-button>
            </div>
          </div>
        </template>

        <el-table
          :data="tasks"
          stripe
          border
          size="small"
          max-height="220"
          v-loading="loadingTasks"
          highlight-current-row
          @row-click="handleTaskRowClick"
        >
          <el-table-column prop="id" label="Task ID" width="90" />
          <el-table-column prop="status" label="状态" width="120" />
          <el-table-column prop="total_jobs" label="总任务" width="90" />
          <el-table-column prop="completed_jobs" label="已完成" width="90" />
          <el-table-column prop="failed_jobs" label="失败" width="90" />
          <el-table-column prop="progress_pct" label="进度%" width="90" />
          <el-table-column prop="updated_at" label="更新时间" min-width="150" :formatter="formatLocalDateTimeColumn" />
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="scope">
              <el-button
                size="small"
                type="danger"
                :disabled="!canCancelTask(scope.row)"
                @click.stop="cancelScanTask(scope.row)"
              >
                停止
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <div v-if="bestScanRun" class="row-gap" style="margin-top: 10px;">
          <el-alert
            :type="bestScanRunTieCount > 1 ? 'warning' : 'success'"
            :closable="false"
            show-icon
            :title="bestScanRunSummary"
          />

          <el-table
            :data="topScanRunRows"
            stripe
            border
            size="small"
            max-height="220"
            style="margin-top: 10px;"
            @row-click="handleTopScanRunRowClick"
          >
            <el-table-column prop="rank" label="排名" width="70" />
            <el-table-column prop="index" label="组合#" width="80" />
            <el-table-column prop="run_id" label="Run ID" width="90" />
            <el-table-column prop="trade_count" label="交易数" width="90" />
            <el-table-column prop="total_return_pct" label="总收益%" width="100" />
            <el-table-column prop="max_drawdown_pct" label="最大回撤%(账户)" width="130" />
            <el-table-column prop="win_rate_pct" label="胜率%" width="90" />
            <el-table-column prop="params_text" label="参数组合" min-width="360" />
          </el-table>
        </div>

        <el-table
          :data="taskEventRows"
          stripe
          border
          size="small"
          max-height="220"
          class="row-gap"
          style="margin-top: 10px;"
        >
          <el-table-column prop="ts" label="时间" width="190" />
          <el-table-column prop="level" label="级别" width="80" />
          <el-table-column prop="step_type" label="步骤" width="120" />
          <el-table-column prop="ts_code" label="代码" width="120" />
          <el-table-column prop="trade_date" label="交易日" width="110" />
          <el-table-column prop="message" label="消息" min-width="260" />
        </el-table>
      </el-card>

      <el-card shadow="never" v-if="lastRunId">
        <template #header>
          <div class="card-header">
            <span>本次执行股票结果（单击下方加载，双击弹窗查看）</span>
            <div class="actions-left">
              <span class="muted">run_id={{ lastRunId }}，{{ executeStockActiveTab === 'traded' ? '已交易' : '可买' }}共 {{ activeStockTabCount }} 只</span>
              <el-button size="small" :loading="executeStockActiveTab === 'traded' ? loadingLatestStocks : loadingLatestBuyableStocks" @click="refreshActiveStockTab">刷新</el-button>
            </div>
          </div>
        </template>

        <el-tabs v-model="executeStockActiveTab" @tab-change="handleExecuteStockTabChange">
          <el-tab-pane label="已交易" name="traded">
            <el-table :data="executeStockRows" stripe border size="small" v-loading="loadingLatestStocks" height="280" @row-click="handleExecuteStockRowClick" @row-dblclick="handleExecuteStockRowDoubleClick">
              <el-table-column prop="ts_code" label="代码" width="120" />
              <el-table-column prop="stock_name" label="名称" width="140" />
              <el-table-column prop="trade_count" label="交易数" width="90" />
              <el-table-column prop="win_rate_pct" label="胜率%" width="90" />
              <el-table-column prop="avg_return_pct" label="平均收益%" width="110" />
              <el-table-column prop="total_return_pct" label="总收益%" width="110" />
              <el-table-column prop="max_drawdown_pct" label="最大跌幅%" width="110" :formatter="formatNegativeDrawdownCell" />
              <el-table-column prop="avg_holding_days" label="平均持有天数" width="130" />
              <el-table-column prop="first_entry_date" label="首次买入" min-width="120" />
              <el-table-column prop="last_exit_date" label="最后卖出" min-width="120" />
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="按策略可买" name="buyable">
            <el-table
              :data="executeBuyableStockRows"
              stripe
              border
              size="small"
              v-loading="loadingLatestBuyableStocks"
              height="280"
              :row-class-name="getBuyableRowClassName"
              @row-click="handleExecuteStockRowClick"
              @row-dblclick="handleExecuteStockRowDoubleClick"
            >
              <el-table-column prop="ts_code" label="代码" width="120" />
              <el-table-column prop="stock_name" label="名称" width="140" />
              <el-table-column prop="hit_count" label="触发次数" width="90" />
              <el-table-column prop="max_score" label="最高分" width="100" />
              <el-table-column prop="best_discount_pct" label="最佳折价%" width="110" />
              <el-table-column prop="latest_entry_price" label="最新股价" width="110" />
              <el-table-column prop="latest_conservative_price" label="最新保守估值价" width="140" />
              <el-table-column prop="first_hit_date" label="首次触发" min-width="120" />
              <el-table-column prop="last_hit_date" label="最后触发" min-width="120" />
            </el-table>
          </el-tab-pane>
        </el-tabs>

        <div v-if="loadingLatestStockDetail || executeStockTradeRows.length" class="table-section">
          <div class="card-header">
            <span>
              详细交易
              <template v-if="executeStockCode">
                ：{{ executeStockCode }}{{ executeStockName ? ` ${executeStockName}` : '' }}
              </template>
            </span>
            <span class="muted" v-if="executeStockRange.start_date || executeStockRange.end_date">
              {{ executeStockRange.start_date || '-' }} ~ {{ executeStockRange.end_date || '-' }}
            </span>
          </div>

          <el-table :data="executeStockTradeRows" stripe border size="small" v-loading="loadingLatestStockDetail" max-height="260" class="trade-table">
            <el-table-column prop="entry_date" label="买入日" width="110" />
            <el-table-column prop="entry_price" label="买入价" width="100" />
            <el-table-column prop="exit_date" label="卖出日" width="110" />
            <el-table-column prop="exit_price" label="卖出价" width="100" />
            <el-table-column prop="return_pct" label="收益%" width="100" />
            <el-table-column prop="holding_days" label="持有天数" width="100" />
            <el-table-column prop="exit_reason" label="卖出原因" min-width="140" />
          </el-table>

          <el-descriptions :column="4" border size="small" class="trade-table">
            <el-descriptions-item label="回测模式">{{ executeStockStats.mode || '-' }}</el-descriptions-item>
            <el-descriptions-item label="交易数">{{ executeStockStats.trade_count ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="收益%">{{ executeStockStats.return_pct ?? executeStockStats.avg_return_pct ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="胜率%">{{ executeStockStats.win_rate_pct ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="最大回撤%">{{ executeStockStats.max_drawdown_pct ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="Sharpe">{{ executeStockStats.sharpe_ratio ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="Profit Factor">{{ executeStockStats.profit_factor ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="Expectancy%">{{ executeStockStats.expectancy_pct ?? '-' }}</el-descriptions-item>
          </el-descriptions>
        </div>
      </el-card>

      <el-dialog v-model="executeStockDialogVisible" width="92%" top="4vh" :title="executeStockDialogTitle">
        <div class="dialog-nav-bar">
          <span class="muted">列表导航：{{ detailStockPositionText }}</span>
          <div class="actions-left">
            <el-button size="small" :disabled="loadingLatestStockDetail || !hasPrevDetailStock" @click="navigateStockDetail(-1)">上一只</el-button>
            <el-button size="small" :disabled="loadingLatestStockDetail || !hasNextDetailStock" @click="navigateStockDetail(1)">下一只</el-button>
          </div>
        </div>
        <el-row :gutter="12">
          <el-col :xs="24" :md="18">
            <v-chart v-if="executeStockKlineOption" :option="executeStockKlineOption" autoresize class="kline-chart" />

            <el-table :data="executeStockTradeRows" stripe border size="small" height="220" class="trade-table">
              <el-table-column prop="entry_date" label="买入日" width="110" />
              <el-table-column prop="entry_price" label="买入价" width="100" />
              <el-table-column prop="exit_date" label="卖出日" width="110" />
              <el-table-column prop="exit_price" label="卖出价" width="100" />
              <el-table-column prop="return_pct" label="收益%" width="100" />
              <el-table-column prop="holding_days" label="持有天数" width="100" />
              <el-table-column prop="exit_reason" label="卖出原因" min-width="120" />
            </el-table>

            <el-table :data="executeStockValuationRows" stripe border size="small" height="200" class="trade-table">
              <el-table-column prop="trade_date" label="估值日期" width="110" />
              <el-table-column prop="valuation_price" label="估值价" width="110" />
              <el-table-column prop="valuation_method" label="估值方法" width="110" />
              <el-table-column prop="valuation_variant" label="估值方案" width="140" />
              <el-table-column prop="valuation_source" label="来源" width="110" />
              <el-table-column prop="match_score" label="匹配分" width="100" />
              <el-table-column prop="valuation_market_cap" label="估值市值" min-width="140" />
            </el-table>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-descriptions :column="1" border size="small" title="Backtesting统计">
              <el-descriptions-item label="股票">{{ executeStockCode || '-' }} {{ executeStockName ? `(${executeStockName})` : '' }}</el-descriptions-item>
              <el-descriptions-item label="回测区间">{{ executeStockRange.start_date || '-' }} ~ {{ executeStockRange.end_date || '-' }}</el-descriptions-item>
              <el-descriptions-item label="模式">{{ executeStockStats.mode || '-' }}</el-descriptions-item>
              <el-descriptions-item label="交易数">{{ executeStockStats.trade_count ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="收益%">{{ executeStockStats.return_pct ?? executeStockStats.avg_return_pct ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="买入持有%">{{ executeStockStats.buy_hold_return_pct ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="胜率%">{{ executeStockStats.win_rate_pct ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="最大回撤%">{{ executeStockStats.max_drawdown_pct ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="Sharpe">{{ executeStockStats.sharpe_ratio ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="Profit Factor">{{ executeStockStats.profit_factor ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="Expectancy%">{{ executeStockStats.expectancy_pct ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="参考参数(经验)">{{ executeStockReferenceParams }}</el-descriptions-item>
              <el-descriptions-item label="一句点评">{{ executeStockBacktestComment }}</el-descriptions-item>
            </el-descriptions>

            <el-alert
              v-if="executeStockStats.warning"
              :title="executeStockStats.warning"
              type="warning"
              :closable="false"
              class="warning-box"
            />
          </el-col>
        </el-row>
      </el-dialog>

      <el-dialog v-model="saveWeeklyStrategyDialogVisible" width="520px" title="保存为周选股策略">
        <el-alert
          title="按钮常驻显示；可从已收藏回测中选择一个来源策略进行保存。"
          type="info"
          :closable="false"
          show-icon
          class="row-gap"
        />
        <el-form-item label="来源回测（可选已收藏）" label-position="top">
          <el-select
            v-model="selectedSourceRunId"
            style="width: 100%;"
            :loading="loadingWeeklyStrategyDialog"
            filterable
            clearable
            placeholder="优先选择已收藏回测，未选择则使用最近一次回测"
            @change="handleSourceRunChanged"
          >
            <el-option
              v-for="item in favoriteRunSourceOptions"
              :key="item.run_id"
              :label="item.label"
              :value="item.run_id"
            />
          </el-select>
        </el-form-item>

        <div v-if="savedStyleSummaryRows.length" class="row-gap" style="font-size: 12px; color: #606266; line-height: 1.8;">
          <div style="font-weight: 600; margin-bottom: 4px;">已保存风格策略</div>
          <div v-for="item in savedStyleSummaryRows" :key="item.style" style="padding: 4px 0; border-top: 1px dashed #ebeef5;">
            <span style="display: inline-block; min-width: 48px; color: #909399;">{{ item.style_label }}</span>
            <span>{{ item.summary }}</span>
          </div>
        </div>

        <el-form-item label="适合市场风格" label-position="top">
          <el-select v-model="weeklyStrategyForm.style" style="width: 100%;">
            <el-option label="保守" value="CONSERVATIVE" />
            <el-option label="平衡" value="BALANCED" />
            <el-option label="激进" value="AGGRESSIVE" />
          </el-select>
        </el-form-item>
        <el-form-item label="策略名称" label-position="top">
          <el-input v-model="weeklyStrategyForm.strategy_name" maxlength="64" show-word-limit placeholder="请输入策略名" />
        </el-form-item>
        <el-alert
          v-if="weeklyStrategyCompareHint"
          :title="weeklyStrategyCompareHint"
          type="info"
          :closable="false"
          show-icon
        />
        <template #footer>
          <el-button @click="saveWeeklyStrategyDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="savingWeeklyStrategy" @click="saveWeeklyStyleStrategy">保存</el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="runHistoryDialogVisible" width="88%" top="8vh" title="回测历史">
        <el-tabs v-model="historyActiveTab" @tab-change="handleHistoryTabChanged">
          <el-tab-pane label="手动回测" name="manual">
            <div class="history-toolbar row-gap">
              <span class="muted">共 {{ manualHistoryTotal }} 条</span>
              <span class="muted">收藏 {{ favoriteRunIds.length }} 条</span>
              <div class="actions-left">
                <el-button size="small" :loading="loadingManualHistory" @click="fetchManualHistoryPage(manualHistoryPage)">刷新</el-button>
              </div>
            </div>

            <el-alert
              v-if="!loadingManualHistory && !manualHistoryRows.length"
              title="当前还没有可展示的手动回测历史。"
              type="info"
              :closable="false"
              class="row-gap"
            />

            <el-table v-else :data="manualHistoryRows" stripe border size="small" max-height="460" v-loading="loadingManualHistory" @row-dblclick="handleRunHistoryRowDoubleClick">
              <el-table-column label="收藏" width="88" fixed="left">
                <template #default="scope">
                  <el-button link type="warning" @click.stop="toggleFavoriteRun(scope.row.run_id)">
                    {{ isRunFavorited(scope.row.run_id) ? '★ 已藏' : '☆ 收藏' }}
                  </el-button>
                </template>
              </el-table-column>
              <el-table-column prop="run_id" label="Run ID" width="90" fixed="left" />
              <el-table-column prop="run_key" label="Run Key" min-width="220" fixed="left" />
              <el-table-column prop="mode" label="模式" width="90" />
              <el-table-column prop="start_date" label="开始日期" width="110" />
              <el-table-column prop="end_date" label="结束日期" width="110" />
              <el-table-column prop="source" label="来源" width="90" />
              <el-table-column prop="starting_capital" label="初始资金" width="120" />
              <el-table-column prop="ending_capital" label="期末资金" width="120" />
              <el-table-column label="参数设置" min-width="320">
                <template #default="scope">
                  <span>{{ compactParams(scope.row.params || {}) }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="trade_count" label="交易数" width="90" />
              <el-table-column prop="avg_return_pct" label="平均收益%" width="110" />
              <el-table-column prop="win_rate_pct" label="胜率%" width="90" />
              <el-table-column prop="avg_holding_days" label="平均持有" width="100" />
              <el-table-column prop="total_return_pct" label="总收益%" width="100" />
              <el-table-column prop="max_drawdown_pct" label="最大回撤%" width="110" />
              <el-table-column prop="created_at" label="记录时间" min-width="160" />
            </el-table>

            <div class="table-footer row-gap">
              <el-pagination
                background
                layout="prev, pager, next, total"
                :current-page="manualHistoryPage"
                :page-size="manualHistoryPageSize"
                :total="manualHistoryTotal"
                @current-change="handleManualHistoryPageChange"
              />
            </div>
          </el-tab-pane>

          <el-tab-pane label="网格搜索" name="scan">
            <div class="history-toolbar row-gap">
              <span class="muted">共 {{ scanHistoryTotal }} 条组合结果</span>
              <div class="actions-left">
                <el-button size="small" :loading="loadingScanHistory" @click="fetchScanHistoryPage(scanHistoryPage)">刷新</el-button>
              </div>
            </div>

            <el-alert
              v-if="!loadingScanHistory && !scanHistoryRows.length"
              title="当前还没有可展示的网格搜索结果。"
              type="info"
              :closable="false"
              class="row-gap"
            />

            <el-table v-else :data="scanHistoryRows" stripe border size="small" max-height="460" v-loading="loadingScanHistory" @row-dblclick="handleRunHistoryRowDoubleClick">
              <el-table-column label="收藏" width="88" fixed="left">
                <template #default="scope">
                  <el-button link type="warning" @click.stop="toggleFavoriteRun(scope.row.run_id)">
                    {{ isRunFavorited(scope.row.run_id) ? '★ 已藏' : '☆ 收藏' }}
                  </el-button>
                </template>
              </el-table-column>
              <el-table-column prop="task_id" label="Task ID" width="90" fixed="left" />
              <el-table-column prop="combo_index" label="组合#" width="80" />
              <el-table-column prop="run_id" label="Run ID" width="90" />
              <el-table-column prop="run_key" label="Run Key" min-width="220" />
              <el-table-column prop="mode" label="模式" width="90" />
              <el-table-column prop="start_date" label="开始日期" width="110" />
              <el-table-column prop="end_date" label="结束日期" width="110" />
              <el-table-column prop="task_key" label="任务Key" min-width="180" />
              <el-table-column label="参数设置" min-width="320">
                <template #default="scope">
                  <span>{{ compactParams(scope.row.params || {}) }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="trade_count" label="交易数" width="90" />
              <el-table-column prop="avg_return_pct" label="平均收益%" width="110" />
              <el-table-column prop="win_rate_pct" label="胜率%" width="90" />
              <el-table-column prop="total_return_pct" label="总收益%" width="100" />
              <el-table-column prop="max_drawdown_pct" label="最大回撤%" width="110" />
              <el-table-column prop="created_at" label="记录时间" min-width="160" />
            </el-table>

            <div class="table-footer row-gap">
              <el-pagination
                background
                layout="prev, pager, next, total"
                :current-page="scanHistoryPage"
                :page-size="scanHistoryPageSize"
                :total="scanHistoryTotal"
                @current-change="handleScanHistoryPageChange"
              />
            </div>
          </el-tab-pane>
        </el-tabs>
      </el-dialog>
    </div>
  </DefaultLayout>
</template>

<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import axios from 'axios'
import { useRouter } from 'vue-router'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElCol,
  ElDatePicker,
  ElDescriptions,
  ElDescriptionsItem,
  ElDivider,
  ElDialog,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElPagination,
  ElOption,
  ElRadioButton,
  ElRadioGroup,
  ElRow,
  ElSelect,
  ElSwitch,
  ElTag,
  ElTabs,
  ElTabPane,
  ElTable,
  ElTableColumn,
} from 'element-plus'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { CandlestickChart, ScatterChart, LineChart } from 'echarts/charts'
import { TooltipComponent, GridComponent, DataZoomComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import DefaultLayout from '../layouts/DefaultLayout.vue'

use([CanvasRenderer, CandlestickChart, ScatterChart, LineChart, TooltipComponent, GridComponent, DataZoomComponent, LegendComponent])

type TemplateItem = {
  template_id: string
  template_name: string
  params: Record<string, any>
}

type TaskItem = {
  id: number
  status: string
  total_jobs: number
  completed_jobs: number
  failed_jobs: number
  progress_pct: number
  updated_at?: string
  result?: Record<string, any>
}

type StockSummaryRow = {
  ts_code: string
  stock_name?: string
  trade_count: number
  win_rate_pct: number
  avg_return_pct: number
  total_return_pct: number
  max_drawdown_pct?: number | null
  avg_holding_days: number
  first_entry_date?: string
  last_exit_date?: string
}

const baseURL = inject<string>('baseURL', 'http://127.0.0.1:5001/api')
const router = useRouter()

const templates = ref<TemplateItem[]>([])
const selectedTemplateId = ref('')

const runningSingle = ref(false)
const submittingScan = ref(false)
const loadingTasks = ref(false)
const loadingTaskDetail = ref(false)

const message = ref('')
const messageType = ref<'success' | 'error' | 'info' | 'warning'>('info')
const lastRunId = ref<number | null>(null)
const fieldErrors = reactive<Record<string, string>>({})

const tasks = ref<TaskItem[]>([])
const activeTaskId = ref<number | null>(null)
const taskRuns = ref<any[]>([])
const taskEvents = ref<Array<Record<string, any>>>([])
const loadingLatestStocks = ref(false)
const loadingLatestBuyableStocks = ref(false)
const loadingLatestStockDetail = ref(false)
const executeStockRows = ref<StockSummaryRow[]>([])
const executeBuyableStockRows = ref<Array<Record<string, any>>>([])
const executeBuyableRowsRunId = ref<number | null>(null)
const executeStockActiveTab = ref<'traded' | 'buyable'>('traded')
const executeStockDialogVisible = ref(false)
const executeStockDialogTitle = ref('')
const executeStockCode = ref('')
const executeStockName = ref('')
const executeStockRange = ref<Record<string, any>>({})
const executeStockKlineRows = ref<Array<Record<string, any>>>([])
const executeStockMarkers = ref<Array<Record<string, any>>>([])
const executeStockTradeRows = ref<Array<Record<string, any>>>([])
const executeStockValuationRows = ref<Array<Record<string, any>>>([])
const executeStockStats = ref<Record<string, any>>({})
const runHistoryDialogVisible = ref(false)
const historyActiveTab = ref<'manual' | 'scan'>('manual')
const manualHistoryRows = ref<Array<Record<string, any>>>([])
const manualHistoryTotal = ref(0)
const manualHistoryPage = ref(1)
const manualHistoryPageSize = ref(20)
const loadingManualHistory = ref(false)
const scanHistoryRows = ref<Array<Record<string, any>>>([])
const scanHistoryTotal = ref(0)
const scanHistoryPage = ref(1)
const scanHistoryPageSize = ref(20)
const loadingScanHistory = ref(false)
const submittedScanTaskIds = ref<number[]>([])
const singleRunTaskId = ref<number | null>(null)
let singleRunPollTimer: number | null = null
const favoriteRunIds = ref<number[]>([])
const saveWeeklyStrategyDialogVisible = ref(false)
const savingWeeklyStrategy = ref(false)
const weeklyStrategyCompareHint = ref('')
const loadingWeeklyStrategyDialog = ref(false)
const selectedSourceRunId = ref<number | undefined>(undefined)
const favoriteRunSourceOptions = ref<Array<Record<string, any>>>([])
const savedStyleStrategies = ref<Record<string, any>>({})
const weeklyStrategyForm = reactive({
  style: 'BALANCED',
  strategy_name: '',
})
const WEEKLY_STYLE_KEYS = ['CONSERVATIVE', 'BALANCED', 'AGGRESSIVE']

const FAVORITE_RUN_IDS_KEY = 'backtest.favoriteRunIds'
const showScanTaskDetails = true


const DEFAULT_FORM = {
  mode: 'account',
  scope: 'ALL',
  market: 'CN',
  start_date: '2025-01-01',
  end_date: '2025-12-31',
  band_pct: 0.1,
  min_score: 90,
  risk_level: 'LOW',
  valuation_variant: '',
  risk_variant_policy: 'any',
  min_netprofit_yoy: null as number | null,
  min_ebit_yoy: null as number | null,
  require_positive_prev_netprofit: true,
  require_positive_prev_ebit: true,
  technical_strategy_enabled: false,
  technical_lookback_days: 60,
  technical_factors: 'price',
  technical_low_quantile: 0.1,
  financial_filter_mode: 'all',
  take_profit_mode: 'fixed',
  take_profit_tiers_text: '0.15:0.15,0.3:0.2,0.5:0.15',
  trend_take_profit_enabled: false,
  trend_position_pct: 0.5,
  trend_activation_profit: 0,
  trend_ma_period: 20,
  trend_confirm_days: 2,
  take_profit_pct: 0,
  stop_loss_mode: 'fixed',
  stop_loss_pct: 0,
  trailing_stop_pct: 0,
  stop_loss_scope: 'position',
  disable_target_hit: false,
  starting_capital: 200000,
  max_position_pct: 0.2,
  first_entry_pct: 0.1,
  add_on_entry_pct: 0.05,
  add_on_drop_pct: 0.05,
  add_on2_drop_pct: 0.1,
  add_on2_fill_remaining: false,
  max_buy_per_day: 3,
  priority_policy: 'score_desc',
  buy_weight_ladder_text: '',
  max_holding_days: 0,
}

const form = reactive({ ...DEFAULT_FORM })

const scanGrid = reactive({
  min_score: '85,90,95',
  band_pct: '0.05,0.08,0.1,0.12',
  take_profit_mode: 'fixed',
  take_profit_pct: '0.15,0.25,0.5,0.75,1',
  take_profit_tiers: '',
  stop_loss_pct: '0,0.03,0.05,0.1,0.15,0.2,0.25',
  risk_level: 'LOW,MEDIUM',
})

const abRows = computed(() => {
  if (taskRuns.value.length < 2) {
    return []
  }
  const a = taskRuns.value[0] || {}
  const b = taskRuns.value[1] || {}
  const aSummary = a.summary || {}
  const bSummary = b.summary || {}

  const metrics = [
    { key: 'trade_count', label: '交易数' },
    { key: 'avg_return_pct', label: '平均收益%' },
    { key: 'median_return_pct', label: '中位收益%' },
    { key: 'win_rate_pct', label: '胜率%' },
    { key: 'avg_holding_days', label: '平均持有天数' },
  ]

  return metrics.map((item) => {
    const aValue = Number(aSummary[item.key] ?? 0)
    const bValue = Number(bSummary[item.key] ?? 0)
    return {
      metric: item.label,
      a: aSummary[item.key],
      b: bSummary[item.key],
      delta: Number.isFinite(aValue) && Number.isFinite(bValue) ? Number((bValue - aValue).toFixed(4)) : '-',
    }
  })
})

const activeStockTabCount = computed(() => {
  if (executeStockActiveTab.value === 'buyable') {
    return executeBuyableStockRows.value.length
  }
  return executeStockRows.value.length
})

function formatLocalDateTime(value: unknown): string {
  const text = String(value || '').trim()
  if (!text) {
    return ''
  }
  let normalizedText = text
  // Backend scan task timestamps may be rendered as "YYYY-MM-DD HH:mm:ss" without timezone.
  // Treat these as UTC to keep main table and event detail timeline consistent.
  if (/^\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}$/.test(text)) {
    normalizedText = `${text.replace(' ', 'T')}Z`
  }
  const parsed = new Date(normalizedText)
  if (Number.isNaN(parsed.getTime())) {
    return text
  }
  return parsed.toLocaleString()
}

function formatLocalDateTimeColumn(_row: Record<string, any>, _column: unknown, cellValue: unknown): string {
  return formatLocalDateTime(cellValue)
}

const taskEventRows = computed(() => {
  const rows = Array.isArray(taskEvents.value) ? taskEvents.value : []
  return rows
    .slice(-300)
    .reverse()
    .map((row) => ({
      ...row,
      ts: formatLocalDateTime(row?.ts),
    }))
})

function pickScanRunMetric(summary: Record<string, any>, keys: string[]): number | null {
  for (const key of keys) {
    const value = toFiniteNumber(summary?.[key])
    if (value !== null) {
      return value
    }
  }
  return null
}

function buildScanRunParamsText(params: Record<string, any>): string {
  const source = params && typeof params === 'object' ? params : {}
  const tiersText = formatTakeProfitTiersText(source.take_profit_tiers)
  const technicalFactorsText = Array.isArray(source.technical_factors)
    ? source.technical_factors.join('|')
    : String(source.technical_factors || '')
  const parts = [
    `min_score=${source.min_score ?? '-'}`,
    `band_pct=${source.band_pct ?? '-'}`,
    `take_profit_mode=${source.take_profit_mode ?? '-'}`,
    `take_profit_pct=${source.take_profit_pct ?? '-'}`,
    `take_profit_tiers=${tiersText || '-'}`,
    `trend_position_pct=${source.trend_position_pct ?? '-'}`,
    `stop_loss_pct=${source.stop_loss_pct ?? '-'}`,
    `risk_level=${source.risk_level ?? '-'}`,
    `technical=${source.technical_strategy_enabled ? 'on' : 'off'}`,
    `lookback=${source.technical_lookback_days ?? '-'}`,
    `factors=${technicalFactorsText || '-'}`,
  ]
  return parts.join(', ')
}

function toTakeProfitModeGridList(text: string): string[] {
  const modeSet = new Set(['fixed', 'dynamic'])
  return String(text || '')
    .split(/[;,|]/)
    .map((item) => String(item || '').trim().toLowerCase())
    .filter((item) => modeSet.has(item))
}

function parseTakeProfitTierGridText(text: string): Array<{
  take_profit_tiers: Array<{ trigger_pct: number, sell_ratio: number }>
  trend_position_pct: number | null
}> {
  return String(text || '')
    .split(/[;\n]/)
    .map((item) => String(item || '').trim())
    .filter((item) => item.length > 0)
    .map((item) => {
      const [tiersRaw, trendRaw] = item.split('|').map((part) => String(part || '').trim())
      const tiers = parseTakeProfitTiersText(tiersRaw)
      const trend = Number(trendRaw)
      const trendPosition = Number.isFinite(trend) ? Math.max(0, Math.min(1, trend)) : null
      return {
        take_profit_tiers: tiers,
        trend_position_pct: trendPosition,
      }
    })
    .filter((item) => item.take_profit_tiers.length > 0)
}

const rankedScanRuns = computed(() => {
  return taskRuns.value
    .map((run: any) => {
      const summary = (run?.summary && typeof run.summary === 'object') ? run.summary : {}
      const totalReturnPct = pickScanRunMetric(summary, ['total_return_pct', 'return_pct', 'final_return_pct', 'account_return_pct'])
      const maxDrawdownPct = pickScanRunMetric(summary, ['max_drawdown_pct'])
      const winRatePct = pickScanRunMetric(summary, ['win_rate_pct'])
      const tradeCount = pickScanRunMetric(summary, ['trade_count'])
      return {
        raw: run,
        index: Number(run?.index || 0),
        run_id: Number(run?.run_id || 0),
        trade_count: tradeCount,
        total_return_pct: totalReturnPct,
        max_drawdown_pct: maxDrawdownPct,
        win_rate_pct: winRatePct,
        params_text: buildScanRunParamsText(run?.params || {}),
      }
    })
    .sort((a, b) => {
      const retA = a.total_return_pct ?? Number.NEGATIVE_INFINITY
      const retB = b.total_return_pct ?? Number.NEGATIVE_INFINITY
      if (retA !== retB) {
        return retB - retA
      }
      const ddA = a.max_drawdown_pct ?? Number.POSITIVE_INFINITY
      const ddB = b.max_drawdown_pct ?? Number.POSITIVE_INFINITY
      if (ddA !== ddB) {
        return ddA - ddB
      }
      const winA = a.win_rate_pct ?? Number.NEGATIVE_INFINITY
      const winB = b.win_rate_pct ?? Number.NEGATIVE_INFINITY
      if (winA !== winB) {
        return winB - winA
      }
      return a.index - b.index
    })
})

const bestScanRun = computed(() => rankedScanRuns.value[0] || null)

const bestScanRunTieCount = computed(() => {
  const best = bestScanRun.value
  if (!best) {
    return 0
  }
  return rankedScanRuns.value.filter((row) =>
    (row.total_return_pct ?? null) === (best.total_return_pct ?? null) &&
    (row.max_drawdown_pct ?? null) === (best.max_drawdown_pct ?? null) &&
    (row.win_rate_pct ?? null) === (best.win_rate_pct ?? null)
  ).length
})

const bestScanRunSummary = computed(() => {
  const best = bestScanRun.value
  if (!best) {
    return ''
  }
  const tradeCountText = best.trade_count ?? '-'
  const tieText = bestScanRunTieCount.value > 1 ? `；当前有 ${bestScanRunTieCount.value} 个组合并列第一，默认展示第一个` : ''
  return `当前最优组合：组合#${best.index} / run_id=${best.run_id}；总收益=${formatPct(best.total_return_pct)}，最大回撤=${formatPct(best.max_drawdown_pct)}，胜率=${formatPct(best.win_rate_pct)}，交易数=${tradeCountText}；参数：${best.params_text}${tieText}`
})

const topScanRunRows = computed(() => {
  return rankedScanRuns.value.slice(0, 5).map((row, index) => ({
    rank: index + 1,
    index: row.index,
    run_id: row.run_id,
    trade_count: row.trade_count ?? '-',
    total_return_pct: formatPct(row.total_return_pct),
    max_drawdown_pct: formatPct(row.max_drawdown_pct),
    win_rate_pct: formatPct(row.win_rate_pct),
    params_text: row.params_text,
  }))
})

const currentDetailStockList = computed<Array<Record<string, any>>>(() => {
  if (executeStockActiveTab.value === 'buyable') {
    return executeBuyableStockRows.value as Array<Record<string, any>>
  }
  return executeStockRows.value as Array<Record<string, any>>
})

const tradedTsCodeSet = computed(() => {
  const set = new Set<string>()
  executeStockRows.value.forEach((item) => {
    const code = String(item?.ts_code || '').trim().toUpperCase()
    if (code) {
      set.add(code)
    }
  })
  return set
})

const currentDetailStockIndex = computed(() => {
  const currentCode = String(executeStockCode.value || '').trim().toUpperCase()
  if (!currentCode) {
    return -1
  }
  return currentDetailStockList.value.findIndex((item) => String(item?.ts_code || '').trim().toUpperCase() === currentCode)
})

const hasPrevDetailStock = computed(() => currentDetailStockIndex.value > 0)

const hasNextDetailStock = computed(() => {
  const idx = currentDetailStockIndex.value
  return idx >= 0 && idx < currentDetailStockList.value.length - 1
})

const detailStockPositionText = computed(() => {
  const total = currentDetailStockList.value.length
  const idx = currentDetailStockIndex.value
  if (total <= 0 || idx < 0) {
    return '-/-'
  }
  return `${idx + 1}/${total}`
})

function apiBase(): string {
  return String(baseURL || '').replace(/\/+$/, '')
}

function toRunId(value: unknown): number | null {
  const runId = Number(value)
  return Number.isFinite(runId) && runId > 0 ? runId : null
}

function loadFavoriteRunIds() {
  try {
    const raw = window.localStorage.getItem(FAVORITE_RUN_IDS_KEY)
    if (!raw) {
      favoriteRunIds.value = []
      return
    }
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) {
      favoriteRunIds.value = []
      return
    }
    favoriteRunIds.value = parsed
      .map((item) => toRunId(item))
      .filter((item): item is number => item !== null)
  } catch {
    favoriteRunIds.value = []
  }
}

function saveFavoriteRunIds() {
  window.localStorage.setItem(FAVORITE_RUN_IDS_KEY, JSON.stringify(favoriteRunIds.value))
}

function isRunFavorited(runIdValue: unknown): boolean {
  const runId = toRunId(runIdValue)
  if (!runId) {
    return false
  }
  return favoriteRunIds.value.includes(runId)
}

function toggleFavoriteRun(runIdValue: unknown) {
  const runId = toRunId(runIdValue)
  if (!runId) {
    return
  }
  if (favoriteRunIds.value.includes(runId)) {
    favoriteRunIds.value = favoriteRunIds.value.filter((item) => item !== runId)
  } else {
    favoriteRunIds.value = [...favoriteRunIds.value, runId]
  }
  saveFavoriteRunIds()
}

function mapBacktestScopeToPickingScope(rawScope: unknown): string {
  const scope = String(rawScope || '').trim().toUpperCase()
  if (!scope) {
    return 'SCOPE:NONE'
  }
  if (scope === 'WATCHLIST' || scope === 'SCOPE:WATCHLIST') {
    return 'WATCHLIST'
  }
  if (scope === 'ALL') {
    return '60,0,3,688'
  }
  if (scope.startsWith('SCOPE:')) {
    return scope
  }
  const normalized = scope
    .replace(/(^|,)00(?=,|$)/g, '$10')
    .replace(/(^|,)30(?=,|$)/g, '$13')
    .replace(/(^|,)68(?=,|$)/g, '$1688')
  return normalized || 'SCOPE:NONE'
}

function normalizeBacktestRiskLevel(rawRiskLevel: unknown): string {
  return String(rawRiskLevel || '')
    .split(',')
    .map((item) => item.trim().toUpperCase())
    .filter((item) => item === 'LOW' || item === 'MEDIUM' || item === 'HIGH')
    .join(',')
}

function riskLevelListFromBacktest(rawRiskLevel: unknown): string[] {
  return normalizeBacktestRiskLevel(rawRiskLevel)
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item === 'LOW' || item === 'MEDIUM' || item === 'HIGH')
}

function styleLabel(styleValue: string): string {
  if (styleValue === 'CONSERVATIVE') {
    return '保守'
  }
  if (styleValue === 'AGGRESSIVE') {
    return '激进'
  }
  return '平衡'
}

function formatPct(value: unknown): string {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? `${parsed}%` : '-'
}

function formatNegativeDrawdownCell(_row: StockSummaryRow, _column: unknown, cellValue: unknown): string {
  const parsed = Number(cellValue)
  if (!Number.isFinite(parsed)) {
    return '-'
  }
  const signed = parsed > 0 ? -parsed : parsed
  return `${Number(signed.toFixed(4))}`
}

const savedStyleSummaryRows = computed(() => {
  return WEEKLY_STYLE_KEYS
    .map((style) => {
      const payload = savedStyleStrategies.value?.[style]
      if (!payload || typeof payload !== 'object') {
        return null
      }
      const strategyName = String(payload.strategy_name || '未命名策略')
      const runId = Number(payload.source_run_id)
      const metrics = (payload.metrics && typeof payload.metrics === 'object') ? payload.metrics : {}
      const totalReturn = formatPct(metrics.total_return_pct)
      const drawdown = formatPct(metrics.max_drawdown_pct)
      const runText = Number.isFinite(runId) && runId > 0 ? `run=${runId}` : 'run=-'
      return {
        style,
        style_label: styleLabel(style),
        summary: `${strategyName}（${runText}，总收益=${totalReturn}，回撤=${drawdown}）`,
      }
    })
    .filter((item): item is { style: string, style_label: string, summary: string } => item !== null)
})

function buildFavoriteRunOptionLabel(row: Record<string, any>): string {
  const runId = Number(row?.run_id ?? row?.id)
  const summary = (row?.summary && typeof row.summary === 'object') ? row.summary : {}
  const totalReturn = formatPct(summary.total_return_pct)
  const maxDrawdown = formatPct(summary.max_drawdown_pct)
  const winRate = formatPct(summary.win_rate_pct)
  const runKey = String(row?.run_key || '')
  return `run=${runId} | ${runKey || '-'} | 收益=${totalReturn} 回撤=${maxDrawdown} 胜率=${winRate}`
}

function applyDefaultWeeklyStrategyName(runId: number | null) {
  if (String(weeklyStrategyForm.strategy_name || '').trim()) {
    return
  }
  const dateText = String(form.end_date || '').trim() || new Date().toISOString().slice(0, 10)
  if (runId && Number.isFinite(runId)) {
    weeklyStrategyForm.strategy_name = `周选股策略_${dateText}_run${runId}`
    return
  }
  weeklyStrategyForm.strategy_name = `周选股策略_${dateText}`
}

function handleSourceRunChanged() {
  if (!String(weeklyStrategyForm.strategy_name || '').trim()) {
    applyDefaultWeeklyStrategyName(toRunId(selectedSourceRunId.value))
  }
}

async function loadWeeklyStrategyDialogContext() {
  loadingWeeklyStrategyDialog.value = true
  try {
    const [configRes, runsRes] = await Promise.all([
      axios.get(`${apiBase()}/stock-pick-valuation/job-strategy-config/`),
      axios.get(`${apiBase()}/backtest/traditional/runs/`, { params: { limit: 200 } }),
    ])
    const configData = (configRes?.data?.data && typeof configRes.data.data === 'object') ? configRes.data.data : {}
    const styleMap = (configData.weekly_style_strategies && typeof configData.weekly_style_strategies === 'object')
      ? configData.weekly_style_strategies
      : {}
    savedStyleStrategies.value = styleMap

    const runRows = Array.isArray(runsRes?.data?.data) ? runsRes.data.data : []
    const favoriteIdSet = new Set<number>()
    favoriteRunIds.value.forEach((id) => {
      const parsed = toRunId(id)
      if (parsed) {
        favoriteIdSet.add(parsed)
      }
    })
    const currentRunId = toRunId(lastRunId.value)
    if (currentRunId) {
      favoriteIdSet.add(currentRunId)
    }
    const options = runRows
      .filter((row: any) => {
        const runId = Number(row?.run_id ?? row?.id)
        return Number.isFinite(runId) && favoriteIdSet.has(runId)
      })
      .map((row: any) => ({
        ...row,
        run_id: Number(row.run_id ?? row.id),
        label: buildFavoriteRunOptionLabel(row),
      }))
      .sort((a: any, b: any) => Number(b.run_id) - Number(a.run_id))
    favoriteRunSourceOptions.value = options

    if (currentRunId) {
      selectedSourceRunId.value = currentRunId
    } else if (options.length) {
      selectedSourceRunId.value = Number(options[0].run_id)
    } else {
      selectedSourceRunId.value = undefined
    }
  } catch {
    favoriteRunSourceOptions.value = []
    savedStyleStrategies.value = {}
  } finally {
    loadingWeeklyStrategyDialog.value = false
  }
}

async function openSaveWeeklyStrategyDialog() {
  weeklyStrategyForm.strategy_name = ''
  weeklyStrategyForm.style = 'BALANCED'
  weeklyStrategyCompareHint.value = '保存前会自动比较同风格已保存策略与当前回测策略。'
  await loadWeeklyStrategyDialogContext()
  applyDefaultWeeklyStrategyName(toRunId(selectedSourceRunId.value))
  saveWeeklyStrategyDialogVisible.value = true
}

function pickMetricValue(metrics: Record<string, any>, key: string): number {
  const value = Number(metrics?.[key])
  return Number.isFinite(value) ? value : 0
}

function calcWeeklyStrategyScore(metrics: Record<string, any>): number {
  const totalReturnPct = pickMetricValue(metrics, 'total_return_pct')
  const winRatePct = pickMetricValue(metrics, 'win_rate_pct')
  const sharpeRatio = pickMetricValue(metrics, 'sharpe_ratio')
  const expectancyPct = pickMetricValue(metrics, 'expectancy_pct')
  const maxDrawdownPct = pickMetricValue(metrics, 'max_drawdown_pct')
  const score = totalReturnPct * 0.6 + winRatePct * 0.2 + sharpeRatio * 10 * 0.1 + expectancyPct * 0.1 - maxDrawdownPct * 0.2
  return Number(score.toFixed(4))
}

function buildCompareHint(existingEntry: Record<string, any> | null, nextMetrics: Record<string, any>, nextScore: number): string {
  if (!existingEntry) {
    return `该风格暂无已保存策略，当前策略将作为首个${styleLabel(weeklyStrategyForm.style)}策略。`
  }
  const prevName = String(existingEntry.strategy_name || '未命名策略')
  const prevMetrics = (existingEntry.metrics && typeof existingEntry.metrics === 'object') ? existingEntry.metrics : {}
  const prevScore = Number.isFinite(Number(existingEntry.score)) ? Number(existingEntry.score) : calcWeeklyStrategyScore(prevMetrics)
  const diff = Number((nextScore - prevScore).toFixed(4))
  const nextReturn = pickMetricValue(nextMetrics, 'total_return_pct')
  const prevReturn = pickMetricValue(prevMetrics, 'total_return_pct')
  const nextDrawdown = pickMetricValue(nextMetrics, 'max_drawdown_pct')
  const prevDrawdown = pickMetricValue(prevMetrics, 'max_drawdown_pct')
  const betterText = diff >= 0 ? '更佳' : '较弱'
  return `已存在策略：${prevName}。综合分对比：新=${nextScore}，旧=${prevScore}（差值 ${diff}，新策略${betterText}）；总收益：新=${nextReturn}% 旧=${prevReturn}%；最大回撤：新=${nextDrawdown}% 旧=${prevDrawdown}%。`
}

function buildWeeklyJobConfigFromBacktestParams(params: Record<string, any>) {
  const source = params && typeof params === 'object' ? params : {}
  const riskLevels = riskLevelListFromBacktest(source.risk_level ?? form.risk_level)
  const minScoreRaw = Number(source.min_score ?? form.min_score ?? 85)
  const minScore = Number.isFinite(minScoreRaw) ? Number(minScoreRaw.toFixed(4)) : 85
  const bandRaw = Number(source.band_pct ?? form.band_pct ?? 0.1)
  const bandPct = Number.isFinite(bandRaw) ? Number(bandRaw.toFixed(4)) : 0.1
  const riskVariantPolicy = String(source.risk_variant_policy ?? form.risk_variant_policy ?? 'any').trim().toLowerCase() === 'specific'
    ? 'specific'
    : 'any'
  const financialFilterMode = String(source.financial_filter_mode ?? form.financial_filter_mode ?? 'all').trim().toLowerCase() === 'any'
    ? 'any'
    : 'all'
  const minNetprofitYoy = toNullableNumber(source.min_netprofit_yoy ?? form.min_netprofit_yoy)
  const minEbitYoy = toNullableNumber(source.min_ebit_yoy ?? form.min_ebit_yoy)
  const priorityPolicyRaw = String(source.priority_policy ?? form.priority_policy ?? 'score_desc').trim().toLowerCase()
  const priorityPolicy = ['score_desc', 'high_price_first', 'low_price_first', 'deep_discount_first', 'target_discount_first', 'low_risk_high_score'].includes(priorityPolicyRaw)
    ? priorityPolicyRaw
    : 'score_desc'
  return {
    scope: mapBacktestScopeToPickingScope(source.scope ?? form.scope),
    freq: 'W',
    valuation_band_pct: bandPct,
    pick_strategy: 'baseline',
    buy_candidate_only: 'BC:ONLY',
    traditional_min_signal_score: minScore,
    traditional_risk_level: riskLevels,
    valuation_variant: String(source.valuation_variant ?? form.valuation_variant ?? '').trim(),
    risk_variant_policy: riskVariantPolicy,
    min_netprofit_yoy: minNetprofitYoy,
    min_ebit_yoy: minEbitYoy,
    require_positive_prev_netprofit: Boolean(source.require_positive_prev_netprofit ?? form.require_positive_prev_netprofit ?? true),
    require_positive_prev_ebit: Boolean(source.require_positive_prev_ebit ?? form.require_positive_prev_ebit ?? true),
    financial_filter_mode: financialFilterMode,
    priority_policy: priorityPolicy,
  }
}

function buildWeeklySelectionParamsFromBacktestParams(params: Record<string, any>) {
  const source = params && typeof params === 'object' ? params : {}
  return {
    scope: mapBacktestScopeToPickingScope(source.scope ?? form.scope),
    band_pct: toNumberOrFallback(source.band_pct ?? form.band_pct, DEFAULT_FORM.band_pct),
    min_score: toNumberOrFallback(source.min_score ?? form.min_score, DEFAULT_FORM.min_score),
    risk_level: normalizeBacktestRiskLevel(source.risk_level ?? form.risk_level),
    valuation_variant: String(source.valuation_variant ?? form.valuation_variant ?? '').trim(),
    risk_variant_policy: String(source.risk_variant_policy ?? form.risk_variant_policy ?? 'any').trim().toLowerCase() === 'specific' ? 'specific' : 'any',
    min_netprofit_yoy: toNullableNumber(source.min_netprofit_yoy ?? form.min_netprofit_yoy),
    min_ebit_yoy: toNullableNumber(source.min_ebit_yoy ?? form.min_ebit_yoy),
    require_positive_prev_netprofit: Boolean(source.require_positive_prev_netprofit ?? form.require_positive_prev_netprofit ?? true),
    require_positive_prev_ebit: Boolean(source.require_positive_prev_ebit ?? form.require_positive_prev_ebit ?? true),
    financial_filter_mode: String(source.financial_filter_mode ?? form.financial_filter_mode ?? 'all').trim().toLowerCase() === 'any' ? 'any' : 'all',
    priority_policy: (() => {
      const raw = String(source.priority_policy ?? form.priority_policy ?? 'score_desc').trim().toLowerCase()
      return ['score_desc', 'high_price_first', 'low_price_first', 'deep_discount_first', 'target_discount_first', 'low_risk_high_score'].includes(raw)
        ? raw
        : 'score_desc'
    })(),
  }
}

async function saveWeeklyStyleStrategy() {
  const runId = toRunId(selectedSourceRunId.value) || toRunId(lastRunId.value)
  const strategyName = String(weeklyStrategyForm.strategy_name || '').trim()
  if (!runId) {
    messageType.value = 'error'
    message.value = '未找到有效来源回测，请先执行并收藏至少一个回测结果。'
    return
  }
  if (!strategyName) {
    weeklyStrategyCompareHint.value = '策略名称不能为空。'
    return
  }

  savingWeeklyStrategy.value = true
  try {
    const [runRes, configRes] = await Promise.all([
      axios.get(`${apiBase()}/backtest/traditional/runs/${runId}/`),
      axios.get(`${apiBase()}/stock-pick-valuation/job-strategy-config/`),
    ])
    const runPayload = runRes?.data || {}
    const runSummary = (runPayload?.summary && typeof runPayload.summary === 'object') ? runPayload.summary : {}
    const runParams = (runPayload?.params && typeof runPayload.params === 'object') ? runPayload.params : {}
    const configData = (configRes?.data?.data && typeof configRes.data.data === 'object') ? configRes.data.data : {}

    const existingStyleMap = (configData.weekly_style_strategies && typeof configData.weekly_style_strategies === 'object')
      ? configData.weekly_style_strategies
      : {}
    const existingEntry = (existingStyleMap[weeklyStrategyForm.style] && typeof existingStyleMap[weeklyStrategyForm.style] === 'object')
      ? existingStyleMap[weeklyStrategyForm.style]
      : null

    const nextJobPatch = buildWeeklyJobConfigFromBacktestParams(runParams)
    const nextSelectionParams = buildWeeklySelectionParamsFromBacktestParams(runParams)
    const nextJob = {
      ...(configData.job && typeof configData.job === 'object' ? configData.job : {}),
      ...nextJobPatch,
    }
    const nextQuickProfiles = configData.quick_profiles && typeof configData.quick_profiles === 'object'
      ? configData.quick_profiles
      : {}

    const nextMetrics: Record<string, any> = {
      total_return_pct: runSummary.total_return_pct,
      max_drawdown_pct: runSummary.max_drawdown_pct,
      win_rate_pct: runSummary.win_rate_pct,
      sharpe_ratio: runSummary.sharpe_ratio,
      profit_factor: runSummary.profit_factor,
      expectancy_pct: runSummary.expectancy_pct,
      trade_count: runSummary.trade_count,
    }
    const nextScore = calcWeeklyStrategyScore(nextMetrics)
    const compareHint = buildCompareHint(existingEntry, nextMetrics, nextScore)
    weeklyStrategyCompareHint.value = compareHint

    const confirmText = `${compareHint}\n\n是否继续保存并覆盖该风格原策略？`
    if (!window.confirm(confirmText)) {
      return
    }

    const nextStyleEntry = {
      strategy_name: strategyName,
      source_run_id: runId,
      run_key: String(runPayload?.run_key || ''),
      saved_at_utc: new Date().toISOString(),
      metrics: nextMetrics,
      score: nextScore,
      compare: {
        previous_strategy_name: String(existingEntry?.strategy_name || ''),
        score_diff: existingEntry ? Number((nextScore - Number(existingEntry?.score || 0)).toFixed(4)) : null,
      },
      job: nextJob,
      quick_profiles: nextQuickProfiles,
      selection_params: nextSelectionParams,
    }

    const nextStyleMap = {
      ...(existingStyleMap || {}),
      [weeklyStrategyForm.style]: nextStyleEntry,
    }
    const nextPayload = {
      ...configData,
      market_style: {
        ...(configData.market_style && typeof configData.market_style === 'object' ? configData.market_style : {}),
        default_style: weeklyStrategyForm.style,
        current_style: weeklyStrategyForm.style,
      },
      weekly_style_strategies: nextStyleMap,
    }

    await axios.post(`${apiBase()}/stock-pick-valuation/job-strategy-config/`, nextPayload)
    saveWeeklyStrategyDialogVisible.value = false
    messageType.value = 'success'
    message.value = `已保存${styleLabel(weeklyStrategyForm.style)}周选股策略：${strategyName}。${compareHint}`
  } catch (error: any) {
    messageType.value = 'error'
    message.value = error?.response?.data?.error || error?.response?.data?.message || error?.message || '保存周选股策略失败'
  } finally {
    savingWeeklyStrategy.value = false
  }
}

function useCurrentBacktestParamsForPicking() {
  const query: Record<string, string> = {
    source: 'backtest_execute',
    trade_date: String(form.end_date || '').trim(),
    scope: mapBacktestScopeToPickingScope(form.scope),
    picking_mode: 'MODE:BASELINE',
    valuation_method: 'VM:RECOMMENDED',
    valuation_status: 'VS:NONE',
    valuation_band_pct: String(form.band_pct ?? '').trim(),
    valuation_pick_strategy: 'VPS:BASELINE',
    buy_candidate_only: 'BC:NONE',
    earnings_report_type: 'ERT:ALL',
    signal_action: 'SA:ALL',
    risk_level: normalizeBacktestRiskLevel(form.risk_level),
    min_signal_score: String(form.min_score ?? '').trim(),
    feature_data_source: 'EDS:ALL',
    netprofit_growth: 'NPG:ALL',
  }
  router.push({
    path: '/picking-valuation',
    query,
  })
}

function toNumberList(text: string): number[] {
  return String(text || '')
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
    .map((item) => Number(item))
    .filter((item) => Number.isFinite(item))
}

function toRiskLevelGridList(text: string): string[] {
  const raw = String(text || '').trim()
  if (!raw) {
    return []
  }
  // Default: comma means separate risk buckets (e.g. LOW,MEDIUM => [LOW, MEDIUM]).
  // Use '+' to express a combined bucket (e.g. LOW+MEDIUM => LOW,MEDIUM).
  const chunks = raw.split(/[;,|]/g)
  return chunks
    .map((item) => item.replace(/\+/g, ','))
    .map((item) => normalizeBacktestRiskLevel(item))
    .filter((item) => item.length > 0)
}

function parseTakeProfitTiersText(text: string): Array<{ trigger_pct: number, sell_ratio: number }> {
  return String(text || '')
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
    .map((item) => {
      const [triggerRaw, sellRaw] = item.split(':').map((part) => String(part || '').trim())
      const triggerPct = Number(triggerRaw)
      const sellRatio = Number(sellRaw)
      if (!Number.isFinite(triggerPct) || !Number.isFinite(sellRatio)) {
        return null
      }
      return { trigger_pct: triggerPct, sell_ratio: sellRatio }
    })
    .filter((item): item is { trigger_pct: number, sell_ratio: number } => item !== null)
}

function formatTakeProfitTiersText(value: unknown): string {
  if (!Array.isArray(value)) {
    return ''
  }
  return value
    .map((item) => {
      if (!item || typeof item !== 'object') {
        return ''
      }
      const triggerPct = Number((item as any).trigger_pct)
      const sellRatio = Number((item as any).sell_ratio)
      if (!Number.isFinite(triggerPct) || !Number.isFinite(sellRatio)) {
        return ''
      }
      return `${triggerPct}:${sellRatio}`
    })
    .filter((item) => item.length > 0)
    .join(',')
}

function getBuyableRowClassName(args: { row: Record<string, any> }): string {
  const code = String(args?.row?.ts_code || '').trim().toUpperCase()
  if (!code) {
    return ''
  }
  return tradedTsCodeSet.value.has(code) ? 'buyable-row--traded' : ''
}

function buildScanGridPayload() {
  const payload: Record<string, Array<any>> = {}
  const minScoreList = toNumberList(scanGrid.min_score)
  const bandList = toNumberList(scanGrid.band_pct)
  const takeProfitModeList = toTakeProfitModeGridList(scanGrid.take_profit_mode)
  const takeProfitList = toNumberList(scanGrid.take_profit_pct)
  const takeProfitTierGridList = parseTakeProfitTierGridText(scanGrid.take_profit_tiers)
  const takeProfitTierList = takeProfitTierGridList.map((item) => item.take_profit_tiers)
  const takeProfitBundleList = takeProfitTierGridList
    .filter((item) => item.trend_position_pct !== null)
    .map((item) => ({
      take_profit_mode: 'dynamic',
      take_profit_tiers: item.take_profit_tiers,
      trend_position_pct: item.trend_position_pct,
    }))
  const stopLossList = toNumberList(scanGrid.stop_loss_pct)
  const riskLevelList = toRiskLevelGridList(scanGrid.risk_level)
  if (minScoreList.length) {
    payload.min_score = minScoreList
  }
  if (bandList.length) {
    payload.band_pct = bandList
  }
  if (takeProfitBundleList.length) {
    payload.take_profit_bundle = takeProfitBundleList
  } else if (takeProfitModeList.length) {
    payload.take_profit_mode = takeProfitModeList
  }
  if (takeProfitList.length) {
    payload.take_profit_pct = takeProfitList
  }
  if (takeProfitTierList.length && !takeProfitBundleList.length) {
    payload.take_profit_tiers = takeProfitTierList as any
  }
  if (stopLossList.length) {
    payload.stop_loss_pct = stopLossList
  }
  if (riskLevelList.length) {
    payload.risk_level = riskLevelList
  }
  return payload
}

function compactParams(params: Record<string, any>) {
  const selectedKeys = [
    'mode',
    'min_score',
    'band_pct',
    'take_profit_pct',
    'stop_loss_pct',
    'stop_loss_mode',
    'trailing_stop_pct',
    'stop_loss_scope',
    'disable_target_hit',
    'take_profit_mode',
    'trend_position_pct',
    'trend_activation_profit',
    'trend_take_profit_enabled',
    'trend_ma_period',
    'trend_confirm_days',
    'risk_level',
    'require_positive_prev_netprofit',
    'require_positive_prev_ebit',
    'technical_strategy_enabled',
    'technical_lookback_days',
    'technical_factors',
    'max_position_pct',
    'max_buy_per_day',
    'first_entry_pct',
    'add_on_entry_pct',
    'add_on_drop_pct',
    'add_on2_drop_pct',
    'add_on2_fill_remaining',
    'priority_policy',
  ]
  return selectedKeys
    .filter((key) => params && params[key] !== undefined && params[key] !== null)
    .map((key) => `${key}=${params[key]}`)
    .join(' | ')
}

function upsertGeneratedRunHistory(row: Record<string, any>) {
  const runId = Number(row?.run_id)
  if (!Number.isFinite(runId) || runId <= 0) {
    return
  }
  const summary = (row?.summary && typeof row.summary === 'object') ? row.summary : {}
  const startingCapital = summary.starting_capital ?? summary.initial_capital ?? summary.initial_cash ?? '-'
  const endingCapital = summary.ending_capital ?? summary.final_capital ?? summary.final_asset ?? '-'
  const payload = {
    run_id: runId,
    run_key: String(row?.run_key || ''),
    source: String(row?.source || 'execute'),
    batch_key: String(row?.batch_key || ''),
    task_id: Number(row?.task_id || 0) || null,
    task_key: String(row?.task_key || ''),
    combo_index: Number(row?.combo_index || row?.index || 0) || null,
    start_date: String(row?.start_date || row?.params?.start_date || ''),
    end_date: String(row?.end_date || row?.params?.end_date || ''),
    created_at: String(row?.created_at || new Date().toLocaleString()),
    starting_capital: startingCapital,
    ending_capital: endingCapital,
    trade_count: summary.trade_count ?? '-',
    avg_return_pct: summary.avg_return_pct ?? '-',
    win_rate_pct: summary.win_rate_pct ?? '-',
    avg_holding_days: summary.avg_holding_days ?? '-',
    median_return_pct: summary.median_return_pct ?? '-',
    total_return_pct: summary.total_return_pct ?? '-',
    max_drawdown_pct: summary.max_drawdown_pct ?? '-',
    sharpe_ratio: summary.sharpe_ratio ?? '-',
    sortino_ratio: summary.sortino_ratio ?? '-',
    calmar_ratio: summary.calmar_ratio ?? '-',
    profit_factor: summary.profit_factor ?? '-',
    expectancy_pct: summary.expectancy_pct ?? '-',
  }

  const targetRows = String(row?.source || '') === 'scan' ? scanHistoryRows : manualHistoryRows
  const idx = targetRows.value.findIndex((item) => Number(item.run_id) === runId)
  if (idx >= 0) {
    targetRows.value[idx] = payload
  } else {
    targetRows.value.unshift(payload)
  }
}

function normalizeRunHistoryRow(item: Record<string, any>, sourceLabel = 'all_history') {
  const summary = (item?.summary && typeof item.summary === 'object') ? item.summary : {}
  const params = (item?.params && typeof item.params === 'object') ? item.params : {}
  const runIdRaw = item?.run_id ?? item?.id
  const runId = Number(runIdRaw)
  const startingCapital = summary.starting_capital ?? summary.initial_capital ?? summary.initial_cash ?? '-'
  const endingCapital = summary.ending_capital ?? summary.final_capital ?? summary.final_asset ?? '-'
  const startDate = String(item?.start_date || params.start_date || '')
  const endDate = String(item?.end_date || params.end_date || '')
  const batchKey = String(item?.batch_key || '')
  const mode = String(params.mode || (batchKey.includes('account') ? 'account' : 'signal') || '')
  return {
    run_id: Number.isFinite(runId) ? runId : runIdRaw,
    run_key: String(item?.run_key || ''),
    batch_key: String(item?.batch_key || ''),
    source: String(item?.source || sourceLabel),
    mode,
    status: String(item?.status || ''),
    task_id: Number(item?.task_id || 0) || null,
    task_key: String(item?.task_key || ''),
    combo_index: Number(item?.combo_index ?? item?.index ?? 0) || null,
    created_at: String(item?.created_at || item?.updated_at || new Date().toLocaleString()),
    start_date: startDate,
    end_date: endDate,
    params,
    starting_capital: startingCapital,
    ending_capital: endingCapital,
    trade_count: summary.trade_count ?? '-',
    avg_return_pct: summary.avg_return_pct ?? '-',
    win_rate_pct: summary.win_rate_pct ?? '-',
    avg_holding_days: summary.avg_holding_days ?? '-',
    median_return_pct: summary.median_return_pct ?? '-',
    total_return_pct: summary.total_return_pct ?? '-',
    max_drawdown_pct: summary.max_drawdown_pct ?? '-',
    sharpe_ratio: summary.sharpe_ratio ?? '-',
    sortino_ratio: summary.sortino_ratio ?? '-',
    calmar_ratio: summary.calmar_ratio ?? '-',
    profit_factor: summary.profit_factor ?? '-',
    expectancy_pct: summary.expectancy_pct ?? '-',
  }
}

function buildExecutePayload() {
  const payload: Record<string, any> = { ...form }
  const buyWeightLadder = toNumberList(form.buy_weight_ladder_text)
  payload.take_profit_tiers = parseTakeProfitTiersText(form.take_profit_tiers_text)
  const technicalFactor = String(form.technical_factors || '').trim()
  payload.technical_factors = technicalFactor ? [technicalFactor] : []
  payload.technical_lookback_days = Number(form.technical_lookback_days || DEFAULT_FORM.technical_lookback_days)
  payload.technical_low_quantile = Number(DEFAULT_FORM.technical_low_quantile)
  delete payload.risk_alignment_mode
  delete payload.buy_weight_ladder_text
  delete payload.take_profit_tiers_text
  if (form.mode === 'account') {
    payload.buy_weight_ladder = buyWeightLadder
  } else {
    payload.stop_loss_scope = 'position'
    delete payload.starting_capital
    delete payload.max_position_pct
    delete payload.first_entry_pct
    delete payload.add_on_entry_pct
    delete payload.add_on_drop_pct
    delete payload.add_on2_drop_pct
    delete payload.add_on2_fill_remaining
    delete payload.max_buy_per_day
    delete payload.priority_policy
  }
  return payload
}

function getHistoryModeText(row: Record<string, any>): string {
  const mode = String(row?.mode || row?.params?.mode || '').trim().toLowerCase()
  if (mode === 'account') {
    return 'account'
  }
  if (mode === 'signal') {
    return 'signal'
  }
  const batchKey = String(row?.batch_key || '').toLowerCase()
  if (batchKey.includes('account')) {
    return 'account'
  }
  if (batchKey.includes('signal')) {
    return 'signal'
  }
  return '-'
}

function clearFieldErrors() {
  Object.keys(fieldErrors).forEach((key) => {
    delete fieldErrors[key]
  })
}

function validateExecutePayload(payload: Record<string, any>): boolean {
  clearFieldErrors()

  const startDate = String(payload.start_date || '').trim()
  const endDate = String(payload.end_date || '').trim()
  if (!startDate) {
    fieldErrors.start_date = '开始日期不能为空'
  }
  if (!endDate) {
    fieldErrors.end_date = '结束日期不能为空'
  }
  if (startDate && endDate && startDate > endDate) {
    fieldErrors.end_date = '结束日期必须大于等于开始日期'
  }

  const stopLossPct = Number(payload.stop_loss_pct)
  if (!Number.isFinite(stopLossPct) || stopLossPct < 0 || stopLossPct > 1) {
    fieldErrors.stop_loss_pct = '止损阈值需在 [0, 1]'
  }
  const stopLossScope = String(payload.stop_loss_scope || '').trim().toLowerCase()
  if (!['position', 'account'].includes(stopLossScope)) {
    fieldErrors.stop_loss_scope = '止损作用域必须是单票或账户'
  }
  if (String(payload.mode || '') !== 'account' && stopLossScope === 'account') {
    fieldErrors.stop_loss_scope = '账户止损仅支持账户模式'
  }

  const trendPositionPct = Number(payload.trend_position_pct)
  if (!Number.isFinite(trendPositionPct) || trendPositionPct < 0 || trendPositionPct > 1) {
    fieldErrors.trend_position_pct = '趋势仓比例需在 [0, 1]'
  }
  const trendActivationProfit = Number(payload.trend_activation_profit)
  if (!Number.isFinite(trendActivationProfit) || trendActivationProfit < 0 || trendActivationProfit > 1) {
    fieldErrors.trend_activation_profit = '趋势止盈激活阈值需在 [0, 1]'
  }

  const technicalEnabled = Boolean(payload.technical_strategy_enabled)
  const technicalLookback = Number(payload.technical_lookback_days)
  const technicalFactors = Array.isArray(payload.technical_factors) ? payload.technical_factors : []
  if (technicalEnabled) {
    if (!Number.isFinite(technicalLookback) || technicalLookback <= 0) {
      fieldErrors.technical_lookback_days = '回看窗口必须大于 0'
    }
    if (!technicalFactors.length) {
      fieldErrors.technical_factors = '启用技术过滤时至少选择一个因子'
    }
  }
  if (String(payload.take_profit_mode || '').trim().toLowerCase() === 'dynamic') {
    const tiers = Array.isArray(payload.take_profit_tiers) ? payload.take_profit_tiers : []
    const stepWeightSum = tiers.reduce((sum: number, tier: any) => {
      const ratio = Number(tier?.sell_ratio)
      return Number.isFinite(ratio) ? (sum + ratio) : sum
    }, 0)
    const trendEnabled = Boolean(payload.trend_take_profit_enabled)
    const effectiveTrendPct = trendEnabled ? Math.max(0, trendPositionPct || 0) : 0
    const totalWeight = stepWeightSum + effectiveTrendPct
    if (Math.abs(totalWeight - 1.0) > 1e-6) {
      fieldErrors.take_profit_tiers_text = '止盈配置总和必须为100%'
      fieldErrors.trend_position_pct = '止盈配置总和必须为100%'
    }
  }

  if (String(payload.mode || '') === 'account') {
    const startingCapital = Number(payload.starting_capital)
    const maxPositionPct = Number(payload.max_position_pct)
    const firstEntryPct = Number(payload.first_entry_pct)
    const addOnEntryPct = Number(payload.add_on_entry_pct)
    const addOn2DropPct = Number(payload.add_on2_drop_pct)
    const addOn2FillRemaining = Boolean(payload.add_on2_fill_remaining)

    if (!Number.isFinite(startingCapital) || startingCapital <= 0) {
      fieldErrors.starting_capital = '账户资金必须大于 0'
    }
    if (!Number.isFinite(maxPositionPct) || maxPositionPct <= 0 || maxPositionPct > 1) {
      fieldErrors.max_position_pct = '单票仓位上限需在 (0, 1]'
    }
    if (!Number.isFinite(firstEntryPct) || firstEntryPct <= 0) {
      fieldErrors.first_entry_pct = '首次建仓比例必须大于 0'
    } else if (Number.isFinite(maxPositionPct) && firstEntryPct > maxPositionPct) {
      fieldErrors.first_entry_pct = '首次建仓比例必须小于等于单票仓位上限'
    }

    if (!Number.isFinite(addOnEntryPct) || addOnEntryPct < 0) {
      fieldErrors.add_on_entry_pct = '首次加仓比例不能小于 0'
    } else if (Number.isFinite(maxPositionPct) && addOnEntryPct > maxPositionPct) {
      fieldErrors.add_on_entry_pct = '首次加仓比例必须小于等于单票仓位上限'
    }

    if (
      Number.isFinite(firstEntryPct) &&
      Number.isFinite(addOnEntryPct) &&
      Number.isFinite(maxPositionPct) &&
      (firstEntryPct + addOnEntryPct) > (maxPositionPct + 1e-9)
    ) {
      fieldErrors.first_entry_pct = '首次建仓比例 + 首次加仓比例 不能超过单票仓位上限'
      fieldErrors.add_on_entry_pct = '首次建仓比例 + 首次加仓比例 不能超过单票仓位上限'
    }

    if (addOn2FillRemaining && (!Number.isFinite(addOn2DropPct) || addOn2DropPct <= 0)) {
      fieldErrors.add_on2_drop_pct = '启用二次补满时，二次加仓触发跌幅必须大于 0'
      fieldErrors.add_on2_fill_remaining = '请先设置有效的二次加仓触发跌幅'
    }
  }

  return Object.keys(fieldErrors).length === 0
}

function toFiniteNumber(value: unknown): number | null {
  const num = Number(value)
  return Number.isFinite(num) ? num : null
}

function buildBacktestComment(stats: Record<string, any>): string {
  const mode = String(stats?.mode || '').toLowerCase()
  const returnPct = toFiniteNumber(stats?.return_pct)
  const drawdownPct = toFiniteNumber(stats?.max_drawdown_pct)
  const winRatePct = toFiniteNumber(stats?.win_rate_pct)
  const sharpe = toFiniteNumber(stats?.sharpe_ratio)

  if (mode === 'fallback') {
    return '当前为简化统计结果，建议补齐K线与交易样本后再判断策略稳定性。'
  }

  if (
    returnPct !== null && returnPct >= 15 &&
    drawdownPct !== null && drawdownPct <= 20 &&
    sharpe !== null && sharpe >= 1
  ) {
    return '收益与风险匹配较好，策略在当前区间表现稳健，可作为下一轮参数微调基线。'
  }

  if (
    returnPct !== null && returnPct > 0 &&
    winRatePct !== null && winRatePct >= 45
  ) {
    return '策略为正收益但优势不强，建议优先优化回撤控制与信号过滤强度。'
  }

  return '当前回测表现偏弱，建议收紧入场条件并缩短风险暴露时间后再复测。'
}

function buildReferenceParams(stats: Record<string, any>): string {
  const drawdownPct = toFiniteNumber(stats?.max_drawdown_pct)
  const winRatePct = toFiniteNumber(stats?.win_rate_pct)
  const returnPct = toFiniteNumber(stats?.return_pct)
  const tradeCount = toFiniteNumber(stats?.trade_count)

  if (tradeCount !== null && tradeCount < 5) {
    return '样本偏少：可保持 min_score=90, band_pct=0.10, take_profit_pct=0.03 先扩大样本。'
  }

  if (drawdownPct !== null && drawdownPct > 25) {
    return '回撤偏大：建议 min_score 92-95, band_pct 0.08-0.10, take_profit_pct 0.03-0.05, risk_level=LOW。'
  }

  if ((returnPct !== null && returnPct < 0) || (winRatePct !== null && winRatePct < 40)) {
    return '胜率/收益偏弱：建议 min_score 93+, band_pct 0.07-0.09, take_profit_pct 0.02-0.04。'
  }

  return '表现较优可参考：min_score 90-94, band_pct 0.08-0.12, take_profit_pct 0.03-0.06。'
}

const executeStockReferenceParams = computed(() => buildReferenceParams(executeStockStats.value || {}))
const executeStockBacktestComment = computed(() => buildBacktestComment(executeStockStats.value || {}))

const trendMaLineStyles: Record<string, { width: number; color: string }> = {
  MA6: { width: 1, color: '#5470C6' },
  MA10: { width: 1, color: '#91CC75' },
  MA25: { width: 1, color: '#FAC858' },
  MA43: { width: 1, color: '#EE6666' },
  MA60: { width: 1, color: '#73C0DE' },
  MA120: { width: 1, color: '#3BA272' },
  MA200: { width: 1, color: '#FC8452' },
}

function buildMaSeries(rows: Array<Record<string, any>>, period: number): Array<number | null> {
  const closes = rows.map((row) => Number(row?.close))
  return closes.map((_, idx) => {
    if (idx + 1 < period) {
      return null
    }
    let sum = 0
    for (let i = idx - period + 1; i <= idx; i += 1) {
      const value = closes[i]
      if (!Number.isFinite(value)) {
        return null
      }
      sum += value
    }
    return Number((sum / period).toFixed(4))
  })
}

function buildFlatQuantileSeries(rows: Array<Record<string, any>>, quantile: number): Array<number | null> {
  const values = rows
    .map((row) => Number(row?.close))
    .filter((value) => Number.isFinite(value))
    .sort((a, b) => a - b)
  if (!values.length) {
    return rows.map(() => null)
  }
  const position = (values.length - 1) * quantile
  const lowerIndex = Math.floor(position)
  const upperIndex = Math.ceil(position)
  const lower = values[lowerIndex]
  const upper = values[upperIndex] ?? lower
  const interpolated = lower + (upper - lower) * (position - lowerIndex)
  const rounded = Number(interpolated.toFixed(4))
  return rows.map(() => rounded)
}

function formatKlineTooltip(rows: Array<Record<string, any>>, axisValue: unknown): string {
  const tradeDate = String(axisValue ?? '')
  const index = rows.findIndex((row) => String(row?.trade_date || '') === tradeDate)
  const currentRow = index >= 0 ? rows[index] : null
  const close = toFiniteNumber(currentRow?.close)
  const prevClose = index > 0 ? toFiniteNumber(rows[index - 1]?.close) : null
  const pctChange = close !== null && prevClose !== null && prevClose !== 0
    ? `${(((close - prevClose) / prevClose) * 100).toFixed(2)}%`
    : '-'
  const closeText = close !== null ? close.toFixed(4) : '-'
  return `${tradeDate}<br/>收盘价: ${closeText}<br/>涨跌幅: ${pctChange}`
}

const executeStockKlineOption = computed(() => {
  if (!executeStockKlineRows.value.length) {
    return null
  }
  const xAxisData = executeStockKlineRows.value.map((item) => item.trade_date)
  const candleData = executeStockKlineRows.value.map((item) => [item.open, item.close, item.low, item.high])

  const buyPoints = executeStockMarkers.value
    .filter((item) => item?.type === 'buy')
    .map((item) => ({ value: [item.trade_date, item.price], tradeDate: item.trade_date, price: item.price }))
    .filter((item) => item.tradeDate && item.price !== undefined && item.price !== null)

  const sellPoints = executeStockMarkers.value
    .filter((item) => item?.type === 'sell')
    .map((item) => ({ value: [item.trade_date, item.price], tradeDate: item.trade_date, price: item.price }))
    .filter((item) => item.tradeDate && item.price !== undefined && item.price !== null)

  const buyCandidatePoints = executeStockMarkers.value
    .filter((item) => item?.type === 'buy_candidate')
    .map((item) => ({ value: [item.trade_date, item.price], tradeDate: item.trade_date, price: item.price }))
    .filter((item) => item.tradeDate && item.price !== undefined && item.price !== null)

  const maPeriods = [6, 10, 25, 43, 60, 120, 200]
  const maSeries = maPeriods.map((period) => {
    const name = `MA${period}`
    const lineStyle = trendMaLineStyles[name] || { width: 1, color: '#94a3b8' }
    return {
      name,
      type: 'line',
      data: buildMaSeries(executeStockKlineRows.value, period),
      smooth: true,
      showSymbol: false,
      lineStyle,
    }
  })

  const upperPriceQuantile = buildFlatQuantileSeries(executeStockKlineRows.value, 0.9)
  const lowerPriceQuantile = buildFlatQuantileSeries(executeStockKlineRows.value, 0.1)
  return {
    animation: false,
    legend: { data: ['K线', ...maPeriods.map((period) => `MA${period}`), '收盘价 90%分位', '收盘价 10%分位', '买点', '卖点', '可买点'] },
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => formatKlineTooltip(executeStockKlineRows.value, Array.isArray(params) && params.length ? params[0]?.axisValue : ''),
    },
    grid: { left: 40, right: 20, top: 30, bottom: 60 },
    xAxis: {
      type: 'category',
      data: xAxisData,
      scale: true,
      boundaryGap: true,
      axisLine: { onZero: false },
    },
    yAxis: { scale: true, splitArea: { show: true } },
    dataZoom: [
      { type: 'inside', start: 60, end: 100 },
      { show: true, type: 'slider', top: '90%', start: 60, end: 100 },
    ],
    series: [
      { name: 'K线', type: 'candlestick', data: candleData },
      ...maSeries,
      {
        name: '收盘价 90%分位',
        type: 'line',
        data: upperPriceQuantile,
        smooth: true,
        showSymbol: false,
        lineStyle: { color: '#ef4444', width: 1, type: 'dashed' },
      },
      {
        name: '收盘价 10%分位',
        type: 'line',
        data: lowerPriceQuantile,
        smooth: true,
        showSymbol: false,
        lineStyle: { color: '#16a34a', width: 1, type: 'dashed' },
      },
      {
        name: '买点',
        type: 'scatter',
        data: buyPoints,
        symbol: 'triangle',
        symbolSize: 18,
        symbolOffset: [0, -12],
        itemStyle: { color: '#dc2626' },
        label: { show: true, formatter: '买', position: 'top', color: '#991b1b', fontSize: 11, fontWeight: 700 },
      },
      {
        name: '卖点',
        type: 'scatter',
        data: sellPoints,
        symbol: 'triangle',
        symbolRotate: 180,
        symbolSize: 18,
        symbolOffset: [0, 12],
        itemStyle: { color: '#16a34a' },
        label: { show: true, formatter: '卖', position: 'bottom', color: '#166534', fontSize: 11, fontWeight: 700 },
      },
      {
        name: '可买点',
        type: 'scatter',
        data: buyCandidatePoints,
        symbol: 'diamond',
        symbolSize: 16,
        itemStyle: { color: '#2563eb' },
        label: { show: true, formatter: '可买', position: 'top', color: '#1d4ed8', fontSize: 11, fontWeight: 700 },
      },
    ],
  }
})

async function fetchTemplates() {
  try {
    const resp = await axios.get(`${apiBase()}/backtest/traditional/templates/`)
    templates.value = Array.isArray(resp?.data?.data) ? resp.data.data : []
  } catch {
    templates.value = []
  }
}

function applyTemplate(templateId: string) {
  const target = templates.value.find((item) => item.template_id === templateId)
  if (!target || !target.params) {
    return
  }
  Object.assign(form, target.params)
}

function handleTemplateChanged(value: string) {
  if (!value) {
    return
  }
  applyTemplate(value)
}

function buildBacktestingMetricSummary(summary: Record<string, any>) {
  const items: Array<{ key: string; label: string }> = [
    { key: 'total_return_pct', label: '总收益%' },
    { key: 'max_drawdown_pct', label: '最大回撤%' },
    { key: 'sharpe_ratio', label: 'Sharpe' },
    { key: 'sortino_ratio', label: 'Sortino' },
    { key: 'calmar_ratio', label: 'Calmar' },
    { key: 'profit_factor', label: 'ProfitFactor' },
    { key: 'expectancy_pct', label: 'Expectancy%' },
    { key: 'sqn', label: 'SQN' },
  ]
  return items
    .filter((item) => summary?.[item.key] !== undefined && summary?.[item.key] !== null && summary?.[item.key] !== '')
    .map((item) => `${item.label}=${summary[item.key]}`)
    .join('，')
}

async function executeSingleRun() {
  runningSingle.value = true
  message.value = ''
  lastRunId.value = null
  singleRunTaskId.value = null
  executeBuyableStockRows.value = []
  executeBuyableRowsRunId.value = null
  try {
    const payload = buildExecutePayload()
    if (!validateExecutePayload(payload)) {
      messageType.value = 'error'
      message.value = '参数校验未通过，请先修正高亮字段。'
      runningSingle.value = false
      return
    }

    const resp = await axios.post(`${apiBase()}/backtest/traditional/scan/submit/`, {
      template_id: selectedTemplateId.value || undefined,
      base_params: { ...payload },
      scan_grid: {},
    })
    const data = resp?.data || {}
    activeTaskId.value = data?.task_id ? Number(data.task_id) : null
    if (!activeTaskId.value) {
      messageType.value = 'error'
      message.value = '任务提交失败：未返回 task_id。'
      runningSingle.value = false
      return
    }
    if (activeTaskId.value && !submittedScanTaskIds.value.includes(activeTaskId.value)) {
      submittedScanTaskIds.value.push(activeTaskId.value)
    }
    singleRunTaskId.value = activeTaskId.value
    messageType.value = 'success'
    message.value = `单次异步回测已提交，task_id=${activeTaskId.value}`
    await fetchTasks()
    const status = await fetchTaskDetail(singleRunTaskId.value || undefined)
    if (!status || !['success', 'partial_success', 'failed'].includes(status)) {
      messageType.value = 'info'
      message.value = `任务执行中，task_id=${activeTaskId.value}。完成前按钮将保持禁用。`
      startSingleRunPolling(singleRunTaskId.value || undefined)
    }
  } catch (error: any) {
    messageType.value = 'error'
    message.value = error?.response?.data?.error || error?.message || '执行失败'
    stopSingleRunPolling()
    runningSingle.value = false
    singleRunTaskId.value = null
  }
}

async function fetchLatestRunStocks() {
  if (!lastRunId.value) {
    executeStockRows.value = []
    executeBuyableStockRows.value = []
    executeBuyableRowsRunId.value = null
    return
  }
  loadingLatestStocks.value = true
  try {
    const resp = await axios.get(`${apiBase()}/backtest/traditional/runs/${lastRunId.value}/stocks/`)
    executeStockRows.value = Array.isArray(resp?.data?.data) ? resp.data.data : []
  } catch {
    executeStockRows.value = []
  } finally {
    loadingLatestStocks.value = false
  }
}

async function fetchLatestRunBuyableStocks() {
  if (!lastRunId.value) {
    executeBuyableStockRows.value = []
    executeBuyableRowsRunId.value = null
    return
  }
  const targetRunId = Number(lastRunId.value)
  loadingLatestBuyableStocks.value = true
  try {
    const resp = await axios.get(`${apiBase()}/backtest/traditional/runs/${lastRunId.value}/buy-candidates/`, {
      params: { limit: 600 },
    })
    executeBuyableStockRows.value = Array.isArray(resp?.data?.data) ? resp.data.data : []
    executeBuyableRowsRunId.value = targetRunId
  } catch {
    executeBuyableStockRows.value = []
    executeBuyableRowsRunId.value = targetRunId
  } finally {
    loadingLatestBuyableStocks.value = false
  }
}

function refreshActiveStockTab() {
  if (executeStockActiveTab.value === 'buyable') {
    void fetchLatestRunBuyableStocks()
    return
  }
  void fetchLatestRunStocks()
}

function handleExecuteStockTabChange(name: string | number) {
  if (String(name) === 'buyable' && (executeBuyableRowsRunId.value !== lastRunId.value || !executeBuyableStockRows.value.length)) {
    void fetchLatestRunBuyableStocks()
  }
}

function navigateStockDetail(step: number) {
  if (loadingLatestStockDetail.value) {
    return
  }
  const list = currentDetailStockList.value
  if (!list.length) {
    return
  }
  const currentIdx = currentDetailStockIndex.value
  if (currentIdx < 0) {
    return
  }
  const targetIdx = currentIdx + Number(step)
  if (targetIdx < 0 || targetIdx >= list.length) {
    return
  }
  const tsCode = String(list[targetIdx]?.ts_code || '').trim()
  if (!tsCode) {
    return
  }
  void fetchLatestRunStockDetail(tsCode)
}

async function fetchLatestRunStockDetail(tsCode: string, options?: { openDialog?: boolean }) {
  if (!lastRunId.value || !tsCode) {
    return
  }
  const openDialog = options?.openDialog !== false
  loadingLatestStockDetail.value = true
  if (openDialog) {
    executeStockDialogVisible.value = true
  }
  executeStockCode.value = tsCode
  executeStockName.value = ''
  executeStockRange.value = {}
  if (openDialog) {
    executeStockDialogTitle.value = `${tsCode} - 加载中...`
  }
  executeStockTradeRows.value = []
  executeStockMarkers.value = []
  executeStockKlineRows.value = []
  executeStockValuationRows.value = []
  executeStockStats.value = {}
  try {
    const encodedCode = encodeURIComponent(tsCode)
    const resp = await axios.get(`${apiBase()}/backtest/traditional/runs/${lastRunId.value}/stocks/${encodedCode}/`)
    const data = resp?.data || {}
    executeStockCode.value = String(data.ts_code || tsCode)
    executeStockName.value = String(data.stock_name || '')
    executeStockRange.value = (data.range && typeof data.range === 'object') ? data.range : {}
    executeStockKlineRows.value = Array.isArray(data.kline) ? data.kline : []
    executeStockMarkers.value = Array.isArray(data.markers) ? data.markers : []
    executeStockTradeRows.value = Array.isArray(data.trades) ? data.trades : []
    executeStockValuationRows.value = Array.isArray(data.valuation_history) ? data.valuation_history : []
    executeStockStats.value = data.stats || {}
    if (openDialog) {
      executeStockDialogTitle.value = `${executeStockCode.value}${executeStockName.value ? ` ${executeStockName.value}` : ''} - K线与触发点`
    }
  } catch (error: any) {
    executeStockStats.value = { mode: 'fallback', warning: error?.response?.data?.error || error?.message || '查询单股详情失败' }
  } finally {
    loadingLatestStockDetail.value = false
  }
}

function handleExecuteStockRowClick(row: StockSummaryRow) {
  void fetchLatestRunStockDetail(row.ts_code, { openDialog: false })
}

function handleExecuteStockRowDoubleClick(row: StockSummaryRow) {
  void fetchLatestRunStockDetail(row.ts_code, { openDialog: true })
}

async function submitScanTask() {
  submittingScan.value = true
  message.value = ''
  try {
    const payload = buildExecutePayload()
    if (!validateExecutePayload(payload)) {
      messageType.value = 'error'
      message.value = '参数校验未通过，请先修正高亮字段。'
      return
    }

    const resp = await axios.post(`${apiBase()}/backtest/traditional/scan/submit/`, {
      template_id: selectedTemplateId.value || undefined,
      base_params: { ...payload },
      scan_grid: buildScanGridPayload(),
    })
    const data = resp?.data || {}
    activeTaskId.value = data?.task_id ? Number(data.task_id) : null
    if (activeTaskId.value && !submittedScanTaskIds.value.includes(activeTaskId.value)) {
      submittedScanTaskIds.value.push(activeTaskId.value)
    }
    messageType.value = 'success'
    message.value = `扫描任务已提交，task_id=${activeTaskId.value}`
    await fetchTasks()
  } catch (error: any) {
    messageType.value = 'error'
    message.value = error?.response?.data?.error || error?.message || '提交失败'
  } finally {
    submittingScan.value = false
  }
}

async function fetchTasks() {
  loadingTasks.value = true
  try {
    const resp = await axios.get(`${apiBase()}/backtest/traditional/scan/tasks/`, {
      params: { limit: 20 },
    })
    const warningText = String(resp?.data?.warning || '').trim()
    if (warningText) {
      messageType.value = 'warning'
      message.value = `扫描任务日志不可用：${warningText}`
    }
    tasks.value = Array.isArray(resp?.data?.data) ? resp.data.data : []
    if (!activeTaskId.value && tasks.value.length) {
      activeTaskId.value = Number(tasks.value[0].id)
    }
    if (activeTaskId.value) {
      const target = tasks.value.find((item) => Number(item.id) === Number(activeTaskId.value))
      if (target) {
        taskRuns.value = Array.isArray(target?.result?.runs) ? target.result?.runs : []
        taskEvents.value = Array.isArray(target?.result?.events) ? target.result.events : []
      }
    }
  } catch {
    // Scan task table may be unavailable in some envs; keep history features working.
    tasks.value = []
    taskRuns.value = []
    taskEvents.value = []
    messageType.value = 'warning'
    message.value = '扫描任务日志不可用：请检查 backtest 扫描任务表是否已迁移。'
  } finally {
    loadingTasks.value = false
  }
}

async function fetchTaskDetail(taskId?: number): Promise<string> {
  const resolvedTaskId = Number(taskId ?? activeTaskId.value ?? 0)
  if (!resolvedTaskId) {
    return ''
  }
  activeTaskId.value = resolvedTaskId
  loadingTaskDetail.value = true
  try {
    const resp = await axios.get(`${apiBase()}/backtest/traditional/scan/tasks/${resolvedTaskId}/`)
    const payload = resp?.data?.data || {}
    taskRuns.value = Array.isArray(payload?.result?.runs) ? payload.result.runs : []
    taskEvents.value = Array.isArray(payload?.result?.events) ? payload.result.events : []

    if (activeTaskId.value && submittedScanTaskIds.value.includes(Number(activeTaskId.value))) {
      taskRuns.value.forEach((item) => {
        upsertGeneratedRunHistory({
          run_id: item?.run_id,
          run_key: item?.run_key,
          summary: item?.summary,
          source: 'scan',
        })
      })
    }

    const status = String(payload?.status || '')
    const isSingleRunTask = singleRunTaskId.value && Number(resolvedTaskId) === Number(singleRunTaskId.value)
    if (isSingleRunTask && ['success', 'partial_success'].includes(status)) {
      const firstRun = taskRuns.value.find((item) => Number(item?.run_id) > 0)
      if (firstRun && Number(firstRun.run_id) > 0) {
        lastRunId.value = Number(firstRun.run_id)
        const summary = firstRun?.summary || {}
        const startingCapital = summary.starting_capital ?? summary.initial_capital ?? summary.initial_cash
        const endingCapital = summary.ending_capital ?? summary.final_capital ?? summary.final_asset
        const metricSummary = buildBacktestingMetricSummary(summary)
        messageType.value = 'success'
        message.value = `执行成功，run_id=${lastRunId.value}，交易数=${summary.trade_count ?? '-'}，胜率=${summary.win_rate_pct ?? '-'}%${startingCapital !== undefined && endingCapital !== undefined ? `，初始资金=${startingCapital}，期末资金=${endingCapital}` : ''}${metricSummary ? `，评价指标：${metricSummary}` : ''}`
        await fetchLatestRunStocks()
        if (executeStockActiveTab.value === 'buyable') {
          await fetchLatestRunBuyableStocks()
        }
      }
      stopSingleRunPolling()
      runningSingle.value = false
      singleRunTaskId.value = null
    } else if (isSingleRunTask && status === 'failed') {
      messageType.value = 'error'
      message.value = payload?.error_message || '单次异步回测失败'
      stopSingleRunPolling()
      runningSingle.value = false
      singleRunTaskId.value = null
    }
    return status
  } finally {
    loadingTaskDetail.value = false
  }
}

function startSingleRunPolling(taskId?: number) {
  stopSingleRunPolling()
  const targetTaskId = Number(taskId ?? singleRunTaskId.value ?? 0)
  if (!targetTaskId) {
    return
  }
  singleRunPollTimer = window.setInterval(() => {
    void fetchTaskDetail(targetTaskId)
  }, 4000)
}

function stopSingleRunPolling() {
  if (singleRunPollTimer) {
    window.clearInterval(singleRunPollTimer)
    singleRunPollTimer = null
  }
}

function handleTaskRowClick(row: TaskItem) {
  activeTaskId.value = Number(row.id)
  taskRuns.value = Array.isArray(row?.result?.runs) ? row.result?.runs : []
  taskEvents.value = Array.isArray(row?.result?.events) ? row.result?.events : []
  const firstRun = taskRuns.value.find((item) => Number(item?.run_id) > 0)
  const firstRunId = Number(firstRun?.run_id || 0)
  if (firstRunId > 0) {
    void switchToRunDetail(firstRunId, {
      applyParams: false,
      messagePrefix: '已从批量任务加载明细',
    })
  }
}

async function switchToRunDetail(
  runId: number,
  options?: {
    applyParams?: boolean
    messagePrefix?: string
  },
) {
  if (!Number.isFinite(runId) || runId <= 0) {
    return
  }
  lastRunId.value = runId
  executeBuyableStockRows.value = []
  executeBuyableRowsRunId.value = null

  const shouldApplyParams = options?.applyParams === true
  const paramsLoaded = shouldApplyParams ? await applyRunParamsToForm(runId) : false

  await fetchLatestRunStocks()
  if (executeStockActiveTab.value === 'buyable') {
    await fetchLatestRunBuyableStocks()
  }

  messageType.value = 'info'
  const prefix = options?.messagePrefix || '已切换到回测结果'
  message.value = `${prefix}，run_id=${runId}，执行选股结果已加载${shouldApplyParams ? (paramsLoaded ? '，参数设置已回填。' : '，参数设置加载失败。') : '。'}`
}

function handleTopScanRunRowClick(row: Record<string, any>) {
  const runId = Number(row?.run_id || 0)
  if (runId > 0) {
    void switchToRunDetail(runId, {
      applyParams: false,
      messagePrefix: '已从 Top5 组合加载明细',
    })
  }
}

async function refreshTaskListAndDetail() {
  await fetchTasks()
  if (activeTaskId.value) {
    await fetchTaskDetail(activeTaskId.value)
  }
}

function canCancelTask(row: TaskItem): boolean {
  const status = String(row?.status || '').trim().toLowerCase()
  return status === 'pending' || status === 'running' || status === 'cancel_requested'
}

async function cancelScanTask(row: TaskItem) {
  const taskId = Number(row?.id || 0)
  if (!taskId) {
    return
  }
  try {
    await axios.post(`${apiBase()}/backtest/traditional/scan/tasks/${taskId}/cancel/`)
    messageType.value = 'warning'
    message.value = `已请求停止 task_id=${taskId}`
    await fetchTasks()
    await fetchTaskDetail(taskId)
  } catch (error: any) {
    messageType.value = 'error'
    message.value = error?.response?.data?.error || error?.message || '停止任务失败'
  }
}

function toNumberOrFallback(value: unknown, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function toNullableNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') {
    return null
  }
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

async function applyRunParamsToForm(runId: number): Promise<boolean> {
  try {
    const resp = await axios.get(`${apiBase()}/backtest/traditional/runs/${runId}/`)
    const detail = resp?.data || {}
    const replayParams = (detail?.replay_params && typeof detail.replay_params === 'object') ? detail.replay_params : {}
    const strategy = (detail?.result?.strategy && typeof detail.result.strategy === 'object') ? detail.result.strategy : {}
    const params = (detail?.params && typeof detail.params === 'object') ? detail.params : {}
    const merged = Object.keys(replayParams).length ? replayParams : { ...strategy, ...params }

    const runKey = String(detail?.run_key || '')
    const modeText = String(merged.mode || '').trim().toLowerCase()
    const inferredMode = modeText === 'account' || runKey.includes('_account_') || merged.starting_capital !== undefined
      ? 'account'
      : 'signal'

    const buyWeightLadder = Array.isArray(merged.buy_weight_ladder)
      ? merged.buy_weight_ladder.map((item: unknown) => Number(item)).filter((item: number) => Number.isFinite(item))
      : []

    Object.assign(form, {
      mode: inferredMode,
      scope: String(merged.scope ?? DEFAULT_FORM.scope),
      market: String(merged.market ?? DEFAULT_FORM.market),
      start_date: String(merged.start_date ?? DEFAULT_FORM.start_date),
      end_date: String(merged.end_date ?? DEFAULT_FORM.end_date),
      band_pct: toNumberOrFallback(merged.band_pct, DEFAULT_FORM.band_pct),
      min_score: toNumberOrFallback(merged.min_score, DEFAULT_FORM.min_score),
      risk_level: String(merged.risk_level ?? DEFAULT_FORM.risk_level),
      valuation_variant: String(merged.valuation_variant ?? DEFAULT_FORM.valuation_variant),
      risk_variant_policy: String(merged.risk_variant_policy ?? DEFAULT_FORM.risk_variant_policy),
      min_netprofit_yoy: toNullableNumber(merged.min_netprofit_yoy),
      min_ebit_yoy: toNullableNumber(merged.min_ebit_yoy),
      require_positive_prev_netprofit: Boolean(merged.require_positive_prev_netprofit ?? DEFAULT_FORM.require_positive_prev_netprofit),
      require_positive_prev_ebit: Boolean(merged.require_positive_prev_ebit ?? DEFAULT_FORM.require_positive_prev_ebit),
      technical_strategy_enabled: Boolean(merged.technical_strategy_enabled ?? DEFAULT_FORM.technical_strategy_enabled),
      technical_lookback_days: toNumberOrFallback(merged.technical_lookback_days, DEFAULT_FORM.technical_lookback_days),
      technical_factors: Array.isArray(merged.technical_factors)
        ? String(merged.technical_factors.find((item: unknown) => String(item || '').trim().length > 0) || '').trim()
        : String(merged.technical_factors || '').trim() || DEFAULT_FORM.technical_factors,
      financial_filter_mode: String(merged.financial_filter_mode ?? DEFAULT_FORM.financial_filter_mode),
      take_profit_mode: String(merged.take_profit_mode ?? DEFAULT_FORM.take_profit_mode),
      trend_position_pct: toNumberOrFallback(merged.trend_position_pct, DEFAULT_FORM.trend_position_pct),
      trend_activation_profit: toNumberOrFallback(merged.trend_activation_profit, DEFAULT_FORM.trend_activation_profit),
      trend_take_profit_enabled: Boolean(merged.trend_take_profit_enabled ?? DEFAULT_FORM.trend_take_profit_enabled),
      trend_ma_period: toNumberOrFallback(merged.trend_ma_period, DEFAULT_FORM.trend_ma_period),
      trend_confirm_days: toNumberOrFallback(merged.trend_confirm_days, DEFAULT_FORM.trend_confirm_days),
      take_profit_pct: toNumberOrFallback(merged.take_profit_pct, DEFAULT_FORM.take_profit_pct),
      stop_loss_mode: String(merged.stop_loss_mode ?? DEFAULT_FORM.stop_loss_mode),
      stop_loss_pct: toNumberOrFallback(merged.stop_loss_pct, DEFAULT_FORM.stop_loss_pct),
      trailing_stop_pct: toNumberOrFallback(merged.trailing_stop_pct, DEFAULT_FORM.trailing_stop_pct),
      stop_loss_scope: String(merged.stop_loss_scope || (inferredMode === 'account' ? DEFAULT_FORM.stop_loss_scope : 'position')),
      disable_target_hit: Boolean(merged.disable_target_hit ?? DEFAULT_FORM.disable_target_hit),
      starting_capital: toNumberOrFallback(merged.starting_capital, DEFAULT_FORM.starting_capital),
      max_position_pct: toNumberOrFallback(merged.max_position_pct, DEFAULT_FORM.max_position_pct),
      first_entry_pct: toNumberOrFallback(merged.first_entry_pct, DEFAULT_FORM.first_entry_pct),
      add_on_entry_pct: toNumberOrFallback(merged.add_on_entry_pct, DEFAULT_FORM.add_on_entry_pct),
      add_on_drop_pct: toNumberOrFallback(merged.add_on_drop_pct, DEFAULT_FORM.add_on_drop_pct),
      add_on2_drop_pct: toNumberOrFallback(merged.add_on2_drop_pct, DEFAULT_FORM.add_on2_drop_pct),
      max_holding_days: toNumberOrFallback(merged.max_holding_days, DEFAULT_FORM.max_holding_days),
      add_on2_fill_remaining: Boolean(merged.add_on2_fill_remaining ?? DEFAULT_FORM.add_on2_fill_remaining),
      max_buy_per_day: toNumberOrFallback(merged.max_buy_per_day, DEFAULT_FORM.max_buy_per_day),
      priority_policy: String(merged.priority_policy ?? DEFAULT_FORM.priority_policy),
      buy_weight_ladder_text: buyWeightLadder.join(','),
      take_profit_tiers_text: formatTakeProfitTiersText(merged.take_profit_tiers),
    })
    selectedTemplateId.value = ''
    return true
  } catch {
    return false
  }
}

async function handleRunHistoryRowDoubleClick(row: Record<string, any>) {
  const runId = Number(row?.run_id)
  if (!Number.isFinite(runId) || runId <= 0) {
    return
  }
  runHistoryDialogVisible.value = false
  await switchToRunDetail(runId, {
    applyParams: true,
    messagePrefix: '已切换到回测结果',
  })
}

async function openRunHistoryDialog() {
  historyActiveTab.value = 'manual'
  manualHistoryPage.value = 1
  scanHistoryPage.value = 1
  runHistoryDialogVisible.value = true
  await Promise.all([
    fetchManualHistoryPage(1),
    fetchScanHistoryPage(1),
  ])
}

async function fetchHistoryPage(kind: 'manual' | 'scan', page: number): Promise<void> {
  const safePage = Math.max(1, Math.floor(Number(page) || 1))
  const pageSize = kind === 'manual' ? manualHistoryPageSize.value : scanHistoryPageSize.value
  const offset = (safePage - 1) * pageSize
  const loadingRef = kind === 'manual' ? loadingManualHistory : loadingScanHistory
  const rowsRef = kind === 'manual' ? manualHistoryRows : scanHistoryRows
  const totalRef = kind === 'manual' ? manualHistoryTotal : scanHistoryTotal

  loadingRef.value = true
  try {
    const resp = await axios.get(`${apiBase()}/backtest/traditional/runs/`, {
      params: {
        kind,
        limit: pageSize,
        offset,
      },
    })
    const rows = Array.isArray(resp?.data?.data) ? resp.data.data : []
    rowsRef.value = rows.map((item: Record<string, any>) => normalizeRunHistoryRow(item, `${kind}_history`))
    totalRef.value = Number(resp?.data?.total || rowsRef.value.length || 0)
    if (kind === 'manual') {
      manualHistoryPage.value = safePage
    } else {
      scanHistoryPage.value = safePage
    }
  } catch {
    rowsRef.value = []
    totalRef.value = 0
  } finally {
    loadingRef.value = false
  }
}

async function fetchManualHistoryPage(page = manualHistoryPage.value) {
  await fetchHistoryPage('manual', page)
}

async function fetchScanHistoryPage(page = scanHistoryPage.value) {
  await fetchHistoryPage('scan', page)
}

async function handleHistoryTabChanged(tabName: string | number) {
  if (String(tabName) === 'manual' && !manualHistoryRows.value.length && !loadingManualHistory.value) {
    await fetchManualHistoryPage(manualHistoryPage.value)
  }
  if (String(tabName) === 'scan' && !scanHistoryRows.value.length && !loadingScanHistory.value) {
    await fetchScanHistoryPage(scanHistoryPage.value)
  }
}

async function handleManualHistoryPageChange(page: number) {
  await fetchManualHistoryPage(page)
}

async function handleScanHistoryPageChange(page: number) {
  await fetchScanHistoryPage(page)
}

onMounted(async () => {
  loadFavoriteRunIds()
  await fetchTemplates()
  await fetchTasks()
  await fetchLatestRunStocks()
})

onBeforeUnmount(() => {
  stopSingleRunPolling()
})
</script>

<style scoped>
.backtest-execute-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.row-gap {
  margin-bottom: 10px;
}

.actions-left {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.table-section {
  margin-top: 12px;
}

.section-title {
  margin-bottom: 8px;
  font-weight: 600;
  color: #303133;
}

.muted {
  color: #909399;
  font-size: 12px;
}

.kline-chart {
  height: 420px;
}

.trade-table {
  margin-top: 12px;
}

.warning-box {
  margin-top: 10px;
}

.dialog-nav-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.metric-header {
  display: flex;
  align-items: center;
  gap: 6px;
}

.message-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.message-alert {
  flex: 1;
}

.history-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

:deep(.el-table__row.buyable-row--traded > td) {
  background: #fff7e6 !important;
}

:deep(.el-table__row.buyable-row--traded > td:first-child) {
  border-left: 3px solid #e6a23c;
}
</style>
