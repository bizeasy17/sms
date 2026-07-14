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
              <el-option label="预测估值回测" value="predictive" />
              <el-option label="传统估值回测" value="traditional" />
              <el-option label="自定义" value="custom" />
            </el-select>
          </el-col>
          <el-col :xs="24" :md="16">
            <el-input v-model="serviceBase" placeholder="服务地址，例如 http://127.0.0.1:9100/api/forecast" clearable>
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
            <el-button type="primary" :loading="loadingList" @click="fetchRuns">查列表</el-button>
            <el-button :loading="loadingDetail" @click="fetchRunDetail">查详情</el-button>
          </el-col>
        </el-row>

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
            <span>运行列表（双击打开详情）</span>
            <span class="muted">共 {{ runs.length }} 条</span>
          </div>
        </template>

        <el-table :data="runs" stripe border size="small" v-loading="loadingList" height="280" @row-dblclick="handleRunDoubleClick">
          <el-table-column prop="id" label="ID" width="80" />
          <el-table-column prop="batch_key" label="Batch" min-width="180" />
          <el-table-column prop="status" label="Status" width="120" />
          <el-table-column prop="created_at" label="Created" min-width="180" />
          <el-table-column prop="updated_at" label="Updated" min-width="180" />
        </el-table>
      </el-card>

      <el-card shadow="never" class="stock-card">
        <template #header>
          <div class="card-header">
            <span>本次回测股票结果（双击看K线与买卖点）</span>
            <span class="muted" v-if="selectedRunId">run_id={{ selectedRunId }}，共 {{ stockRows.length }} 只</span>
          </div>
        </template>

        <el-table :data="stockRows" stripe border size="small" v-loading="loadingStocks" height="300" @row-dblclick="handleStockDoubleClick">
          <el-table-column prop="ts_code" label="代码" width="120" />
          <el-table-column prop="stock_name" label="名称" width="140" />
          <el-table-column prop="trade_count" label="交易数" width="90" />
          <el-table-column prop="win_rate_pct" label="胜率%" width="90" />
          <el-table-column prop="avg_return_pct" label="平均收益%" width="110" />
          <el-table-column prop="total_return_pct" label="总收益%" width="100" />
          <el-table-column prop="avg_holding_days" label="平均持有天数" width="130" />
          <el-table-column prop="first_entry_date" label="首次买入" min-width="120" />
          <el-table-column prop="last_exit_date" label="最后卖出" min-width="120" />
        </el-table>
      </el-card>

      <el-card shadow="never" class="detail-card">
        <template #header>
          <div class="card-header">
            <span>运行详情 JSON</span>
            <span class="muted" v-if="selectedRunId">run_id={{ selectedRunId }}</span>
          </div>
        </template>

        <pre class="json-box">{{ detailJson }}</pre>
      </el-card>

      <el-dialog v-model="stockDialogVisible" width="92%" top="4vh" :title="stockDialogTitle">
        <el-row :gutter="12">
          <el-col :xs="24" :md="18">
            <v-chart v-if="stockKlineOption" :option="stockKlineOption" autoresize class="kline-chart" />

            <el-table :data="stockTradeRows" stripe border size="small" height="280" class="trade-table">
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
import { useRoute } from 'vue-router'
import axios from 'axios'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElCol,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElInput,
  ElInputNumber,
  ElOption,
  ElRow,
  ElSelect,
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

