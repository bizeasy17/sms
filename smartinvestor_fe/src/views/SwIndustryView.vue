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
              <el-tab-pane :label="`收藏行业 (${favoriteIndustryList.length})`" name="favorites" />
            </el-tabs>
            <el-scrollbar class="sw-industry-list-scroll">
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
  </DefaultLayout>
</template>

<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from 'vue'
import axios from 'axios'
import { ElButton, ElCard, ElCol, ElDialog, ElEmpty, ElInput, ElLink, ElMessage, ElOption, ElPagination, ElRadioButton, ElRadioGroup, ElRow, ElScrollbar, ElSelect, ElTable, ElTableColumn, ElTabPane, ElTabs, ElTag } from 'element-plus'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { TooltipComponent, GridComponent, DataZoomComponent, LegendComponent, MarkLineComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import DefaultLayout from '../layouts/DefaultLayout.vue'
import StockChartFilter from '../components/StockChartFilter.vue'
import { useStockTradeStore } from '../stores/stockTradeStore'

use([CanvasRenderer, LineChart, TooltipComponent, GridComponent, DataZoomComponent, LegendComponent, MarkLineComponent])

type IndustryType = 'sw' | 'valuation_variant' | 'corp_industry'

type IndustryItem = {
  industry_type: IndustryType
  industry_key: string
  display_name: string
  member_count: number
  extra_label?: string
}

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
  { value: 'valuation_variant', label: '行业变体' },
  { value: 'corp_industry', label: '基本信息行业' },
]

const selectedIndustryType = ref<IndustryType>('sw')
const industryList = ref<IndustryItem[]>([])
const industryKeyword = ref('')
const industryTab = ref<'all' | 'favorites'>('all')
const favoriteIndustryKeys = ref<string[]>([])
const selectedIndustryKey = ref('')
const selectedIndustryName = ref('')

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
  const resp = await axios.get(`${baseURL}/industry-universe/list/`, {
    params: {
      industry_type: selectedIndustryType.value,
      keyword: industryKeyword.value.trim(),
    },
  })
  const rows = Array.isArray(resp?.data?.data) ? resp.data.data : []
  industryList.value = rows
    .map((row: any) => ({
      industry_type: String(row?.industry_type || selectedIndustryType.value) as IndustryType,
      industry_key: String(row?.industry_key || ''),
      display_name: String(row?.display_name || ''),
      member_count: Number(row?.member_count || 0),
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
  const resp = await axios.get(`${baseURL}/industry-universe/history/`, {
    params: {
      industry_type: selectedIndustryType.value,
      industry_key: selectedIndustryKey.value,
      metric: metric.value,
      period: period.value,
    },
  })
  historyRows.value = (Array.isArray(resp?.data?.data) ? resp.data.data : [])
    .map((row: any) => ({
      trade_date: String(row?.trade_date || ''),
      value: Number.isFinite(Number(row?.value)) ? Number(row?.value) : null,
    }))
    .filter((row: IndustryHistoryRow) => Boolean(row.trade_date))

  const meta = resp?.data?.meta || {}
  historyMeta.value = {
    q10: Number.isFinite(Number(meta.q10)) ? Number(meta.q10) : null,
    q50: Number.isFinite(Number(meta.q50)) ? Number(meta.q50) : null,
    q90: Number.isFinite(Number(meta.q90)) ? Number(meta.q90) : null,
    latest_value: Number.isFinite(Number(meta.latest_value)) ? Number(meta.latest_value) : null,
    latest_trade_date: String(meta.latest_trade_date || ''),
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

function selectIndustry(item: IndustryItem) {
  selectedIndustryType.value = item.industry_type
  selectedIndustryKey.value = String(item.industry_key || '').trim()
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
  selectedIndustryKey.value = ''
  selectedIndustryName.value = ''
  currentPage.value = 1
  await fetchIndustryList()
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

.sw-industry-tabs {
  margin-top: -8px;
}

.sw-industry-list-scroll {
  height: 620px;
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
