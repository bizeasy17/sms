<template>
  <DefaultLayout>
    <div class="sw-industry-page">
      <el-row :gutter="12">
        <el-col :xs="24" :md="5">
          <el-card class="sw-panel" shadow="always">
            <template #header>
              <div class="sw-panel-header sw-industry-header">
                <el-select v-model="selectedIndustryType" size="small" class="sw-industry-type-select">
                  <el-option
                    v-for="item in industryTypeOptions"
                    :key="item.value"
                    :label="item.label"
                    :value="item.value"
                  />
                </el-select>
                <el-select
                  v-if="selectedIndustryType === 'ths'"
                  v-model="selectedThsIndexType"
                  size="small"
                  class="sw-ths-index-type-select"
                >
                  <el-option
                    v-for="item in thsIndexTypeOptions"
                    :key="item.value"
                    :label="item.label"
                    :value="item.value"
                  />
                </el-select>
                <el-input
                  v-model="industryKeyword"
                  size="small"
                  placeholder="搜索行业"
                  clearable
                />
              </div>
            </template>
            <el-tabs v-model="industryTab" class="sw-industry-tabs">
              <el-tab-pane label="全部行业" name="all" />
              <el-tab-pane label="行业轮动" name="rotation" />
              <el-tab-pane :label="`收藏行业 (${favoriteIndustryList.length})`" name="favorites" />
            </el-tabs>
            <div v-if="industryTab === 'rotation'" class="sw-rotation-panel" v-loading="rotationLoading">
              <div class="sw-rotation-toolbar">
                <el-input-number
                  v-model="rotationTopN"
                  size="small"
                  :min="1"
                  :max="50"
                  :step="1"
                  controls-position="right"
                />
                <el-button size="small" @click="refreshRotationList">刷新</el-button>
              </div>
              <div class="sw-rotation-meta" v-if="rotationMeta.generated_at">
                <span>快照 {{ rotationMeta.asof_date || '-' }}</span>
                <span>生成 {{ rotationMeta.generated_at || '-' }}</span>
                <span>版本 {{ rotationMeta.scoring_version || '-' }}</span>
                <span>run {{ rotationMeta.run_id || '-' }}</span>
              </div>
              <el-scrollbar class="sw-rotation-scroll">
                <div
                  v-for="(item, idx) in rotationRows"
                  :key="`${item.industry_code}-${idx}`"
                  class="sw-rotation-item"
                  :class="{
                    active: selectedIndustryType === 'sw' && selectedIndustryKey === item.industry_code,
                  }"
                  @click="selectRotationIndustry(item)"
                >
                  <div class="sw-rotation-head">
                    <span class="sw-rotation-rank">#{{ idx + 1 }}</span>
                    <span class="sw-rotation-name">{{ item.industry_name || item.industry_code }}</span>
                  </div>
                  <div class="sw-rotation-sub">{{ item.industry_code }} | {{ item.regime || '-' }}</div>
                  <div class="sw-rotation-score">综合分 {{ formatMetric(item.rotation_score) }}</div>
                  <div class="sw-rotation-breakdown">
                    <span>估值 {{ formatMetric(item.score_breakdown?.valuation) }}</span>
                    <span>动量 {{ formatMetric(item.score_breakdown?.momentum) }}</span>
                    <span>风险 {{ formatMetric(item.score_breakdown?.risk) }}</span>
                    <span>风格 {{ formatMetric(item.score_breakdown?.style) }}</span>
                  </div>
                </div>
                <el-empty v-if="!rotationRows.length" description="暂无轮动候选" />
              </el-scrollbar>
              <div class="sw-rotation-actions-bottom">
                <el-button size="small" type="primary" plain @click="recomputeRotationList">立即重算</el-button>
                <el-button size="small" type="success" plain @click="openRotationRunDialog">查看topN表现</el-button>
              </div>
            </div>

            <el-scrollbar v-else class="sw-industry-list-scroll">
              <div
                v-for="item in displayedIndustryList"
                :key="`${item.industry_type}:${item.industry_key}`"
                class="sw-industry-item"
                :class="{
                  active: item.industry_type === selectedIndustryType && item.industry_key === selectedIndustryKey,
                  favorite: isIndustryFavorite(item),
                }"
                @click="selectIndustry(item)"
              >
                <div class="sw-industry-name">{{ item.display_name }}</div>
                <div class="sw-industry-meta">
                  <span>{{ item.industry_key }}</span>
                  <span>{{ item.member_count }}只</span>
                </div>
                <div v-if="item.extra_label" class="sw-industry-extra">{{ item.extra_label }}</div>
              </div>
              <el-empty
                v-if="!displayedIndustryList.length"
                :description="industryTab === 'favorites' ? '暂无收藏行业' : '暂无行业数据'"
              />
            </el-scrollbar>
          </el-card>
        </el-col>

        <el-col :xs="24" :md="13">
          <el-card class="sw-panel" shadow="always">
            <template #header>
              <div class="sw-panel-header sw-history-header">
                <div class="sw-history-title-row">
                  <span>{{ selectedIndustryName || '行业分位走势' }}</span>
                  <el-button
                    v-if="selectedIndustryKey"
                    size="small"
                    text
                    :type="isSelectedIndustryFavorite ? 'warning' : 'primary'"
                    @click="toggleIndustryFavorite()"
                  >
                    {{ isSelectedIndustryFavorite ? '取消收藏' : '收藏行业' }}
                  </el-button>
                </div>
                <div class="sw-toolbar">
                  <el-radio-group v-model="metric" size="small">
                    <el-radio-button label="close">Close</el-radio-button>
                    <el-radio-button label="pe">PE</el-radio-button>
                    <el-radio-button label="pb">PB</el-radio-button>
                  </el-radio-group>
                  <el-radio-group v-model="period" size="small">
                    <el-radio-button v-for="item in periodOptions" :key="item" :label="item">
                      {{ item }}
                    </el-radio-button>
                  </el-radio-group>
                </div>
              </div>
            </template>

            <div class="sw-summary" v-if="historyRows.length">
              <span>最新 {{ metric.toUpperCase() }} {{ formatMetric(historyMeta.latest_value) }}</span>
              <span>日期 {{ historyMeta.latest_trade_date || '-' }}</span>
              <span>90分位 {{ formatMetric(historyMeta.q90) }}</span>
              <span>50分位 {{ formatMetric(historyMeta.q50) }}</span>
              <span>10分位 {{ formatMetric(historyMeta.q10) }}</span>
            </div>

            <v-chart v-if="historyChartOption" :option="historyChartOption" autoresize class="sw-history-chart" />
            <el-empty v-else description="暂无行业历史数据" />
          </el-card>
        </el-col>

        <el-col :xs="24" :md="6">
          <el-card class="sw-panel" shadow="always" v-loading="constituentsLoading">
            <template #header>
              <div class="sw-panel-header sw-members-header">
                <span>成分股</span>
                <div class="sw-members-toolbar">
                  <el-select v-model="constituentMarket" size="small" style="width: 110px;">
                    <el-option label="全部" value="ALL" />
                    <el-option label="沪市" value="SH" />
                    <el-option label="深市" value="SZ" />
                    <el-option label="创业" value="CYB" />
                    <el-option label="科创" value="STAR" />
                  </el-select>
                  <el-input
                    v-model="constituentKeyword"
                    size="small"
                    placeholder="代码/名称"
                    clearable
                    @keyup.enter="reloadConstituents"
                  >
                    <template #append>
                      <el-button @click="reloadConstituents">查</el-button>
                    </template>
                  </el-input>
                </div>
              </div>
            </template>

            <el-table :data="constituents" size="small" stripe height="560" class="sw-members-table">
              <el-table-column label="股票" min-width="150">
                <template #default="scope">
                  <el-link type="primary" :underline="false" @click.stop="openStockDialog(scope.row)">
                    {{ scope.row.name }} | {{ scope.row.ts_code }}
                  </el-link>
                  <div class="sw-member-tags">
                    <el-tag size="small" effect="plain" :type="scope.row.in_watchlist ? 'danger' : 'info'">自</el-tag>
                    <el-tag size="small" effect="plain" :type="scope.row.hold_position ? 'primary' : 'info'">持</el-tag>
                    <el-tag size="small" effect="plain" :type="scope.row.observe_only ? 'warning' : 'info'">观</el-tag>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="162">
                <template #default="scope">
                  <div class="sw-member-actions">
                    <el-button size="small" text @click.stop="toggleWatch(scope.row)">
                      {{ scope.row.in_watchlist ? '移自' : '加自' }}
                    </el-button>
                    <el-button size="small" text @click.stop="toggleHold(scope.row)">
                      {{ scope.row.hold_position ? '撤持' : '持仓' }}
                    </el-button>
                    <el-button size="small" text @click.stop="toggleObserve(scope.row)">
                      {{ scope.row.observe_only ? '撤观' : '观察' }}
                    </el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>

            <div class="sw-pagination">
              <el-pagination
                small
                background
                layout="prev, pager, next"
                :current-page="currentPage"
                :page-size="pageSize"
                :pager-count="5"
                :total="constituentTotal"
                @current-change="handleConstituentPageChange"
              />
            </div>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <el-dialog v-model="stockDialogVisible" width="92%" top="4vh" :title="stockDialogTitle">
      <template #header>
        <div class="sw-stock-dialog-header">
          <span class="sw-stock-dialog-title">{{ stockDialogTitle }}</span>
          <div v-if="constituents.length > 1" class="sw-stock-dialog-nav">
            <el-button size="small" text :disabled="selectedConstituentIndex <= 0" @click="navigatePrevStock">
              前一只
            </el-button>
            <el-button size="small" text :disabled="selectedConstituentIndex < 0 || selectedConstituentIndex >= constituents.length - 1" @click="navigateNextStock">
              后一只
            </el-button>
          </div>
        </div>
      </template>
      <StockChartFilter :show-recent-report-panel="false" @toggle-recent-report-panel="noopToggleRecent" />
    </el-dialog>

    <el-dialog v-model="rotationRunDialogVisible" width="88%" top="6vh" title="TopN表现（按run）">
      <div class="sw-rotation-run-layout" v-loading="rotationRunLoading">
        <div class="sw-rotation-run-list">
          <div class="sw-rotation-run-list-title">最近run</div>
          <el-scrollbar class="sw-rotation-run-scroll">
            <div
              v-for="item in rotationRunList"
              :key="item.run_id"
              class="sw-rotation-run-item"
              :class="{ active: selectedRotationRunId === item.run_id }"
            >
              <div class="sw-rotation-run-row" @click="selectRotationRun(item.run_id)">
                <div class="sw-rotation-run-id">{{ item.run_id }}</div>
                <div class="sw-rotation-run-meta">{{ item.asof_date || '-' }} | {{ item.created_at || '-' }}</div>
              </div>
              <el-button size="small" text type="danger" @click.stop="deleteRotationRun(item.run_id)">删除</el-button>
            </div>
            <el-empty v-if="!rotationRunList.length" description="暂无run" />
          </el-scrollbar>
        </div>
        <div class="sw-rotation-run-chart-wrap">
          <div class="sw-rotation-run-headline" v-if="selectedRotationRunId">
            <span>当前run: {{ selectedRotationRunId }}</span>
            <span>窗口: {{ rotationRunWindows.join('/') }}</span>
          </div>
          <v-chart
            v-if="rotationRunChartOption"
            :option="rotationRunChartOption"
            autoresize
            class="sw-rotation-run-chart"
          />
          <el-empty v-else description="暂无可展示的run表现数据" />
        </div>
      </div>
    </el-dialog>
  </DefaultLayout>
