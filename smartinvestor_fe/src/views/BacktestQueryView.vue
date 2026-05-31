<template>
  <DefaultLayout>
    <div class="backtest-query-page">
      <el-card shadow="never" class="query-card">
        <template #header>
          <div class="card-header">
            <span>回测结果查询</span>
          </div>
        </template>

        <el-row :gutter="12" class="row-gap">
          <el-col :xs="24" :md="8">
            <el-select v-model="sourceType" placeholder="查询源" style="width: 100%" @change="applySourcePreset">
              <el-option label="全部回测（预测+传统）" value="all" />
              <el-option label="预测估值回测" value="predictive" />
              <el-option label="传统估值回测" value="traditional" />
              <el-option label="自定义" value="custom" />
            </el-select>
          </el-col>
          <el-col :xs="24" :md="16">
            <el-input v-model="serviceBase" placeholder="服务地址，例如 http://127.0.0.1:5002/api/forecast" clearable>
              <template #prepend>Service</template>
            </el-input>
          </el-col>
        </el-row>

        <el-row :gutter="12" class="row-gap">
          <el-col :xs="24" :md="12">
            <el-input v-model="runsPath" placeholder="列表路径，例如 /backtest/runs/" clearable>
              <template #prepend>Runs Path</template>
            </el-input>
          </el-col>
          <el-col :xs="24" :md="8">
            <el-input v-model="batchKey" placeholder="batch_key（可选）" clearable>
              <template #prepend>Batch</template>
            </el-input>
          </el-col>
          <el-col :xs="24" :md="4">
            <el-input-number v-model="limit" :min="1" :max="200" :step="10" controls-position="right" style="width: 100%" />
          </el-col>
        </el-row>

        <el-row :gutter="12" class="row-gap">
          <el-col :xs="24" :md="12">
            <el-input v-model="runDetailPathTemplate" placeholder="详情路径模板，例如 /backtest/runs/{id}/" clearable>
              <template #prepend>Detail Path</template>
            </el-input>
          </el-col>
          <el-col :xs="24" :md="4">
            <el-input-number v-model="runId" :min="1" controls-position="right" style="width: 100%" placeholder="run id" />
          </el-col>
          <el-col :xs="24" :md="8" class="actions">
            <el-button type="primary" :loading="loadingList" @click="fetchRuns">刷新列表</el-button>
            <el-button :loading="loadingDetail" @click="fetchRunDetail">按ID查详情</el-button>
          </el-col>
        </el-row>

        <div class="hint-text">提示：列表支持分页，双击任一行可直接查看该条回测详情。</div>

        <el-alert
          v-if="errorMessage"
          :title="errorMessage"
          type="error"
          show-icon
          :closable="false"
          class="row-gap"
        />
      </el-card>

      <el-card shadow="never" class="list-card">
        <template #header>
          <div class="card-header">
            <span>运行列表</span>
            <span class="muted">共 {{ runs.length }} 条</span>
          </div>
        </template>

        <el-table :data="pagedRuns" stripe border size="small" v-loading="loadingList" height="360" @row-dblclick="handleRowDoubleClick">
          <el-table-column prop="source_label" label="来源" width="120" />
          <el-table-column prop="id" label="ID" width="80" />
          <el-table-column prop="batch_key" label="Batch" min-width="180" />
          <el-table-column prop="status" label="Status" width="120" />
          <el-table-column prop="summary_trade_count" label="交易数" width="90" />
          <el-table-column prop="summary_avg_return_pct" label="平均收益%" width="110" />
          <el-table-column prop="summary_median_return_pct" label="中位收益%" width="110" />
          <el-table-column prop="summary_win_rate_pct" label="胜率%" width="90" />
          <el-table-column prop="created_at_local" label="Created" min-width="220" />
          <el-table-column prop="updated_at_local" label="Updated" min-width="220" sortable />
        </el-table>
        <div class="pager-wrap">
          <el-pagination
            background
            layout="total, sizes, prev, pager, next"
            :total="runs.length"
            :page-sizes="[10, 20, 50, 100]"
            v-model:current-page="currentPage"
            v-model:page-size="pageSize"
          />
        </div>
      </el-card>

      <el-card shadow="never" class="stock-card">
        <template #header>
          <div class="card-header">
            <span>本次回测股票结果（双击看K线买卖点）</span>
            <span class="muted" v-if="selectedRunId">run_id={{ selectedRunId }}，共 {{ stockRows.length }} 只</span>
          </div>
        </template>

        <el-table :data="stockRows" stripe border size="small" v-loading="loadingStocks" height="280" @row-dblclick="handleStockRowDoubleClick">
          <el-table-column prop="ts_code" label="代码" width="120" />
          <el-table-column prop="stock_name" label="名称" width="140" />
          <el-table-column prop="trade_count" label="交易数" width="90" />
          <el-table-column prop="win_rate_pct" label="胜率%" width="90" />
          <el-table-column prop="avg_return_pct" label="平均收益%" width="110" />
          <el-table-column prop="total_return_pct" label="总收益%" width="110" />
          <el-table-column prop="avg_holding_days" label="平均持有天数" width="130" />
          <el-table-column prop="first_entry_date" label="首次买入" min-width="120" />
          <el-table-column prop="last_exit_date" label="最后卖出" min-width="120" />
        </el-table>
      </el-card>

      <el-card shadow="never" class="detail-card">
        <template #header>
          <div class="card-header">
            <span>运行详情</span>
            <span class="muted" v-if="selectedRunId">run_id={{ selectedRunId }}</span>
          </div>
        </template>

        <div v-if="detailOverviewRows.length" class="detail-section">
          <div class="section-title">基础信息</div>
          <el-descriptions :column="2" border>
            <el-descriptions-item v-for="item in detailOverviewRows" :key="item.label" :label="item.label">
              {{ item.value }}
            </el-descriptions-item>
          </el-descriptions>
        </div>

        <div v-if="detailSummaryRows.length" class="detail-section">
          <div class="section-title">摘要</div>
          <el-table :data="detailSummaryRows" border size="small">
            <el-table-column prop="label" label="指标" min-width="180" />
            <el-table-column prop="value" label="值" min-width="160" />
          </el-table>
        </div>

        <div v-if="detailStrategyRows.length" class="detail-section">
          <div class="section-title">策略参数</div>
          <el-table :data="detailStrategyRows" border size="small">
            <el-table-column prop="label" label="参数" min-width="180" />
            <el-table-column prop="value" label="值" min-width="220" />
          </el-table>
        </div>

        <div v-if="detailMetricRows.length" class="detail-section">
          <div class="section-title">年度表现</div>
          <el-table :data="detailMetricRows" border size="small">
            <el-table-column prop="year" label="年份" width="100" />
            <el-table-column prop="days" label="天数" width="90" />
            <el-table-column prop="active_days" label="活跃天数" width="100" />
            <el-table-column prop="active_ratio" label="活跃比率" width="100" />
            <el-table-column prop="avg_daily_return" label="平均日收益" width="120" />
            <el-table-column prop="cumulative_return" label="累计收益" width="120" />
            <el-table-column prop="annualized_return" label="年化收益" width="120" />
            <el-table-column prop="stop_mode" label="止损模式" width="100" />
          </el-table>
        </div>

        <div v-if="detailByYearRows.length" class="detail-section">
          <div class="section-title">按年份汇总</div>
          <el-table :data="detailByYearRows" border size="small">
            <el-table-column prop="year" label="年份" width="100" />
            <el-table-column prop="trade_count" label="交易数" width="100" />
            <el-table-column prop="avg_return_pct" label="平均收益%" width="120" />
            <el-table-column prop="median_return_pct" label="中位收益%" width="120" />
            <el-table-column prop="win_rate_pct" label="胜率%" width="100" />
            <el-table-column prop="avg_holding_days" label="平均持有天数" width="130" />
            <el-table-column prop="target_exit_count" label="目标止盈数" width="120" />
            <el-table-column prop="eop_exit_count" label="期末卖出数" width="120" />
          </el-table>
        </div>

        <div v-if="detailSampleTradeRows.length" class="detail-section">
          <div class="section-title">样本交易</div>
          <el-table :data="detailSampleTradeRows" border size="small" height="320">
            <el-table-column prop="ts_code" label="代码" width="110" />
            <el-table-column prop="entry_date" label="买入日" width="110" />
            <el-table-column prop="exit_date" label="卖出日" width="110" />
            <el-table-column prop="entry_price" label="买入价" width="100" />
            <el-table-column prop="exit_price" label="卖出价" width="100" />
            <el-table-column prop="target_price" label="目标估值价" width="110" />
            <el-table-column prop="conservative_price" label="保守估值价" width="110" />
            <el-table-column prop="valuation_price" label="估值价" width="100" />
            <el-table-column prop="valuation_method" label="估值方法" width="110" />
            <el-table-column prop="valuation_market_cap" label="估值市值" min-width="120" />
            <el-table-column prop="score" label="估值分" width="90" />
            <el-table-column prop="risk_level" label="风险级别" width="100" />
            <el-table-column prop="return_pct" label="收益%" width="100" />
            <el-table-column prop="holding_days" label="持有天数" width="100" />
            <el-table-column prop="netprofit_yoy" label="净利YoY%" width="110" />
            <el-table-column prop="ebit_yoy" label="EBITYoY%" width="110" />
            <el-table-column prop="exit_reason" label="卖出原因" min-width="120" />
          </el-table>
        </div>

        <div class="detail-section">
          <div class="section-title">原始 JSON</div>
          <pre class="json-box">{{ detailJson }}</pre>
        </div>
      </el-card>

      <el-dialog v-model="stockDialogVisible" width="92%" top="4vh" :title="stockDialogTitle">
        <el-row :gutter="12">
          <el-col :xs="24" :md="18">
            <v-chart v-if="stockKlineOption" :option="stockKlineOption" autoresize class="kline-chart" />

            <el-table :data="stockTradeRows" stripe border size="small" height="260" class="trade-table">
              <el-table-column prop="entry_date" label="买入日" width="110" />
              <el-table-column prop="entry_price" label="买入价" width="100" />
              <el-table-column prop="exit_date" label="卖出日" width="110" />
              <el-table-column prop="exit_price" label="卖出价" width="100" />
              <el-table-column prop="return_pct" label="收益%" width="100" />
              <el-table-column prop="holding_days" label="持有天数" width="100" />
              <el-table-column prop="exit_reason" label="卖出原因" min-width="120" />
            </el-table>

            <el-table :data="stockValuationRows" stripe border size="small" height="220" class="trade-table">
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
              <el-descriptions-item label="股票">{{ stockCode || '-' }} {{ stockName ? `(${stockName})` : '' }}</el-descriptions-item>
              <el-descriptions-item label="回测区间">{{ stockRange.start_date || '-' }} ~ {{ stockRange.end_date || '-' }}</el-descriptions-item>
              <el-descriptions-item label="模式">{{ stockStats.mode || '-' }}</el-descriptions-item>
              <el-descriptions-item label="交易数">{{ stockStats.trade_count ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="收益%">{{ stockStats.return_pct ?? stockStats.avg_return_pct ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="买入持有%">{{ stockStats.buy_hold_return_pct ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="胜率%">{{ stockStats.win_rate_pct ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="最大回撤%">{{ stockStats.max_drawdown_pct ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="平均回撤%">{{ stockStats.avg_drawdown_pct ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="Sharpe">{{ stockStats.sharpe_ratio ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="Sortino">{{ stockStats.sortino_ratio ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="Calmar">{{ stockStats.calmar_ratio ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="Profit Factor">{{ stockStats.profit_factor ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="Expectancy%">{{ stockStats.expectancy_pct ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="Avg Trade%">{{ stockStats.avg_trade_pct ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="Best/Worst%">{{ stockStats.best_trade_pct ?? '-' }} / {{ stockStats.worst_trade_pct ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="Exposure%">{{ stockStats.exposure_time_pct ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="Equity Final">{{ stockStats.equity_final ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="Equity Peak">{{ stockStats.equity_peak ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="SQN">{{ stockStats.sqn ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="参考参数(经验)">{{ stockReferenceParams }}</el-descriptions-item>
              <el-descriptions-item label="一句点评">{{ stockBacktestComment }}</el-descriptions-item>
            </el-descriptions>

            <el-alert
              v-if="stockStats.warning"
              :title="stockStats.warning"
              type="warning"
              :closable="false"
              class="warning-box"
            />
          </el-col>
        </el-row>
      </el-dialog>
    </div>
  </DefaultLayout>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import axios from 'axios'
import { useRoute } from 'vue-router'
import {
  ElCard,
  ElRow,
  ElCol,
  ElSelect,
  ElOption,
  ElInput,
  ElInputNumber,
  ElButton,
  ElAlert,
  ElDialog,
  ElDescriptions,
  ElDescriptionsItem,
  ElTable,
  ElTableColumn,
  ElPagination,
} from 'element-plus'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { CandlestickChart, ScatterChart, LineChart } from 'echarts/charts'
import { TooltipComponent, GridComponent, DataZoomComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import DefaultLayout from '../layouts/DefaultLayout.vue'

use([CanvasRenderer, CandlestickChart, ScatterChart, LineChart, TooltipComponent, GridComponent, DataZoomComponent, LegendComponent])

type BacktestRunItem = {
  id: number
  batch_key?: string
  status?: string
  created_at?: string
  updated_at?: string
  summary?: Record<string, unknown>
  source_label?: string
  source_key?: 'predictive' | 'traditional' | 'custom'
  detail_base?: string
  detail_path_template?: string
  summary_trade_count?: number | null
  summary_avg_return_pct?: number | null
  summary_median_return_pct?: number | null
  summary_win_rate_pct?: number | null
  [key: string]: unknown
}

type SourceType = 'all' | 'predictive' | 'traditional' | 'custom'

type SourceConfig = {
  sourceKey: 'predictive' | 'traditional' | 'custom'
  sourceLabel: string
  base: string
  runsPath: string
  detailPathTemplate: string
}

type StockSummaryRow = {
  ts_code: string
  stock_name?: string
  trade_count: number
  win_rate_pct: number
  avg_return_pct: number
  total_return_pct: number
  avg_holding_days: number
  first_entry_date?: string
  last_exit_date?: string
}

const sourceType = ref<SourceType>('all')
const serviceBase = ref('http://127.0.0.1:5002/api/forecast')
const runsPath = ref('/backtest/runs/')
const runDetailPathTemplate = ref('/backtest/runs/{id}/')
const batchKey = ref('')
const limit = ref(200)
const runId = ref<number | undefined>(undefined)
const currentPage = ref(1)
const pageSize = ref(20)

const loadingList = ref(false)
const loadingDetail = ref(false)
const loadingStocks = ref(false)
const loadingStockDetail = ref(false)
const errorMessage = ref('')

const runs = ref<BacktestRunItem[]>([])
const selectedRunId = ref<number | null>(null)
const detailJson = ref('')
const detailObject = ref<Record<string, unknown> | null>(null)
const stockRows = ref<StockSummaryRow[]>([])
const stockDialogVisible = ref(false)
const stockDialogTitle = ref('')
const stockCode = ref('')
const stockName = ref('')
const stockRange = ref<Record<string, any>>({})
const stockKlineRows = ref<Array<Record<string, any>>>([])
const stockTradeRows = ref<Array<Record<string, any>>>([])
const stockValuationRows = ref<Array<Record<string, any>>>([])
const stockStats = ref<Record<string, any>>({})
const route = useRoute()

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

const stockReferenceParams = computed(() => buildReferenceParams(stockStats.value || {}))
const stockBacktestComment = computed(() => buildBacktestComment(stockStats.value || {}))

const predictivePreset: SourceConfig = {
  sourceKey: 'predictive',
  sourceLabel: '预测估值',
  base: 'http://127.0.0.1:5002/api/forecast',
  runsPath: '/backtest/runs/',
  detailPathTemplate: '/backtest/runs/{id}/',
}

const traditionalPreset: SourceConfig = {
  sourceKey: 'traditional',
  sourceLabel: '传统估值',
  base: 'http://127.0.0.1:5001/api',
  runsPath: '/backtest/traditional/runs/',
  detailPathTemplate: '/backtest/traditional/runs/{id}/',
}

const pagedRuns = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  const end = start + pageSize.value
  return runs.value.slice(start, end)
})

const detailRoot = computed<Record<string, any>>(() => {
  const payload = detailObject.value
  if (!payload || typeof payload !== 'object') {
    return {}
  }
  const inner = payload.data
  if (inner && typeof inner === 'object' && !Array.isArray(inner)) {
    return inner as Record<string, any>
  }
  return payload as Record<string, any>
})

const detailResult = computed<Record<string, any>>(() => {
  const root = detailRoot.value
  const result = root.result
  return result && typeof result === 'object' && !Array.isArray(result) ? result as Record<string, any> : {}
})

const detailTestedPeriod = computed(() => {
  const root = detailRoot.value
  const params = root.params && typeof root.params === 'object' && !Array.isArray(root.params)
    ? root.params as Record<string, unknown>
    : {}

  const startYear = params.start_year
  const endYear = params.end_year
  if (startYear || endYear) {
    if (startYear && endYear) {
      return `${startYear}-${endYear}`
    }
    return String(startYear || endYear)
  }

  const startDate = params.start_date || root.start_date || detailResult.value.start_date
  const endDate = params.end_date || root.end_date || detailResult.value.end_date
  if (startDate || endDate) {
    if (startDate && endDate) {
      return `${startDate} ~ ${endDate}`
    }
    return String(startDate || endDate)
  }

  const byYear = detailResult.value.by_year
  if (byYear && typeof byYear === 'object' && !Array.isArray(byYear)) {
    const years = Object.keys(byYear).sort()
    if (years.length === 1) {
      return years[0]
    }
    if (years.length > 1) {
      return `${years[0]}-${years[years.length - 1]}`
    }
  }

  const metrics = detailResult.value.metrics
  if (Array.isArray(metrics)) {
    const years = metrics
      .map((item) => String((item as Record<string, unknown>).year || '').trim())
      .filter(Boolean)
      .sort()
    if (years.length === 1) {
      return years[0]
    }
    if (years.length > 1) {
      return `${years[0]}-${years[years.length - 1]}`
    }
  }

  return '-'
})

const detailOverviewRows = computed(() => {
  const root = detailRoot.value
  const rows = [
    { label: 'Run ID', value: root.run_id ?? root.id ?? selectedRunId.value ?? '-' },
    { label: 'Run Key', value: root.run_key ?? '-' },
    { label: 'Batch Key', value: root.batch_key ?? detailResult.value.batch_key ?? '-' },
    { label: '回测年份', value: detailTestedPeriod.value },
    { label: '状态', value: root.status ?? '-' },
    { label: '开始时间', value: formatDateTimeLocal(root.started_at ?? root.created_at ?? '-') },
    { label: '结束时间', value: formatDateTimeLocal(root.finished_at ?? root.updated_at ?? '-') },
  ]
  return rows.filter((item) => item.value !== undefined && item.value !== null && item.value !== '')
})

const detailSummaryRows = computed(() => {
  const rootSummary = rootObjectToRows(detailRoot.value.summary)
  if (rootSummary.length) {
    return rootSummary
  }
  return rootObjectToRows(detailResult.value.combined)
})

const detailStrategyRows = computed(() => {
  const root = detailRoot.value
  const params = root.params && typeof root.params === 'object' && !Array.isArray(root.params)
    ? root.params as Record<string, unknown>
    : {}

  const sellStrategyMap: Record<string, string> = {
    next_day: '次日调仓',
    optimistic_price: '高于乐观估值卖出',
    take_profit_pct: '利润止盈%',
    optimistic_or_take_profit: '乐观估值或利润止盈',
  }

  const rows: Array<{ label: string; value: string }> = [
    { label: '最低分数阈值', value: formatDisplayValue(params.min_score) },
    { label: '最大风险等级', value: formatDisplayValue(params.max_risk) },
    { label: '买入条件', value: '当前价 <= 保守估值价 且 分数达标 且 风险达标' },
    {
      label: '卖出策略',
      value: sellStrategyMap[String(params.sell_strategy || '')] || formatDisplayValue(params.sell_strategy),
    },
    { label: '止盈阈值(%)', value: formatDisplayValue(params.take_profit_pct) },
    { label: '止损阈值(%)', value: formatDisplayValue(params.stop_loss_pct) },
    { label: '最大持有天数', value: formatDisplayValue(params.max_holding_days) },
    { label: '止损模式', value: formatDisplayValue(params.stop_mode) },
  ]

  return rows.filter((item) => item.value !== '-' && item.value !== '')
})

const detailMetricRows = computed(() => {
  const metrics = detailResult.value.metrics
  return Array.isArray(metrics) ? metrics : []
})

const detailByYearRows = computed(() => {
  const byYear = detailResult.value.by_year
  if (!byYear || typeof byYear !== 'object' || Array.isArray(byYear)) {
    return []
  }
  return Object.entries(byYear).map(([year, payload]) => ({
    year,
    ...(payload as Record<string, unknown>),
  }))
})

const detailSampleTradeRows = computed(() => {
  const trades = detailResult.value.sample_trades
  if (!Array.isArray(trades)) {
    return []
  }
  return trades.slice(0, 50).map((trade) => {
    const row = trade && typeof trade === 'object' ? { ...(trade as Record<string, unknown>) } : {}
    if ((row.score === undefined || row.score === null || row.score === '') && row.signal_score !== undefined) {
      row.score = row.signal_score
    }
    return row
  })
})

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

const stockKlineOption = computed(() => {
  if (!stockKlineRows.value.length) {
    return null
  }
  const xAxisData = stockKlineRows.value.map((item) => item.trade_date)
  const candleData = stockKlineRows.value.map((item) => [item.open, item.close, item.low, item.high])

  const buyPoints = stockTradeRows.value
    .map((item) => ({ value: [item.entry_date, item.entry_price], tradeDate: item.entry_date, price: item.entry_price }))
    .filter((item) => item.tradeDate && item.price !== undefined && item.price !== null)

  const sellPoints = stockTradeRows.value
    .map((item) => ({ value: [item.exit_date, item.exit_price], tradeDate: item.exit_date, price: item.exit_price }))
    .filter((item) => item.tradeDate && item.price !== undefined && item.price !== null)

  const maPeriods = [6, 10, 25, 43, 60, 120, 200]
  const maSeries = maPeriods.map((period) => {
    const name = `MA${period}`
    const lineStyle = trendMaLineStyles[name] || { width: 1, color: '#94a3b8' }
    return {
      name,
      type: 'line',
      data: buildMaSeries(stockKlineRows.value, period),
      smooth: true,
      showSymbol: false,
      lineStyle,
    }
  })

  const upperPriceQuantile = buildFlatQuantileSeries(stockKlineRows.value, 0.9)
  const lowerPriceQuantile = buildFlatQuantileSeries(stockKlineRows.value, 0.1)
  const sl1Series = stockKlineRows.value.map((item) => toFiniteNumber(item?.sl1))
  const sl2Series = stockKlineRows.value.map((item) => toFiniteNumber(item?.sl2))
  const tp1Series = stockKlineRows.value.map((item) => toFiniteNumber(item?.tp1))
  const tp2Series = stockKlineRows.value.map((item) => toFiniteNumber(item?.tp2))

  return {
    animation: false,
    legend: { data: ['K线', ...maPeriods.map((period) => `MA${period}`), '收盘价 90%分位', '收盘价 10%分位', 'SL1', 'SL2', 'TP1', 'TP2', '买点', '卖点'] },
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => formatKlineTooltip(stockKlineRows.value, Array.isArray(params) && params.length ? params[0]?.axisValue : ''),
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
        name: 'SL1',
        type: 'line',
        data: sl1Series,
        smooth: true,
        showSymbol: false,
        lineStyle: { color: 'rgba(245, 158, 11, 0.5)', width: 1 },
      },
      {
        name: 'SL2',
        type: 'line',
        data: sl2Series,
        smooth: true,
        showSymbol: false,
        lineStyle: { color: 'rgba(180, 83, 9, 0.5)', width: 1 },
      },
      {
        name: 'TP1',
        type: 'line',
        data: tp1Series,
        smooth: true,
        showSymbol: false,
        lineStyle: { color: 'rgba(14, 165, 233, 0.5)', width: 1 },
      },
      {
        name: 'TP2',
        type: 'line',
        data: tp2Series,
        smooth: true,
        showSymbol: false,
        lineStyle: { color: 'rgba(3, 105, 161, 0.5)', width: 1 },
      },
      {
        name: '买点',
        type: 'scatter',
        data: buyPoints,
        symbol: 'triangle',
        symbolSize: 18,
        symbolOffset: [0, -12],
        itemStyle: { color: '#dc2626' },
        label: {
          show: true,
          formatter: '买',
          position: 'top',
          color: '#991b1b',
          fontSize: 11,
          fontWeight: 700,
        },
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
        label: {
          show: true,
          formatter: '卖',
          position: 'bottom',
          color: '#166534',
          fontSize: 11,
          fontWeight: 700,
        },
      },
    ],
  }
})

function formatDisplayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') {
    return '-'
  }
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : value.toFixed(4)
  }
  if (typeof value === 'boolean') {
    return value ? 'true' : 'false'
  }
  if (Array.isArray(value)) {
    return value.join(', ')
  }
  if (typeof value === 'object') {
    return JSON.stringify(value)
  }
  return String(value)
}

function rootObjectToRows(value: unknown): Array<{ label: string; value: string }> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return []
  }
  return Object.entries(value as Record<string, unknown>).map(([key, item]) => ({
    label: key,
    value: formatDisplayValue(item),
  }))
}

function applySourcePreset(value: SourceType) {
  if (value === 'all') {
    serviceBase.value = predictivePreset.base
    runsPath.value = predictivePreset.runsPath
    runDetailPathTemplate.value = predictivePreset.detailPathTemplate
    return
  }
  if (value === 'predictive') {
    serviceBase.value = predictivePreset.base
    runsPath.value = predictivePreset.runsPath
    runDetailPathTemplate.value = predictivePreset.detailPathTemplate
    return
  }
  if (value === 'traditional') {
    serviceBase.value = traditionalPreset.base
    runsPath.value = traditionalPreset.runsPath
    runDetailPathTemplate.value = traditionalPreset.detailPathTemplate
  }
}

function normalizedBase(): string {
  return String(serviceBase.value || '').trim().replace(/\/+$/, '')
}

function joinUrl(base: string, pathOrUrl: string): string {
  const raw = String(pathOrUrl || '').trim()
  if (!raw) {
    return ''
  }
  if (/^https?:\/\//i.test(raw)) {
    return raw
  }
  const safeBase = String(base || '').trim().replace(/\/+$/, '')
  const safePath = raw.startsWith('/') ? raw : `/${raw}`
  return `${safeBase}${safePath}`
}

function extractRuns(payload: any): BacktestRunItem[] {
  if (Array.isArray(payload)) {
    return payload
  }
  if (Array.isArray(payload?.data)) {
    return payload.data
  }
  if (Array.isArray(payload?.runs)) {
    return payload.runs
  }
  return []
}

function toNumberOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === '') {
    return null
  }
  const num = Number(value)
  return Number.isFinite(num) ? num : null
}

function formatDateTimeLocal(value: unknown): string {
  if (value === null || value === undefined || value === '') {
    return '-'
  }
  const raw = String(value).trim()
  if (!raw) {
    return '-'
  }

  let normalized = raw.includes('T') ? raw : raw.replace(' ', 'T')
  normalized = normalized.replace(/\.(\d{3})\d+(?=(Z|[+-]\d{2}:?\d{2})$)/, '.$1')
  if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(normalized)) {
    normalized = `${normalized}Z`
  }

  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) {
    return raw
  }

  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

function normalizeSummary(summary: unknown) {
  const s = (summary && typeof summary === 'object') ? (summary as Record<string, unknown>) : {}
  return {
    trade_count: toNumberOrNull(s.trade_count),
    avg_return_pct: toNumberOrNull(s.avg_return_pct),
    median_return_pct: toNumberOrNull(s.median_return_pct),
    win_rate_pct: toNumberOrNull(s.win_rate_pct),
  }
}

function normalizeRunRows(items: BacktestRunItem[], config: SourceConfig): BacktestRunItem[] {
  return items.map((item) => {
    const summary = normalizeSummary(item.summary)
    return {
      ...item,
      source_key: config.sourceKey,
      source_label: config.sourceLabel,
      detail_base: config.base,
      detail_path_template: config.detailPathTemplate,
      summary_trade_count: summary.trade_count,
      summary_avg_return_pct: summary.avg_return_pct,
      summary_median_return_pct: summary.median_return_pct,
      summary_win_rate_pct: summary.win_rate_pct,
      created_at_local: formatDateTimeLocal(item.created_at),
      updated_at_local: formatDateTimeLocal(item.updated_at),
    }
  })
}

function sortRunsByTime(items: BacktestRunItem[]): BacktestRunItem[] {
  const parseTime = (raw: unknown) => {
    const text = String(raw || '')
    const t = Date.parse(text)
    return Number.isNaN(t) ? 0 : t
  }
  return [...items].sort((a, b) => {
    const t1 = parseTime(a.updated_at || a.created_at)
    const t2 = parseTime(b.updated_at || b.created_at)
    return t2 - t1
  })
}

async function fetchRunsFromConfig(config: SourceConfig): Promise<{ rows: BacktestRunItem[]; error: string | null }> {
  const params: Record<string, string | number> = { limit: limit.value }
  if (batchKey.value.trim()) {
    params.batch_key = batchKey.value.trim()
  }

  const url = joinUrl(config.base, config.runsPath)
  if (!url) {
    return { rows: [], error: `${config.sourceLabel} 列表路径为空` }
  }

  try {
    const response = await axios.get(url, { params })
    const list = extractRuns(response.data)
    return { rows: normalizeRunRows(list, config), error: null }
  } catch (error: any) {
    const msg = error?.response?.data?.error || error?.message || 'network error'
    return { rows: [], error: `${config.sourceLabel}：${msg}` }
  }
}

function prettyJson(payload: unknown): string {
  try {
    return JSON.stringify(payload, null, 2)
  } catch {
    return String(payload ?? '')
  }
}

async function fetchRuns() {
  loadingList.value = true
  errorMessage.value = ''

  try {
    let merged: BacktestRunItem[] = []
    const errors: string[] = []

    if (sourceType.value === 'all') {
      const [predictiveResp, traditionalResp] = await Promise.all([
        fetchRunsFromConfig(predictivePreset),
        fetchRunsFromConfig(traditionalPreset),
      ])
      merged = [...predictiveResp.rows, ...traditionalResp.rows]
      if (predictiveResp.error) {
        errors.push(predictiveResp.error)
      }
      if (traditionalResp.error) {
        errors.push(traditionalResp.error)
      }
    } else if (sourceType.value === 'predictive') {
      const one = await fetchRunsFromConfig(predictivePreset)
      merged = one.rows
      if (one.error) {
        errors.push(one.error)
      }
    } else if (sourceType.value === 'traditional') {
      const one = await fetchRunsFromConfig(traditionalPreset)
      merged = one.rows
      if (one.error) {
        errors.push(one.error)
      }
    } else {
      const base = normalizedBase()
      if (!base) {
        errorMessage.value = '请先输入服务地址。'
        runs.value = []
        return
      }
      const customConfig: SourceConfig = {
        sourceKey: 'custom',
        sourceLabel: '自定义',
        base,
        runsPath: runsPath.value,
        detailPathTemplate: runDetailPathTemplate.value,
      }
      const one = await fetchRunsFromConfig(customConfig)
      merged = one.rows
      if (one.error) {
        errors.push(one.error)
      }
    }

    runs.value = sortRunsByTime(merged)
    currentPage.value = 1
    if (errors.length) {
      errorMessage.value = errors.join('；')
    }
    if (!detailJson.value && runs.value.length === 0 && !errorMessage.value) {
      detailJson.value = prettyJson({ ok: true, data: [], message: '暂无回测结果' })
      detailObject.value = { ok: true, data: [], message: '暂无回测结果' }
    }
  } catch (error: any) {
    runs.value = []
    errorMessage.value = error?.response?.data?.error || error?.message || '查询列表失败'
  } finally {
    loadingList.value = false
  }
}

async function fetchRunDetail() {
  if (!runId.value) {
    errorMessage.value = '请先输入 run id。'
    return
  }

  loadingDetail.value = true
  errorMessage.value = ''

  try {
    const requestedId = Number(runId.value)
    const errors: string[] = []

    const tryFetch = async (config: SourceConfig) => {
      const detailPath = String(config.detailPathTemplate || '').replace('{id}', String(requestedId))
      const url = joinUrl(config.base, detailPath)
      if (!url) {
        errors.push(`${config.sourceLabel}: 详情地址无效`)
        return false
      }
      try {
        const response = await axios.get(url)
        selectedRunId.value = requestedId
        detailObject.value = response.data
        detailJson.value = prettyJson(response.data)
        return true
      } catch (error: any) {
        const msg = error?.response?.data?.error || error?.message || '查询失败'
        errors.push(`${config.sourceLabel}: ${msg}`)
        return false
      }
    }

    if (sourceType.value === 'all') {
      const okTraditional = await tryFetch(traditionalPreset)
      if (!okTraditional) {
        const okPredictive = await tryFetch(predictivePreset)
        if (!okPredictive) {
          throw new Error(errors.join('；'))
        }
      }
    } else if (sourceType.value === 'predictive') {
      const ok = await tryFetch(predictivePreset)
      if (!ok) {
        throw new Error(errors.join('；'))
      }
    } else if (sourceType.value === 'traditional') {
      const ok = await tryFetch(traditionalPreset)
      if (!ok) {
        throw new Error(errors.join('；'))
      }
    } else {
      const base = normalizedBase()
      const customConfig: SourceConfig = {
        sourceKey: 'custom',
        sourceLabel: '自定义',
        base,
        runsPath: runsPath.value,
        detailPathTemplate: runDetailPathTemplate.value,
      }
      const ok = await tryFetch(customConfig)
      if (!ok) {
        throw new Error(errors.join('；'))
      }
    }
    await fetchRunStocks()
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.error || error?.message || '查询详情失败'
  } finally {
    loadingDetail.value = false
  }
}

async function fetchRunStocks() {
  if (!selectedRunId.value) {
    stockRows.value = []
    return
  }
  if (sourceType.value !== 'traditional' && sourceType.value !== 'all') {
    stockRows.value = []
    return
  }

  loadingStocks.value = true
  try {
    const url = `${traditionalPreset.base}/backtest/traditional/runs/${selectedRunId.value}/stocks/`
    const response = await axios.get(url)
    stockRows.value = Array.isArray(response?.data?.data) ? response.data.data : []
  } catch (error: any) {
    stockRows.value = []
    errorMessage.value = error?.response?.data?.error || error?.message || '查询股票列表失败'
  } finally {
    loadingStocks.value = false
  }
}

async function openDetailForRow(row: BacktestRunItem) {
  const id = Number(row.id)
  if (!Number.isFinite(id)) {
    errorMessage.value = '当前行缺少有效的 run id'
    return
  }

  const base = String(row.detail_base || '').trim()
  const pathTemplate = String(row.detail_path_template || '')
  const detailPath = pathTemplate.replace('{id}', String(id))
  const url = joinUrl(base, detailPath)
  if (!url) {
    errorMessage.value = '详情地址无效'
    return
  }

  loadingDetail.value = true
  errorMessage.value = ''
  try {
    const response = await axios.get(url)
    selectedRunId.value = id
    detailObject.value = response.data
    detailJson.value = prettyJson(response.data)
    await fetchRunStocks()
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.error || error?.message || '查询详情失败'
  } finally {
    loadingDetail.value = false
  }
}

function handleRowDoubleClick(row: BacktestRunItem) {
  runId.value = Number(row.id)
  void openDetailForRow(row)
}

async function fetchStockDetail(tsCode: string) {
  if (!selectedRunId.value || !tsCode) {
    return
  }
  loadingStockDetail.value = true
  stockCode.value = tsCode
  stockName.value = ''
  stockRange.value = {}
  stockDialogTitle.value = `${tsCode} - 加载中...`
  stockTradeRows.value = []
  stockKlineRows.value = []
  stockValuationRows.value = []
  stockStats.value = {}
  stockDialogVisible.value = true
  try {
    const encodedCode = encodeURIComponent(tsCode)
    const url = `${traditionalPreset.base}/backtest/traditional/runs/${selectedRunId.value}/stocks/${encodedCode}/`
    const response = await axios.get(url)
    const data = response?.data || {}
    stockCode.value = String(data.ts_code || tsCode)
    stockName.value = String(data.stock_name || '')
    stockRange.value = (data.range && typeof data.range === 'object') ? data.range : {}
    stockKlineRows.value = Array.isArray(data.kline) ? data.kline : []
    stockTradeRows.value = Array.isArray(data.trades) ? data.trades : []
    stockValuationRows.value = Array.isArray(data.valuation_history) ? data.valuation_history : []
    stockStats.value = data.stats || {}
    stockDialogTitle.value = `${stockCode.value}${stockName.value ? ` ${stockName.value}` : ''} - K线与买卖点`
  } catch (error: any) {
    const msg = error?.response?.data?.error || error?.message || '查询单股详情失败'
    errorMessage.value = msg
    stockStats.value = { mode: 'fallback', warning: msg }
  } finally {
    loadingStockDetail.value = false
  }
}

function handleStockRowDoubleClick(row: StockSummaryRow) {
  void fetchStockDetail(row.ts_code)
}

onMounted(async () => {
  const querySource = String(route.query.source || '').trim().toLowerCase()
  const queryRunIdRaw = String(route.query.run_id || route.query.runId || '').trim()

  if (querySource === 'traditional') {
    sourceType.value = 'traditional'
    applySourcePreset('traditional')
  } else if (querySource === 'predictive') {
    sourceType.value = 'predictive'
    applySourcePreset('predictive')
  }

  await fetchRuns()

  if (queryRunIdRaw) {
    const parsed = Number(queryRunIdRaw)
    if (Number.isFinite(parsed) && parsed > 0) {
      runId.value = parsed
      await fetchRunDetail()
    }
  }
})
</script>

<style scoped>
.backtest-query-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.row-gap {
  margin-bottom: 10px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.hint-text {
  color: #606266;
  font-size: 12px;
}

.muted {
  color: #909399;
  font-size: 12px;
}

.detail-section {
  margin-bottom: 16px;
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}

.pager-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.json-box {
  margin: 0;
  max-height: 420px;
  overflow: auto;
  background: #0f172a;
  color: #e2e8f0;
  padding: 12px;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.45;
}

.kline-chart {
  height: 460px;
}

.trade-table {
  margin-top: 12px;
}

.warning-box {
  margin-top: 10px;
}

@media (max-width: 768px) {
  .actions {
    justify-content: flex-start;
  }
}
</style>