type BacktestRunItem = {
  id: number
  batch_key?: string
  status?: string
  created_at?: string
  updated_at?: string
  [key: string]: unknown
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

type SourceType = 'predictive' | 'traditional' | 'custom'

const sourceType = ref<SourceType>('predictive')
const serviceBase = ref('http://127.0.0.1:9100/api/forecast')
const runsPath = ref('/backtest/runs/')
const runDetailPathTemplate = ref('/backtest/runs/{id}/')
const batchKey = ref('')
const limit = ref(20)
const runId = ref<number | undefined>(undefined)

const loadingList = ref(false)
const loadingDetail = ref(false)
const loadingStocks = ref(false)
const loadingStockDetail = ref(false)
const errorMessage = ref('')

const runs = ref<BacktestRunItem[]>([])
const selectedRunId = ref<number | null>(null)
const detailObject = ref<Record<string, any> | null>(null)
const detailJson = ref('')
const stockRows = ref<StockSummaryRow[]>([])

const stockDialogVisible = ref(false)
const stockDialogTitle = ref('')
const stockCode = ref('')
const stockName = ref('')
const stockRange = ref<Record<string, any>>({})
const stockKlineRows = ref<Array<Record<string, any>>>([])
const stockMarkers = ref<Array<Record<string, any>>>([])
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

function applySourcePreset(value: SourceType) {
  if (value === 'predictive') {
    serviceBase.value = 'http://127.0.0.1:9100/api/forecast'
    runsPath.value = '/backtest/runs/'
    runDetailPathTemplate.value = '/backtest/runs/{id}/'
    return
  }
  if (value === 'traditional') {
    serviceBase.value = 'http://127.0.0.1:5001/api'
    runsPath.value = '/backtest/traditional/runs/'
    runDetailPathTemplate.value = '/backtest/traditional/runs/{id}/'
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

function prettyJson(payload: unknown): string {
  try {
    return JSON.stringify(payload, null, 2)
  } catch {
    return String(payload ?? '')
  }
}

async function fetchRuns() {
  const base = normalizedBase()
  if (!base) {
    errorMessage.value = '请先输入服务地址。'
    return
  }

  loadingList.value = true
  errorMessage.value = ''

  try {
    const params: Record<string, string | number> = {
      limit: limit.value,
    }
    if (batchKey.value.trim()) {
      params.batch_key = batchKey.value.trim()
    }
    const url = joinUrl(base, runsPath.value)
    if (!url) {
      errorMessage.value = '请先输入列表路径。'
      return
    }
    const response = await axios.get(url, { params })
    runs.value = extractRuns(response.data)
  } catch (error: any) {
    runs.value = []
    errorMessage.value = error?.response?.data?.error || error?.message || '查询列表失败'
  } finally {
    loadingList.value = false
  }
}

async function fetchRunDetail() {
  const base = normalizedBase()
  if (!base) {
    errorMessage.value = '请先输入服务地址。'
    return
  }
  if (!runId.value) {
    errorMessage.value = '请先输入 run id。'
    return
  }

  loadingDetail.value = true
  errorMessage.value = ''

  try {
    const detailPath = String(runDetailPathTemplate.value || '').replace('{id}', String(runId.value))
    const url = joinUrl(base, detailPath)
    if (!url) {
      errorMessage.value = '请先输入详情路径模板。'
      return
    }
    const response = await axios.get(url)
    selectedRunId.value = Number(runId.value)
    detailObject.value = response.data
    detailJson.value = prettyJson(response.data)
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
  if (sourceType.value !== 'traditional') {
    stockRows.value = []
    return
  }

  loadingStocks.value = true
  try {
    const url = `${normalizedBase()}/backtest/traditional/runs/${selectedRunId.value}/stocks/`
    const response = await axios.get(url)
    stockRows.value = Array.isArray(response?.data?.data) ? response.data.data : []
  } catch (error: any) {
    stockRows.value = []
    errorMessage.value = error?.response?.data?.error || error?.message || '查询股票列表失败'
  } finally {
    loadingStocks.value = false
  }
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
  stockMarkers.value = []
  stockTradeRows.value = []
  stockKlineRows.value = []
  stockValuationRows.value = []
  stockStats.value = {}
  stockDialogVisible.value = true
  try {
    const encodedCode = encodeURIComponent(tsCode)
    const url = `${normalizedBase()}/backtest/traditional/runs/${selectedRunId.value}/stocks/${encodedCode}/`
    const response = await axios.get(url)
    const data = response?.data || {}
    stockCode.value = String(data.ts_code || tsCode)
    stockName.value = String(data.stock_name || '')
    stockRange.value = (data.range && typeof data.range === 'object') ? data.range : {}
    stockKlineRows.value = Array.isArray(data.kline) ? data.kline : []
    stockMarkers.value = Array.isArray(data.markers) ? data.markers : []
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

function handleRunDoubleClick(row: BacktestRunItem) {
  runId.value = Number(row.id)
  void fetchRunDetail()
}

function handleStockDoubleClick(row: StockSummaryRow) {
  void fetchStockDetail(row.ts_code)
}

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

function buildSparsePriceSeries(rows: Array<Record<string, any>>, markers: Array<Record<string, any>>, field: string) {
  const valueMap = new Map<string, number>()
  markers.forEach((marker) => {
    const tradeDate = String(marker?.trade_date || '').trim()
    const value = toFiniteNumber(marker?.[field])
    if (tradeDate && value !== null) {
      valueMap.set(tradeDate, value)
    }
  })
  return rows.map((row) => {
    const tradeDate = String(row?.trade_date || '').trim()
    return tradeDate && valueMap.has(tradeDate) ? valueMap.get(tradeDate) ?? null : null
  })
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
  const currentMarker = stockMarkers.value.find((item) => String(item?.trade_date || '') === tradeDate && item?.type === 'buy_candidate')
  const compositePrice = toFiniteNumber(currentMarker?.composite_price)
  const conservativePrice = toFiniteNumber(currentMarker?.conservative_price)
  const compositeText = compositePrice !== null ? compositePrice.toFixed(4) : '-'
  const conservativeText = conservativePrice !== null ? conservativePrice.toFixed(4) : '-'
  return `${tradeDate}<br/>收盘价: ${closeText}<br/>涨跌幅: ${pctChange}<br/>组合估值价: ${compositeText}<br/>保守估值价: ${conservativeText}`
}

const stockKlineOption = computed(() => {
  if (!stockKlineRows.value.length) {
    return null
  }
  const xAxisData = stockKlineRows.value.map((item) => item.trade_date)
  const candleData = stockKlineRows.value.map((item) => [item.open, item.close, item.low, item.high])

  const buyPoints = stockTradeRows.value
    .map((item) => ({
      value: [item.entry_date, item.entry_price],
      tradeDate: item.entry_date,
      price: item.entry_price,
    }))
    .filter((item) => item.tradeDate && item.price !== undefined && item.price !== null)

  const sellPoints = stockTradeRows.value
    .map((item) => ({
      value: [item.exit_date, item.exit_price],
      tradeDate: item.exit_date,
      price: item.exit_price,
    }))
    .filter((item) => item.tradeDate && item.price !== undefined && item.price !== null)

  const buyCandidateCompositeSeries = buildSparsePriceSeries(stockKlineRows.value, stockMarkers.value, 'composite_price')
  const buyCandidateConservativeSeries = buildSparsePriceSeries(stockKlineRows.value, stockMarkers.value, 'conservative_price')

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
    legend: { data: ['K线', ...maPeriods.map((period) => `MA${period}`), '收盘价 90%分位', '收盘价 10%分位', 'SL1', 'SL2', 'TP1', 'TP2', '组合估值价', '保守估值价', '买点', '卖点'] },
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
    yAxis: {
      scale: true,
      splitArea: { show: true },
    },
    dataZoom: [
      { type: 'inside', start: 60, end: 100 },
      { show: true, type: 'slider', top: '90%', start: 60, end: 100 },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: candleData,
      },
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
        name: '组合估值价',
        type: 'line',
        data: buyCandidateCompositeSeries,
        smooth: true,
        showSymbol: true,
        connectNulls: false,
        lineStyle: { color: '#7c3aed', width: 1.5, type: 'dashed' },
        itemStyle: { color: '#7c3aed' },
      },
      {
        name: '保守估值价',
        type: 'line',
        data: buyCandidateConservativeSeries,
        smooth: true,
        showSymbol: true,
        connectNulls: false,
        lineStyle: { color: '#ea580c', width: 1.5, type: 'dashed' },
        itemStyle: { color: '#ea580c' },
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

.muted {
  color: #909399;
  font-size: 12px;
}

.json-box {
  margin: 0;
  max-height: 260px;
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