</template>

<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from 'vue'
import axios from 'axios'
import { ElButton, ElCard, ElCol, ElDialog, ElEmpty, ElInput, ElInputNumber, ElLink, ElMessage, ElMessageBox, ElOption, ElPagination, ElRadioButton, ElRadioGroup, ElRow, ElScrollbar, ElSelect, ElTable, ElTableColumn, ElTabPane, ElTabs, ElTag } from 'element-plus'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart } from 'echarts/charts'
import { TooltipComponent, GridComponent, DataZoomComponent, LegendComponent, MarkLineComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import DefaultLayout from '../layouts/DefaultLayout.vue'
import StockChartFilter from '../components/StockChartFilter.vue'
import { useStockTradeStore } from '../stores/stockTradeStore'

use([CanvasRenderer, LineChart, BarChart, TooltipComponent, GridComponent, DataZoomComponent, LegendComponent, MarkLineComponent])

type IndustryType = 'sw' | 'ths' | 'valuation_variant' | 'corp_industry'

type IndustryItem = {
  industry_type: IndustryType
  industry_key: string
  display_name: string
  member_count: number
  index_type?: string
  index_type_label?: string
  extra_label?: string
}

type ThsIndexTypeFilter = 'ALL' | 'N' | 'I' | 'R' | 'S' | 'ST' | 'TH' | 'BB'

type IndustryHistoryRow = {
  trade_date: string
  value: number | null
}

type SwConstituentRow = {
  ts_code: string
  name: string
  basic_info?: {
    website?: string
    main_business?: string
  }
  in_watchlist: boolean
  hold_position: boolean
  observe_only: boolean
}

const baseURL = inject<string>('baseURL', '')
const stockTradeStore = useStockTradeStore()
const FAVORITE_INDUSTRY_KEYS_KEY = 'industry_universe_favorite_keys_v1'
const LEGACY_FAVORITE_SW_KEY = 'sw_industry_favorite_codes'

const industryTypeOptions: Array<{ value: IndustryType; label: string }> = [
  { value: 'sw', label: 'SW行业' },
  { value: 'ths', label: 'THS行业' },
  { value: 'valuation_variant', label: '行业变体' },
  { value: 'corp_industry', label: '基本信息行业' },
]

const thsIndexTypeOptions: Array<{ value: ThsIndexTypeFilter; label: string }> = [
  { value: 'ALL', label: '全部类型' },
  { value: 'N', label: 'N 概念指数' },
  { value: 'I', label: 'I 行业指数' },
  { value: 'R', label: 'R 地域指数' },
  { value: 'S', label: 'S 特色指数' },
  { value: 'ST', label: 'ST 风格指数' },
  { value: 'TH', label: 'TH 主题指数' },
  { value: 'BB', label: 'BB 宽基指数' },
]

const selectedIndustryType = ref<IndustryType>('sw')
const selectedThsIndexType = ref<ThsIndexTypeFilter>('ALL')
const industryList = ref<IndustryItem[]>([])
const industryKeyword = ref('')
const industryTab = ref<'all' | 'rotation' | 'favorites'>('all')
const favoriteIndustryKeys = ref<string[]>([])
const selectedIndustryKey = ref('')
const selectedIndustryName = ref('')

const rotationLoading = ref(false)
const rotationTopN = ref(10)
const rotationRows = ref<Array<{
  industry_code: string
  industry_name: string
  regime: string
  rotation_score: number | null
  score_breakdown?: {
    valuation?: number | null
    momentum?: number | null
    risk?: number | null
    style?: number | null
  }
}>>([])
const rotationMeta = ref<{
  asof_date?: string
  generated_at?: string
  scoring_version?: string
  run_id?: string
}>({})

type RotationRunSummary = {
  run_id: string
  created_at: string
  asof_date: string
}

const rotationRunDialogVisible = ref(false)
const rotationRunLoading = ref(false)
const rotationRunList = ref<RotationRunSummary[]>([])
const selectedRotationRunId = ref('')
const rotationRunWindows = ref<number[]>([])
const rotationRunPerformance = ref<{
  topn_summary: Record<string, number | null>
  benchmark_summary: Record<string, number | null>
  alpha_summary: Record<string, number | null>
  hit_ratio_summary: Record<string, number | null>
}>({
  topn_summary: {},
  benchmark_summary: {},
  alpha_summary: {},
  hit_ratio_summary: {},
})
const rotationRunDailySeries = ref<Array<{
  day_offset: number
  trade_date: string
  topn_return: number | null
  benchmark_return: number | null
  alpha_return: number | null
  hit_ratio: number | null
}>>([])

const metric = ref<'close' | 'pe' | 'pb'>('pe')
const period = ref<'30D' | '60D' | '90D' | '1Y' | '3Y' | '5Y' | '10Y' | 'ALL'>('5Y')
const periodOptions: Array<'30D' | '60D' | '90D' | '1Y' | '3Y' | '5Y' | '10Y' | 'ALL'> = ['30D', '60D', '90D', '1Y', '3Y', '5Y', '10Y', 'ALL']

const historyRows = ref<IndustryHistoryRow[]>([])
const historyMeta = ref<{
  q10: number | null
  q50: number | null
  q90: number | null
  latest_value: number | null
  latest_trade_date: string
}>({
  q10: null,
  q50: null,
  q90: null,
  latest_value: null,
  latest_trade_date: '',
})

const INDUSTRY_HISTORY_CACHE_TTL_MS = 5 * 60 * 1000
const industryHistoryMemoryCache = new Map<
  string,
  {
    data: IndustryHistoryRow[]
    meta: {
      q10: number | null
      q50: number | null
      q90: number | null
      latest_value: number | null
      latest_trade_date: string
    }
    cachedAt: number
  }
>()
let industryHistoryAbortController: AbortController | null = null
let industryHistoryRequestToken = 0

const constituents = ref<SwConstituentRow[]>([])
const constituentsLoading = ref(false)
const constituentKeyword = ref('')
const constituentMarket = ref<'ALL' | 'SH' | 'SZ' | 'CYB' | 'STAR'>('ALL')
const constituentTotal = ref(0)
const currentPage = ref(1)
const pageSize = ref(30)

const stockDialogVisible = ref(false)
const stockDialogTitle = ref('股票详情')
const selectedConstituentIndex = ref(-1)

function buildFavoriteKey(industryType: IndustryType, industryKey: string) {
  return `${industryType}|${String(industryKey || '').trim()}`
}

function normalizeFavoriteIndustryKeys(rawList: any[]): string[] {
  if (!Array.isArray(rawList)) return []
  const result = new Set<string>()
  for (const rawItem of rawList) {
    const text = String(rawItem || '').trim()
    if (!text) continue

    if (text.includes('|')) {
      const [rawType, ...rest] = text.split('|')
      const typeText = String(rawType || '').trim().toLowerCase()
      const keyText = String(rest.join('|') || '').trim()
      if (!keyText) continue
      const type: IndustryType = typeText === 'valuation_variant'
        ? 'valuation_variant'
        : typeText === 'ths'
          ? 'ths'
        : typeText === 'corp_industry'
          ? 'corp_industry'
          : 'sw'
      result.add(buildFavoriteKey(type, keyText))
      continue
    }

    // Legacy storage may keep only SW industry codes, migrate to typed keys.
    result.add(buildFavoriteKey('sw', text))
  }
  return Array.from(result)
}

function getFavoriteKeyCandidates(industryType: IndustryType, industryKey: string) {
  const normalizedType = String(industryType || '').trim() as IndustryType
  const rawKey = String(industryKey || '').trim()
  if (!rawKey) return []

  const candidates = new Set<string>([buildFavoriteKey(normalizedType, rawKey)])
  if (normalizedType === 'sw') {
    const upper = rawKey.toUpperCase()
    const base = upper.includes('.') ? upper.split('.', 1)[0] : upper
    if (base) {
      candidates.add(buildFavoriteKey('sw', base))
      candidates.add(buildFavoriteKey('sw', `${base}.SI`))
    }
  }
  return Array.from(candidates)
}

function isIndustryFavorite(item: IndustryItem) {
  const favoriteSet = new Set(favoriteIndustryKeys.value)
  return getFavoriteKeyCandidates(item.industry_type, item.industry_key).some((key) => favoriteSet.has(key))
}

const filteredIndustryList = computed(() => {
  const key = industryKeyword.value.trim().toLowerCase()
  if (!key) return industryList.value
  return industryList.value.filter((item) => (
    String(item.display_name || '').toLowerCase().includes(key)
    || String(item.industry_key || '').toLowerCase().includes(key)
  ))
})

const favoriteIndustryList = computed(() => {
  if (!favoriteIndustryKeys.value.length) return []
  const favoriteSet = new Set(favoriteIndustryKeys.value)
  return industryList.value.filter((item) => (
    getFavoriteKeyCandidates(item.industry_type, item.industry_key).some((key) => favoriteSet.has(key))
  ))
})

const displayedIndustryList = computed(() => {
  const sourceList = industryTab.value === 'favorites' ? favoriteIndustryList.value : filteredIndustryList.value
  if (industryTab.value === 'favorites') {
    const key = industryKeyword.value.trim().toLowerCase()
    if (!key) return sourceList
    return sourceList.filter((item) => (
      String(item.display_name || '').toLowerCase().includes(key)
      || String(item.industry_key || '').toLowerCase().includes(key)
    ))
  }
  return sourceList
})

const isSelectedIndustryFavorite = computed(() => {
  if (!selectedIndustryKey.value) return false
  const favoriteSet = new Set(favoriteIndustryKeys.value)
  return getFavoriteKeyCandidates(selectedIndustryType.value, selectedIndustryKey.value).some((key) => favoriteSet.has(key))
})

const historyChartOption = computed(() => {
  if (!historyRows.value.length) {
    return null
  }
  const xAxis = historyRows.value.map((item) => item.trade_date)

  const markData: Array<{ name: string; yAxis: number }> = []
  if (typeof historyMeta.value.q90 === 'number') markData.push({ name: '90分位', yAxis: historyMeta.value.q90 })
  if (typeof historyMeta.value.q50 === 'number') markData.push({ name: '50分位', yAxis: historyMeta.value.q50 })
  if (typeof historyMeta.value.q10 === 'number') markData.push({ name: '10分位', yAxis: historyMeta.value.q10 })

  const yData = historyRows.value.map((item) => item.value)
  const metricLabel = metric.value.toUpperCase()

  return {
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: number) => Number(value).toFixed(2),
    },
    legend: {
      data: [metricLabel],
    },
    grid: {
      top: 30,
      left: 56,
      right: 18,
      bottom: 64,
    },
    xAxis: {
      type: 'category',
      data: xAxis,
      axisLabel: { hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      scale: true,
    },
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      { type: 'slider', height: 16, bottom: 20, start: 0, end: 100 },
    ],
    series: [
      {
        name: metricLabel,
        type: 'line',
        smooth: false,
        symbol: 'none',
        lineStyle: {
          width: 2,
          color: '#2563eb',
        },
        areaStyle: {
          color: 'rgba(37, 99, 235, 0.12)',
        },
        data: yData,
        markLine: markData.length ? {
          symbol: ['none', 'none'],
          data: markData,
          lineStyle: {
            type: 'dashed',
            width: 1,
            color: '#94a3b8',
          },
          label: {
            color: '#475569',
            fontSize: 11,
          },
        } : undefined,
      },
    ],
  }
})

function formatMetric(value: number | null | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-'
  return value.toFixed(2)
}

function buildIndustryHistoryCacheKey() {
  if (!selectedIndustryKey.value) return ''
  return [
    selectedIndustryType.value,
    selectedIndustryKey.value,
    metric.value,
    period.value,
  ].join('|')
}

function applyIndustryHistoryPayload(payload: any) {
  historyRows.value = (Array.isArray(payload?.data) ? payload.data : [])
    .map((row: any) => ({
      trade_date: String(row?.trade_date || ''),
      value: Number.isFinite(Number(row?.value)) ? Number(row?.value) : null,
    }))
    .filter((row: IndustryHistoryRow) => Boolean(row.trade_date))

  const meta = payload?.meta || {}
  historyMeta.value = {
    q10: Number.isFinite(Number(meta.q10)) ? Number(meta.q10) : null,
    q50: Number.isFinite(Number(meta.q50)) ? Number(meta.q50) : null,
    q90: Number.isFinite(Number(meta.q90)) ? Number(meta.q90) : null,
    latest_value: Number.isFinite(Number(meta.latest_value)) ? Number(meta.latest_value) : null,
    latest_trade_date: String(meta.latest_trade_date || ''),
  }
}

function formatPercent(value: number | null | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-'
  return `${(value * 100).toFixed(2)}%`
}

const rotationRunChartOption = computed(() => {
  if (!rotationRunDailySeries.value.length) {
    return null
  }
  const categories = rotationRunDailySeries.value.map((item) => item.trade_date || `${item.day_offset}D`)
  const topn = rotationRunDailySeries.value.map((item) => item.topn_return)
  const benchmark = rotationRunDailySeries.value.map((item) => item.benchmark_return)
  const alpha = rotationRunDailySeries.value.map((item) => item.alpha_return)
  const hitRatio = rotationRunDailySeries.value.map((item) => item.hit_ratio)

  return {
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: number) => formatPercent(Number(value)),
    },
    legend: {
      data: ['TopN收益', '基准收益', '超额收益', '命中率'],
    },
    grid: {
      top: 34,
      left: 56,
      right: 56,
      bottom: 42,
    },
    xAxis: {
      type: 'category',
      data: categories,
    },
    yAxis: [
      {
        type: 'value',
        name: '收益率',
        axisLabel: {
          formatter: (value: number) => `${(Number(value) * 100).toFixed(0)}%`,
        },
      },
      {
        type: 'value',
        name: '命中率',
        min: 0,
        max: 1,
        axisLabel: {
          formatter: (value: number) => `${(Number(value) * 100).toFixed(0)}%`,
        },
      },
    ],
    series: [
      {
        name: 'TopN收益',
        type: 'bar',
        data: topn,
        itemStyle: { color: '#2563eb' },
      },
      {
        name: '基准收益',
        type: 'bar',
        data: benchmark,
        itemStyle: { color: '#64748b' },
      },
      {
        name: '超额收益',
        type: 'bar',
        data: alpha,
        itemStyle: { color: '#f59e0b' },
      },
      {
        name: '命中率',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        data: hitRatio,
        lineStyle: { width: 2, color: '#16a34a' },
        itemStyle: { color: '#16a34a' },
      },
    ],
  }
})

function noopToggleRecent() {
  // 对齐 StockChartFilter 的事件签名，弹窗中不需要额外动作。
}

function loadFavoriteIndustryKeys() {
  if (typeof window === 'undefined') return
  try {
    const raw = window.localStorage.getItem(FAVORITE_INDUSTRY_KEYS_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    if (Array.isArray(parsed)) {
      favoriteIndustryKeys.value = normalizeFavoriteIndustryKeys(parsed)
      persistFavoriteIndustryKeys()
      return
    }
  } catch {
    // fallback to legacy key
  }

  try {
    const legacyRaw = window.localStorage.getItem(LEGACY_FAVORITE_SW_KEY)
    const legacyParsed = legacyRaw ? JSON.parse(legacyRaw) : []
    favoriteIndustryKeys.value = normalizeFavoriteIndustryKeys(
      Array.isArray(legacyParsed)
        ? legacyParsed.map((item) => buildFavoriteKey('sw', String(item || '').trim()))
        : []
    )
    persistFavoriteIndustryKeys()
  } catch {
    favoriteIndustryKeys.value = []
  }
}

function persistFavoriteIndustryKeys() {
  if (typeof window === 'undefined') return
  try {
    if (!favoriteIndustryKeys.value.length) {
      window.localStorage.removeItem(FAVORITE_INDUSTRY_KEYS_KEY)
      return
    }
    window.localStorage.setItem(FAVORITE_INDUSTRY_KEYS_KEY, JSON.stringify(favoriteIndustryKeys.value))
  } catch {
    // ignore localStorage failures
  }
}

function toggleIndustryFavorite() {
  const normalizedKey = String(selectedIndustryKey.value || '').trim()
  if (!normalizedKey) return
  const candidates = getFavoriteKeyCandidates(selectedIndustryType.value, normalizedKey)
  const canonical = buildFavoriteKey(selectedIndustryType.value, normalizedKey)
  const hasFavorite = candidates.some((key) => favoriteIndustryKeys.value.includes(key))
  if (hasFavorite) {
    favoriteIndustryKeys.value = favoriteIndustryKeys.value.filter((item) => !candidates.includes(item))
  } else {
    favoriteIndustryKeys.value = [...favoriteIndustryKeys.value.filter((item) => !candidates.includes(item)), canonical]
  }
  persistFavoriteIndustryKeys()
}

function syncDialogStock(row: SwConstituentRow) {
  const tsCode = String(row.ts_code || '').trim().toUpperCase()
  if (!tsCode) return
  stockTradeStore.setTsCode(tsCode)
  stockTradeStore.setName(String(row.name || ''))
  stockTradeStore.setWebsite(String(row.basic_info?.website || ''))
  stockDialogTitle.value = `${row.name || ''} | ${tsCode}`
}

async function fetchIndustryList() {
  if (!baseURL) return
  const params: Record<string, string> = {
    industry_type: selectedIndustryType.value,
    keyword: industryKeyword.value.trim(),
  }
  if (selectedIndustryType.value === 'ths' && selectedThsIndexType.value !== 'ALL') {
    params.ths_index_type = selectedThsIndexType.value
  }
  const resp = await axios.get(`${baseURL}/industry-universe/list/`, {
    params,
  })
  const rows = Array.isArray(resp?.data?.data) ? resp.data.data : []
  industryList.value = rows
    .map((row: any) => ({
      industry_type: String(row?.industry_type || selectedIndustryType.value) as IndustryType,
      industry_key: String(row?.industry_key || ''),
      display_name: String(row?.display_name || ''),
      member_count: Number(row?.member_count || 0),
      index_type: String(row?.index_type || ''),
      index_type_label: String(row?.index_type_label || ''),
      extra_label: String(row?.extra_label || ''),
    }))
    .filter((row: IndustryItem) => Boolean(row.industry_key) && Boolean(row.display_name))

  const existing = industryList.value.find((item) => (
    item.industry_type === selectedIndustryType.value && item.industry_key === selectedIndustryKey.value
  ))

  if (existing) {
    selectIndustry(existing)
    return
  }

  if (industryList.value.length) {
    selectIndustry(industryList.value[0])
  } else {
    selectedIndustryKey.value = ''
    selectedIndustryName.value = ''
    historyRows.value = []
    constituents.value = []
    constituentTotal.value = 0
  }
}

async function fetchIndustryHistory() {
  if (!baseURL || !selectedIndustryKey.value) {
    historyRows.value = []
    return
  }
  const cacheKey = buildIndustryHistoryCacheKey()
  const now = Date.now()
  if (cacheKey) {
    const cached = industryHistoryMemoryCache.get(cacheKey)
    if (cached && now - cached.cachedAt <= INDUSTRY_HISTORY_CACHE_TTL_MS) {
      applyIndustryHistoryPayload({ data: cached.data, meta: cached.meta })
    }
  }

  industryHistoryRequestToken += 1
  const requestToken = industryHistoryRequestToken
  if (industryHistoryAbortController) {
    industryHistoryAbortController.abort()
  }
  industryHistoryAbortController = new AbortController()

  try {
    const resp = await axios.get(`${baseURL}/industry-universe/history/`, {
      params: {
        industry_type: selectedIndustryType.value,
        industry_key: selectedIndustryKey.value,
        metric: metric.value,
        period: period.value,
      },
      signal: industryHistoryAbortController.signal,
    })

    if (requestToken !== industryHistoryRequestToken) {
      return
    }

    applyIndustryHistoryPayload(resp?.data || {})

    if (cacheKey) {
      industryHistoryMemoryCache.set(cacheKey, {
        data: [...historyRows.value],
        meta: { ...historyMeta.value },
        cachedAt: Date.now(),
      })
    }
  } catch (error: any) {
    if (axios.isCancel?.(error) || error?.code === 'ERR_CANCELED') {
      return
    }
    throw error
  }
}

async function fetchConstituents() {
  if (!baseURL || !selectedIndustryKey.value) {
    constituents.value = []
    constituentTotal.value = 0
    return
  }
  constituentsLoading.value = true
  try {
    const fromIndex = (currentPage.value - 1) * pageSize.value
    const toIndex = fromIndex + pageSize.value
    const resp = await axios.get(`${baseURL}/industry-universe/constituents/`, {
      params: {
        industry_type: selectedIndustryType.value,
        industry_key: selectedIndustryKey.value,
        from_index: fromIndex,
        to_index: toIndex,
        market: constituentMarket.value,
        keyword: constituentKeyword.value.trim(),
      },
    })
    constituents.value = (Array.isArray(resp?.data?.data) ? resp.data.data : []).map((row: any) => ({
      ts_code: String(row?.ts_code || ''),
      name: String(row?.name || ''),
      basic_info: {
        website: String(row?.basic_info?.website || ''),
        main_business: String(row?.basic_info?.main_business || ''),
      },
      in_watchlist: Boolean(row?.in_watchlist),
      hold_position: Boolean(row?.hold_position),
      observe_only: Boolean(row?.observe_only),
    }))
    constituentTotal.value = Number(resp?.data?.meta?.total || 0)
  } finally {
    constituentsLoading.value = false
  }
}

async function fetchRotationList(useRecompute = false) {
  if (!baseURL) return
  rotationLoading.value = true
  try {
    const topN = Math.max(1, Math.min(50, Number(rotationTopN.value || 10)))
    const thsIndexType = selectedIndustryType.value === 'ths' ? selectedThsIndexType.value : 'ALL'
    if (useRecompute) {
      const recomputeResp = await axios.post(`${baseURL}/industry-universe/rotation/recompute/`, {
        market: 'CN',
        industry_type: selectedIndustryType.value,
        ths_index_type: thsIndexType,
        top_n: topN,
      })
      const recomputeRows = Array.isArray(recomputeResp?.data?.data) ? recomputeResp.data.data : []
      rotationRows.value = recomputeRows.map((row: any) => ({
        industry_code: String(row?.industry_code || ''),
        industry_name: String(row?.industry_name || ''),
        regime: String(row?.regime || ''),
        rotation_score: Number.isFinite(Number(row?.rotation_score)) ? Number(row.rotation_score) : null,
        score_breakdown: {
          valuation: Number.isFinite(Number(row?.score_breakdown?.valuation)) ? Number(row.score_breakdown.valuation) : null,
          momentum: Number.isFinite(Number(row?.score_breakdown?.momentum)) ? Number(row.score_breakdown.momentum) : null,
          risk: Number.isFinite(Number(row?.score_breakdown?.risk)) ? Number(row.score_breakdown.risk) : null,
          style: Number.isFinite(Number(row?.score_breakdown?.style)) ? Number(row.score_breakdown.style) : null,
        },
      }))
      rotationMeta.value = {
        asof_date: String(recomputeResp?.data?.meta?.asof_date || ''),
        generated_at: String(recomputeResp?.data?.meta?.generated_at || ''),
        scoring_version: String(recomputeResp?.data?.meta?.scoring_version || ''),
        run_id: String(recomputeResp?.data?.meta?.run_id || ''),
      }
      return
    }

    const resp = await axios.get(`${baseURL}/industry-universe/rotation/latest/`, {
      params: {
        market: 'CN',
        industry_type: selectedIndustryType.value,
        ths_index_type: thsIndexType,
        top_n: topN,
      },
    })
    const rows = Array.isArray(resp?.data?.data) ? resp.data.data : []
    rotationRows.value = rows.map((row: any) => ({
      industry_code: String(row?.industry_code || ''),
      industry_name: String(row?.industry_name || ''),
      regime: String(row?.regime || ''),
      rotation_score: Number.isFinite(Number(row?.rotation_score)) ? Number(row.rotation_score) : null,
      score_breakdown: {
        valuation: Number.isFinite(Number(row?.score_breakdown?.valuation)) ? Number(row.score_breakdown.valuation) : null,
        momentum: Number.isFinite(Number(row?.score_breakdown?.momentum)) ? Number(row.score_breakdown.momentum) : null,
        risk: Number.isFinite(Number(row?.score_breakdown?.risk)) ? Number(row.score_breakdown.risk) : null,
        style: Number.isFinite(Number(row?.score_breakdown?.style)) ? Number(row.score_breakdown.style) : null,
      },
    }))
    rotationMeta.value = {
      asof_date: String(resp?.data?.meta?.asof_date || ''),
      generated_at: String(resp?.data?.meta?.generated_at || ''),
      scoring_version: String(resp?.data?.meta?.scoring_version || ''),
      run_id: String(resp?.data?.meta?.run_id || ''),
    }
  } finally {
    rotationLoading.value = false
  }
}

function refreshRotationList() {
  void fetchRotationList(false)
}

function recomputeRotationList() {
  void fetchRotationList(true)
}

async function fetchRotationRunList() {
  if (!baseURL) return
  const thsIndexType = selectedIndustryType.value === 'ths' ? selectedThsIndexType.value : 'ALL'
  const resp = await axios.get(`${baseURL}/industry-universe/rotation/runs/`, {
    params: { industry_type: selectedIndustryType.value, ths_index_type: thsIndexType, limit: 20, _ts: Date.now() },
  })
  const rows = Array.isArray(resp?.data?.data) ? resp.data.data : []
  rotationRunList.value = rows.map((row: any) => ({
    run_id: String(row?.run_id || ''),
    created_at: String(row?.created_at || ''),
    asof_date: String(row?.asof_date || ''),
  })).filter((row: RotationRunSummary) => Boolean(row.run_id))
}

async function fetchRotationRunDetail(runId: string) {
  if (!baseURL || !runId) return
  const thsIndexType = selectedIndustryType.value === 'ths' ? selectedThsIndexType.value : 'ALL'
  const resp = await axios.get(`${baseURL}/industry-universe/rotation/runs/${encodeURIComponent(runId)}/`, {
    params: { industry_type: selectedIndustryType.value, ths_index_type: thsIndexType, windows: '5,20,60', _ts: Date.now() },
  })
  const evaluation = resp?.data?.data?.evaluation || {}
  const windowsRaw = Array.isArray(evaluation?.windows) ? evaluation.windows : []
  const windows = windowsRaw
    .map((item: any) => Number(item))
    .filter((item: number) => Number.isInteger(item) && item > 0)

  rotationRunWindows.value = windows
  rotationRunPerformance.value = {
    topn_summary: evaluation?.topn_summary || {},
    benchmark_summary: evaluation?.benchmark_summary || {},
    alpha_summary: evaluation?.alpha_summary || {},
    hit_ratio_summary: evaluation?.hit_ratio_summary || {},
  }
  rotationRunDailySeries.value = Array.isArray(evaluation?.daily_series) ? evaluation.daily_series.map((item: any) => ({
    day_offset: Number(item?.day_offset || 0),
    trade_date: String(item?.trade_date || ''),
    topn_return: Number.isFinite(Number(item?.topn_return)) ? Number(item.topn_return) : null,
    benchmark_return: Number.isFinite(Number(item?.benchmark_return)) ? Number(item.benchmark_return) : null,
    alpha_return: Number.isFinite(Number(item?.alpha_return)) ? Number(item.alpha_return) : null,
    hit_ratio: Number.isFinite(Number(item?.hit_ratio)) ? Number(item.hit_ratio) : null,
  })) : []
}

async function selectRotationRun(runId: string) {
  const normalized = String(runId || '').trim()
  if (!normalized) return
  selectedRotationRunId.value = normalized
  await fetchRotationRunDetail(normalized)
}

async function openRotationRunDialog() {
  if (!baseURL) return
  rotationRunDialogVisible.value = true
  rotationRunLoading.value = true
  try {
    await fetchRotationRunList()
    if (!rotationRunList.value.length) {
      selectedRotationRunId.value = ''
      rotationRunWindows.value = []
      rotationRunDailySeries.value = []
      rotationRunPerformance.value = {
        topn_summary: {},
        benchmark_summary: {},
        alpha_summary: {},
        hit_ratio_summary: {},
      }
      return
    }
    const preferred = String(rotationMeta.value.run_id || '').trim()
    const matched = preferred
      ? rotationRunList.value.find((item) => item.run_id === preferred)
      : undefined
    await selectRotationRun(matched?.run_id || rotationRunList.value[0].run_id)
  } finally {
    rotationRunLoading.value = false
  }
}

async function deleteRotationRun(runId: string) {
  const normalized = String(runId || '').trim()
  if (!normalized) return
  try {
    await ElMessageBox.confirm(`确认删除 run ${normalized}？`, '删除Run', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }

  if (!baseURL) return
  const thsIndexType = selectedIndustryType.value === 'ths' ? selectedThsIndexType.value : 'ALL'
  await axios.delete(`${baseURL}/industry-universe/rotation/runs/${encodeURIComponent(normalized)}/delete/`, {
    params: { industry_type: selectedIndustryType.value, ths_index_type: thsIndexType },
  })
  ElMessage.success('run 已删除')
  await fetchRotationRunList()
  if (!rotationRunList.value.length) {
    rotationRunDailySeries.value = []
    rotationRunPerformance.value = {
      topn_summary: {},
      benchmark_summary: {},
      alpha_summary: {},
      hit_ratio_summary: {},
    }
    selectedRotationRunId.value = ''
    return
  }

  const nextSelected = rotationRunList.value.find((item) => item.run_id !== normalized) || rotationRunList.value[0]
  if (!nextSelected) return
  await selectRotationRun(nextSelected.run_id)
}

function selectRotationIndustry(item: {
  industry_code: string
  industry_name: string
}) {
  const normalizedCode = String(item?.industry_code || '').trim()
  if (!normalizedCode) return

  const matched = industryList.value.find((row) => (
    row.industry_type === selectedIndustryType.value && String(row.industry_key || '').trim() === normalizedCode
  ))
  if (matched) {
    selectIndustry(matched)
    return
  }

  selectIndustry({
    industry_type: selectedIndustryType.value,
    industry_key: normalizedCode,
    display_name: String(item?.industry_name || normalizedCode),
    member_count: 0,
  })
}

function selectIndustry(item: IndustryItem) {
  const nextType = item.industry_type
  const nextKey = String(item.industry_key || '').trim()
  if (selectedIndustryType.value === nextType && selectedIndustryKey.value === nextKey) {
    return
  }

  selectedIndustryType.value = nextType
  selectedIndustryKey.value = nextKey
  selectedIndustryName.value = item.display_name || ''
  currentPage.value = 1
  void fetchIndustryHistory()
  void fetchConstituents()
}

function handleConstituentPageChange(page: number) {
  currentPage.value = page
  void fetchConstituents()
}

function reloadConstituents() {
  currentPage.value = 1
  void fetchConstituents()
}

async function toggleWatch(row: SwConstituentRow) {
  if (!baseURL || !row.ts_code) return
  const url = row.in_watchlist
    ? `${baseURL}/watchlist/delete/${row.ts_code}/`
    : `${baseURL}/watchlist/add/${row.ts_code}/`
  await axios.post(url)
  await fetchConstituents()
}

async function toggleHold(row: SwConstituentRow) {
  if (!baseURL || !row.ts_code) return
  const url = row.hold_position
    ? `${baseURL}/watchlist/unhold/${row.ts_code}/`
    : `${baseURL}/watchlist/hold/${row.ts_code}/`
  await axios.post(url)
  await fetchConstituents()
}

async function toggleObserve(row: SwConstituentRow) {
  if (!baseURL || !row.ts_code) return
  const url = row.observe_only
    ? `${baseURL}/watchlist/unobserve/${row.ts_code}/`
    : `${baseURL}/watchlist/observe/${row.ts_code}/`
  await axios.post(url)
  await fetchConstituents()
}

function openStockDialog(row: SwConstituentRow) {
  const tsCode = String(row.ts_code || '').trim().toUpperCase()
  if (!tsCode) return
  selectedConstituentIndex.value = constituents.value.findIndex((item) => String(item.ts_code || '').trim().toUpperCase() === tsCode)
  syncDialogStock(row)
  stockDialogVisible.value = true
}

function navigateToStockByIndex(index: number) {
  if (index < 0 || index >= constituents.value.length) return
  selectedConstituentIndex.value = index
  syncDialogStock(constituents.value[index])
}

function navigatePrevStock() {
  navigateToStockByIndex(selectedConstituentIndex.value - 1)
}

function navigateNextStock() {
  navigateToStockByIndex(selectedConstituentIndex.value + 1)
}

watch([metric, period], () => {
  void fetchIndustryHistory()
})

watch([constituentMarket], () => {
  reloadConstituents()
})

watch(selectedIndustryType, async () => {
  metric.value = 'pe'
  selectedThsIndexType.value = selectedIndustryType.value === 'ths' ? 'N' : 'ALL'
  selectedIndustryKey.value = ''
  selectedIndustryName.value = ''
  currentPage.value = 1
  await fetchIndustryList()
  if (industryTab.value === 'rotation') {
    await fetchRotationList(false)
  }
})

watch(selectedThsIndexType, async () => {
  if (selectedIndustryType.value !== 'ths') return
  selectedIndustryKey.value = ''
  selectedIndustryName.value = ''
  currentPage.value = 1
  await fetchIndustryList()
  if (industryTab.value === 'rotation') {
    await fetchRotationList(false)
  }
})

watch(industryTab, async (tab) => {
  if (tab === 'rotation') {
    await fetchRotationList(false)
  }
})

onMounted(async () => {
  try {
    loadFavoriteIndustryKeys()
    await fetchIndustryList()
  } catch (error) {
    console.error(error)
    ElMessage.error('加载行业页面失败')
  }
})
</script>

<style scoped>
.sw-industry-page {
  padding: 6px 0;
}

.sw-panel {
  min-height: 700px;
}

.sw-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.sw-industry-header {
  align-items: flex-start;
}

.sw-industry-type-select {
  width: 144px;
}

.sw-ths-index-type-select {
  width: 156px;
}

.sw-industry-tabs {
  margin-top: -8px;
}

.sw-industry-list-scroll {
  height: 620px;
}

.sw-rotation-panel {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px;
  background: #f8fafc;
}

.sw-rotation-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.sw-rotation-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 8px;
  font-size: 12px;
  color: #64748b;
}

.sw-rotation-scroll {
  height: 548px;
}

.sw-rotation-actions-bottom {
  margin-top: 10px;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.sw-rotation-item {
  border: 1px solid #dbeafe;
  border-radius: 8px;
  padding: 8px;
  margin-bottom: 8px;
  background: #eff6ff;
  cursor: pointer;
}

.sw-rotation-item.active {
  border-color: #2563eb;
  background: #dbeafe;
}

.sw-rotation-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sw-rotation-rank {
  font-weight: 700;
  color: #1d4ed8;
}

.sw-rotation-name {
  font-weight: 600;
  color: #1e293b;
}

.sw-rotation-sub {
  margin-top: 2px;
  color: #475569;
  font-size: 12px;
}

.sw-rotation-score {
  margin-top: 6px;
  font-size: 12px;
  color: #0f172a;
}

.sw-rotation-breakdown {
  margin-top: 4px;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 12px;
  color: #334155;
}

.sw-rotation-run-layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 12px;
  min-height: 520px;
}

.sw-rotation-run-list {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  padding: 8px;
}

.sw-rotation-run-list-title {
  font-size: 13px;
  color: #475569;
  margin-bottom: 8px;
}

.sw-rotation-run-scroll {
  height: 460px;
}

.sw-rotation-run-item {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
  padding: 8px;
  margin-bottom: 8px;
  cursor: pointer;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.sw-rotation-run-row {
  min-width: 0;
  flex: 1;
}

.sw-rotation-run-item.active {
  border-color: #2563eb;
  background: #eff6ff;
}

.sw-rotation-run-id {
  font-size: 12px;
  color: #1e3a8a;
  font-weight: 600;
}

.sw-rotation-run-meta {
  margin-top: 4px;
  font-size: 12px;
  color: #64748b;
}

.sw-rotation-run-chart-wrap {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px;
  background: #ffffff;
}

.sw-rotation-run-headline {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 12px;
  color: #475569;
  margin-bottom: 8px;
}

.sw-rotation-run-chart {
  height: 460px;
}

@media (max-width: 960px) {
  .sw-rotation-run-layout {
    grid-template-columns: 1fr;
  }
  .sw-rotation-run-scroll {
    height: 220px;
  }
  .sw-rotation-run-chart {
    height: 320px;
  }
}

.sw-industry-item {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.18s ease;
}

.sw-industry-item:hover {
  border-color: #93c5fd;
  background: #eff6ff;
}

.sw-industry-item.active {
  border-color: #2563eb;
  background: #dbeafe;
}

.sw-industry-item.favorite {
  border-color: #f59e0b;
  background: #fffbeb;
}

.sw-industry-item.favorite .sw-industry-name {
  color: #b45309;
}

.sw-industry-item.favorite.active {
  border-color: #d97706;
  background: #fef3c7;
}

.sw-industry-name {
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 4px;
}

.sw-industry-meta {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #6b7280;
}

.sw-industry-extra {
  margin-top: 4px;
  font-size: 11px;
  color: #64748b;
}

.sw-history-header {
  align-items: flex-start;
}

.sw-history-title-row {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.sw-toolbar {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-end;
}

.sw-summary {
  margin-bottom: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  color: #475569;
  font-size: 12px;
}

.sw-history-chart {
  height: 620px;
}

.sw-members-header {
  align-items: flex-start;
}

.sw-members-toolbar {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 220px;
}

.sw-member-tags {
  margin-top: 4px;
  display: flex;
  gap: 4px;
}

.sw-member-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
}

.sw-pagination {
  margin-top: 10px;
  display: flex;
  justify-content: flex-end;
}

.sw-stock-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: calc(100% - 28px);
}

.sw-stock-dialog-title {
  font-size: 18px;
  font-weight: 600;
  color: #111827;
}

.sw-stock-dialog-nav {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

:deep(.sw-members-table .el-button.is-text) {
  padding: 2px 4px;
}

@media (max-width: 1200px) {
  .sw-panel {
    min-height: 520px;
  }

  .sw-industry-list-scroll,
  .sw-history-chart {
    height: 420px;
  }
}
</style>
