<template>
    <el-header class="header">
        <div class="header-left">
            <img src="../../assets/logo.png" alt="Logo" class="logo" />
            <span class="app-title">Jiu Cai</span>
            <div class="header-nav-wrap">
                <el-menu mode="horizontal" class="header-menu" background-color="transparent" text-color="#333"
                    active-text-color="#409EFF" :border="false" style="flex: none;">
                    <el-menu-item index="dashboard">
                        <router-link to="/"
                            style="display: flex; align-items: center; text-decoration: none; color: inherit;">
                            <el-icon style="vertical-align: middle; margin-right: 6px;">
                                <HomeFilled />
                            </el-icon>
                            Dashboard
                        </router-link>
                    </el-menu-item>
                    
                    <el-menu-item index="valuation-pick">
                        <router-link to="/picking-valuation"
                            style="display: flex; align-items: center; text-decoration: none; color: inherit;">
                            <el-icon style="vertical-align: middle; margin-right: 6px;">
                                <DataAnalysis />
                            </el-icon>
                            估值选股
                        </router-link>
                    </el-menu-item>
                    <el-menu-item index="sw-industry">
                        <router-link to="/sw-industry"
                            style="display: flex; align-items: center; text-decoration: none; color: inherit;">
                            <el-icon style="vertical-align: middle; margin-right: 6px;">
                                <DataAnalysis />
                            </el-icon>
                            SW行业
                        </router-link>
                    </el-menu-item>
                    <el-menu-item index="supply-chain-graph">
                        <router-link to="/supply-chain"
                            style="display: flex; align-items: center; text-decoration: none; color: inherit;">
                            <el-icon style="vertical-align: middle; margin-right: 6px;">
                                <DataAnalysis />
                            </el-icon>
                            供应链图谱
                        </router-link>
                    </el-menu-item>
                    <el-sub-menu index="backtest">
                        <template #title>
                            <div style="display: flex; align-items: center;">
                                <el-icon style="vertical-align: middle; margin-right: 6px;">
                                    <Histogram />
                                </el-icon>
                                回测
                            </div>
                        </template>
                        <el-menu-item index="backtest-execute">
                            <router-link to="/backtest-execute"
                                style="display: flex; align-items: center; text-decoration: none; color: inherit; width: 100%;">
                                回测执行
                            </router-link>
                        </el-menu-item>
                        <el-menu-item index="backtest-query">
                            <router-link to="/backtest-query"
                                style="display: flex; align-items: center; text-decoration: none; color: inherit; width: 100%;">
                                回测查询
                            </router-link>
                        </el-menu-item>
                    </el-sub-menu>
                    <el-menu-item index="schedule-jobs">
                        <router-link to="/schedule-jobs"
                            style="display: flex; align-items: center; text-decoration: none; color: inherit;">
                            调度总览
                        </router-link>
                    </el-menu-item>
                </el-menu>
            </div>
            <div class="header-search-wrap">
                <el-autocomplete v-model="state" :fetch-suggestions="querySearchAsync" placeholder="请输入股票代码或名称"
                    class="header-search" :trigger-on-focus="true" @select="handleSelect" clearable>
                    <template #default="{ item }">
                        <div>
                            <div>
                                <span style="font-weight:bold; color:#409EFF; font-size:13px;">{{ item.name }} {{ item.ts_code }}</span>
                            </div>
                            <div>
                                <span style="color:#999; font-size:12px;">{{ item.__source === 'history' ? '最近搜索' : '上市日期: ' + item.listdate }}</span>
                            </div>
                        </div>
                    </template>
                </el-autocomplete>
            </div>
            <div v-if="showMarketQuantileInline" class="header-market-quantile-wrap">
                <el-tooltip :content="marketOverallInlineFullText" placement="bottom-start">
                    <el-link
                        type="primary"
                        :underline="false"
                        class="header-market-quantile-chip"
                        @click="openHeaderMarketQuantileDialog('market')"
                    >
                        {{ marketOverallInlineShortText }}
                    </el-link>
                </el-tooltip>
                <el-tooltip :content="shBenchmarkInlineFullText" placement="bottom-start">
                    <el-link
                        type="primary"
                        :underline="false"
                        class="header-market-quantile-chip"
                        @click="openHeaderMarketQuantileDialog('shanghai')"
                    >
                        {{ shBenchmarkInlineShortText }}
                    </el-link>
                </el-tooltip>
            </div>
        </div>
        <div class="header-right">

            <el-avatar :src="userPhoto" size="default" class="user-avatar"></el-avatar>
            <span class="user-name">{{ userName }}</span>
        </div>
        <el-dialog
            v-model="headerMarketQuantileDialogVisible"
            width="78%"
            top="8vh"
            :title="`${headerMarketQuantileDialogMarketLabel}趋势`"
        >
            <div class="header-market-quantile-dialog-toolbar">
                <el-radio-group v-model="headerMarketQuantileDialogMarket" size="small">
                    <el-radio-button label="market">大盘分位</el-radio-button>
                    <el-radio-button label="shanghai">上证分位</el-radio-button>
                </el-radio-group>
                <el-radio-group v-model="headerMarketQuantileDialogMetric" size="small">
                    <el-radio-button
                        v-for="item in HEADER_MARKET_METRIC_OPTIONS"
                        :key="item.key"
                        :label="item.key"
                    >
                        {{ item.label }}
                    </el-radio-button>
                </el-radio-group>
                <el-radio-group
                    v-model="headerMarketQuantileDialogStyle"
                    size="small"
                    :disabled="headerMarketQuantileDialogMarket === 'shanghai'"
                >
                    <el-radio-button
                        v-for="item in HEADER_MARKET_STYLE_OPTIONS"
                        :key="item.key"
                        :label="item.key"
                    >
                        {{ item.label }}
                    </el-radio-button>
                </el-radio-group>
                <el-radio-group v-model="headerMarketQuantileDialogPeriod" size="small">
                    <el-radio-button
                        v-for="item in HEADER_MARKET_PERIOD_OPTIONS"
                        :key="item.key"
                        :label="item.key"
                    >
                        {{ item.label }}
                    </el-radio-button>
                </el-radio-group>
            </div>
            <div class="header-market-quantile-dialog-summary" v-if="headerMarketQuantileChartRows.length || headerSimpleValuationLoading || headerSimpleCompositePrice !== null || headerSimpleConservativePrice !== null || Boolean(headerSimpleValuationError)">
                <span>{{ headerMarketQuantileDialogMarketLabel }} {{ headerMarketQuantileDialogMetricLabel }} 最新值 {{ formatMetricValue(headerMarketQuantileSummary.latestValue) }}</span>
                <span>日期 {{ headerMarketQuantileSummary.latestDate || headerMarketQuantileDialogAsOfText || '-' }}</span>
                <span>{{ headerMarketQuantileDialogPeriodLabel }}分位 {{ formatPercent(headerMarketQuantilePeriodPercentilePct) }}%</span>
                <span>P10 {{ formatMetricValue(headerMarketQuantileDynamicLevels.p10) }}</span>
                <span>P50 {{ formatMetricValue(headerMarketQuantileDynamicLevels.p50) }}</span>
                <span>P90 {{ formatMetricValue(headerMarketQuantileDynamicLevels.p90) }}</span>
                <span v-if="headerSimpleValuationLoading">简化估值计算中...</span>
                <span v-if="!headerSimpleValuationLoading && headerSimpleValuationError">简化估值不可用：{{ headerSimpleValuationError }}</span>
                <span v-else-if="headerSimpleCompositePrice !== null">
                    组合估值 {{ formatMetricValue(headerSimpleCompositePrice) }} ({{ formatValuationStatusLabel(headerSimpleCompositeStatus) }} {{ formatSignedPercent(headerSimpleCompositeGapPct) }}%)
                </span>
                <span v-if="!headerSimpleValuationLoading && headerSimpleConservativePrice !== null">
                    保守估值 {{ formatMetricValue(headerSimpleConservativePrice) }} ({{ formatValuationStatusLabel(headerSimpleConservativeStatus) }} {{ formatSignedPercent(headerSimpleConservativeGapPct) }}%)
                </span>
            </div>
            <v-chart v-if="headerMarketQuantileChartOption" :option="headerMarketQuantileChartOption" autoresize class="header-market-quantile-chart" />
            <el-empty v-else description="当前市场没有可展示的分位历史" />
        </el-dialog>
    </el-header>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import axios from 'axios'
import { ElMenu, ElMenuItem, ElSubMenu, ElIcon, ElHeader, ElAvatar, ElTooltip, ElDialog, ElRadioGroup, ElRadioButton, ElEmpty } from 'element-plus'
import avatarImg from '../../assets/avatar.png'
import { HomeFilled, DataAnalysis, Histogram } from '@element-plus/icons-vue'
// Element Plus
import { ElAutocomplete } from 'element-plus'
import { inject } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { TooltipComponent, GridComponent, DataZoomComponent, LegendComponent, MarkLineComponent } from 'echarts/components'
import VChart from 'vue-echarts'
// store
import { useStockTradeStore } from '../../stores/stockTradeStore'

use([CanvasRenderer, LineChart, TooltipComponent, GridComponent, DataZoomComponent, LegendComponent, MarkLineComponent])

const baseURL = inject('baseURL')
const stockTradeStore = useStockTradeStore()
const state = ref('')
const userName = ref('John Doe')
const userPhoto = ref(avatarImg)
const SEARCH_HISTORY_KEY = 'smartinvestor_search_history_v1'
const MAX_SEARCH_HISTORY = 10
const HEADER_INDEX_START_DATE = '20040101'

type CorporationSuggestion = {
    ts_code: string
    name: string
    listdate?: string
    __source?: 'history' | 'remote'
}

const searchHistory = ref<CorporationSuggestion[]>([])
const headerMarketQuantileDialogVisible = ref(false)
const headerMarketQuantileDialogMarket = ref<'market' | 'shanghai'>('market')
const headerMarketQuantileDialogMetric = ref<'pe' | 'pe_ttm' | 'pb'>('pe')
const headerMarketQuantileDialogStyle = ref<'overall' | 'defensive' | 'balanced' | 'aggressive'>('overall')
const headerMarketQuantileDialogPeriod = ref<'30D' | '60D' | '90D' | '1Y' | '3Y' | '5Y' | '10Y' | 'ALL'>('5Y')
const headerSimpleValuation = ref<any | null>(null)
const headerSimpleValuationLoading = ref(false)
const headerSimpleValuationError = ref('')
const headerMarketSentimentRows = ref<MarketSentimentRow[]>([])
let headerMarketSentimentRequest: Promise<void> | null = null

const HEADER_MARKET_METRIC_OPTIONS = [
    { key: 'pe', label: 'PE' },
    { key: 'pe_ttm', label: 'PETTM' },
    { key: 'pb', label: 'PB' },
] as const

type MarketMetricKey = 'pe' | 'pe_ttm' | 'pb'
type MarketMetricSourceRow = { trade_date: string; pe: number | null; pe_ttm: number | null; pb: number | null }
type MarketIndexKey = 'sh' | 'sz' | 'hs300' | 'sse50' | 'csi500' | 'sme' | 'cyb'
type MarketStyleKey = 'overall' | 'defensive' | 'balanced' | 'aggressive'

const HEADER_MARKET_STYLE_OPTIONS: Array<{ key: MarketStyleKey; label: string }> = [
    { key: 'overall', label: '综合' },
    { key: 'defensive', label: '防御' },
    { key: 'balanced', label: '平衡' },
    { key: 'aggressive', label: '进攻' },
]

const HEADER_INDEX_DEFS = [
    { key: 'sh', label: '上证', tsCode: '000001.SH' },
    { key: 'sz', label: '深成指', tsCode: '399001.SZ' },
    { key: 'hs300', label: '沪深300', tsCode: '399300.SZ' },
    { key: 'sse50', label: '上证50', tsCode: '000016.SH' },
    { key: 'csi500', label: '中证500', tsCode: '000905.SH' },
    { key: 'sme', label: '中小板指', tsCode: '399005.SZ' },
    { key: 'cyb', label: '创指', tsCode: '399006.SZ' },
] as const satisfies ReadonlyArray<{ key: MarketIndexKey; label: string; tsCode: string }>

const HEADER_COMPOSITE_STYLE_WEIGHTS: Record<MarketStyleKey, Record<MarketIndexKey, number>> = {
    overall: {
        sh: 0.18,
        sz: 0.16,
        hs300: 0.20,
        sse50: 0.14,
        csi500: 0.14,
        sme: 0.08,
        cyb: 0.10,
    },
    defensive: {
        sh: 0.24,
        sz: 0.12,
        hs300: 0.26,
        sse50: 0.20,
        csi500: 0.10,
        sme: 0.03,
        cyb: 0.05,
    },
    balanced: {
        sh: 0.18,
        sz: 0.16,
        hs300: 0.20,
        sse50: 0.16,
        csi500: 0.15,
        sme: 0.06,
        cyb: 0.09,
    },
    aggressive: {
        sh: 0.10,
        sz: 0.18,
        hs300: 0.14,
        sse50: 0.08,
        csi500: 0.18,
        sme: 0.12,
        cyb: 0.20,
    },
}

const headerIndexHistoryMap = ref<Record<string, MarketMetricSourceRow[]>>({})

const HEADER_MARKET_PERIOD_OPTIONS = [
    { key: '30D', label: '30D' },
    { key: '60D', label: '60D' },
    { key: '90D', label: '90D' },
    { key: '1Y', label: '1Y' },
    { key: '3Y', label: '3Y' },
    { key: '5Y', label: '5Y' },
    { key: '10Y', label: '10Y' },
    { key: 'ALL', label: '所有' },
] as const

type MarketHistoryRow = {
    trade_date: string
    value: number
}

type MarketSentimentRow = {
    trade_date: string
    score: number | null
    level: string
    status: string
    momentum_score: number | null
    activity_score: number | null
    fear_score: number | null
}

type MarketSummaryRow = {
    key: string
    label: string
    latestValue: number | null
    latestDate: string
    fiveYearPercentilePct: number | null
    tenYearPercentilePct: number | null
    allHistoryPercentilePct: number | null
}

function resolveMetricValue(item: MarketMetricSourceRow, metricKey: MarketMetricKey): number | null {
    if (metricKey === 'pe') return Number.isFinite(Number(item?.pe)) ? Number(item.pe) : null
    if (metricKey === 'pe_ttm') return Number.isFinite(Number(item?.pe_ttm)) ? Number(item.pe_ttm) : null
    return Number.isFinite(Number(item?.pb)) ? Number(item.pb) : null
}

function getIndexRows(indexKey: string, metricKey: MarketMetricKey): MarketHistoryRow[] {
    const rows = headerIndexHistoryMap.value[indexKey] || []
    return rows
        .map((item) => ({
            trade_date: String(item?.trade_date || '').trim(),
            value: resolveMetricValue(item, metricKey),
        }))
        .filter((item): item is MarketHistoryRow => Boolean(item.trade_date) && Number.isFinite(item.value))
}

function buildCompositeRows(metricKey: MarketMetricKey, styleKey: MarketStyleKey): MarketHistoryRow[] {
    const styleWeights = HEADER_COMPOSITE_STYLE_WEIGHTS[styleKey] || HEADER_COMPOSITE_STYLE_WEIGHTS.overall
    const indexKeys = Object.keys(styleWeights) as MarketIndexKey[]
    if (!indexKeys.length) {
        return []
    }

    const rowsByIndex: Record<MarketIndexKey, MarketHistoryRow[]> = {
        sh: getIndexRows('sh', metricKey),
        sz: getIndexRows('sz', metricKey),
        hs300: getIndexRows('hs300', metricKey),
        sse50: getIndexRows('sse50', metricKey),
        csi500: getIndexRows('csi500', metricKey),
        sme: getIndexRows('sme', metricKey),
        cyb: getIndexRows('cyb', metricKey),
    }

    if (indexKeys.some((key) => !rowsByIndex[key].length)) {
        return []
    }

    const seedKey = indexKeys[0]
    const dateSet = new Set(rowsByIndex[seedKey].map((item) => item.trade_date))
    for (const date of Array.from(dateSet)) {
        if (indexKeys.some((key) => !rowsByIndex[key].some((item) => item.trade_date === date))) {
            dateSet.delete(date)
        }
    }
    const sharedDates = Array.from(dateSet).sort()
    if (!sharedDates.length) {
        return []
    }
    const mapByDate = (rows: MarketHistoryRow[]) => {
        const output = new Map<string, number>()
        for (const row of rows) {
            output.set(row.trade_date, row.value)
        }
        return output
    }
    const mapByIndex: Record<MarketIndexKey, Map<string, number>> = {
        sh: mapByDate(rowsByIndex.sh),
        sz: mapByDate(rowsByIndex.sz),
        hs300: mapByDate(rowsByIndex.hs300),
        sse50: mapByDate(rowsByIndex.sse50),
        csi500: mapByDate(rowsByIndex.csi500),
        sme: mapByDate(rowsByIndex.sme),
        cyb: mapByDate(rowsByIndex.cyb),
    }

    const weightTotal = indexKeys.reduce((acc, key) => acc + (Number(styleWeights[key]) || 0), 0)
    if (!(weightTotal > 0)) {
        return []
    }

    return sharedDates.map((date) => {
        let weightedSum = 0
        for (const key of indexKeys) {
            const rawValue = Number(mapByIndex[key].get(date) || 0)
            const weightValue = Number(styleWeights[key]) || 0
            weightedSum += rawValue * weightValue
        }

        const composite = weightedSum / weightTotal

        return {
            trade_date: date,
            value: Number(composite.toFixed(4)),
        }
    })
}

const showMarketQuantileInline = computed(() => {
    return true
})

const marketOverallAsOfText = computed(() => String(marketOverallMetricRows.value[0]?.latestDate || '').trim())
const shBenchmarkAsOfText = computed(() => String(shBenchmarkMetricRows.value[0]?.latestDate || '').trim())

const marketOverallInlineFullText = computed(() => {
    return buildMarketQuantileSummaryText('大盘分位', marketOverallAsOfText.value, marketOverallMetricRows.value)
})

const marketOverallInlineShortText = computed(() => {
    return buildMarketQuantileShortText('大盘分位', marketOverallAsOfText.value, marketOverallMetricRows.value)
})

const shBenchmarkInlineFullText = computed(() => {
    return buildMarketQuantileSummaryText('上证分位', shBenchmarkAsOfText.value, shBenchmarkMetricRows.value)
})

const shBenchmarkInlineShortText = computed(() => {
    return buildMarketQuantileShortText('上证分位', shBenchmarkAsOfText.value, shBenchmarkMetricRows.value)
})

const headerMarketQuantileDialogMetricLabel = computed(() => (
    HEADER_MARKET_METRIC_OPTIONS.find((item) => item.key === headerMarketQuantileDialogMetric.value)?.label || 'PE'
))

const headerMarketQuantileDialogPeriodLabel = computed(() => (
    HEADER_MARKET_PERIOD_OPTIONS.find((item) => item.key === headerMarketQuantileDialogPeriod.value)?.label || String(headerMarketQuantileDialogPeriod.value)
))

const headerMarketQuantileDialogStyleLabel = computed(() => (
    HEADER_MARKET_STYLE_OPTIONS.find((item) => item.key === headerMarketQuantileDialogStyle.value)?.label || '综合'
))

const headerMarketQuantileDialogMarketLabel = computed(() => (
    headerMarketQuantileDialogMarket.value === 'shanghai'
        ? '上证指数'
        : `${headerMarketQuantileDialogStyleLabel.value}综合指数`
))

const headerMarketQuantileDialogAsOfText = computed(() => {
    return String(headerMarketQuantileSummary.value.latestDate || '').trim()
})

function parseHistoryDate(value: string): Date | null {
    const raw = String(value || '').trim()
    if (!raw) return null
    const normalized = /^\d{8}$/.test(raw)
        ? `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`
        : raw
    const parsed = new Date(`${normalized}T00:00:00`)
    return Number.isNaN(parsed.getTime()) ? null : parsed
}

function normalizeHistoryDateKey(value: string): string {
    return String(value || '').trim().replace(/-/g, '')
}

function filterHistoryRowsByPeriod(
    rows: MarketHistoryRow[],
    period: '30D' | '60D' | '90D' | '1Y' | '3Y' | '5Y' | '10Y' | 'ALL',
): MarketHistoryRow[] {
    if (!rows.length || period === 'ALL') return rows
    const latestDate = parseHistoryDate(rows[rows.length - 1]?.trade_date || '')
    if (!latestDate) return rows
    const cutoff = new Date(latestDate)
    if (period === '30D') cutoff.setDate(cutoff.getDate() - 30)
    else if (period === '60D') cutoff.setDate(cutoff.getDate() - 60)
    else if (period === '90D') cutoff.setDate(cutoff.getDate() - 90)
    else if (period === '1Y') cutoff.setFullYear(cutoff.getFullYear() - 1)
    else if (period === '3Y') cutoff.setFullYear(cutoff.getFullYear() - 3)
    else if (period === '5Y') cutoff.setFullYear(cutoff.getFullYear() - 5)
    else if (period === '10Y') cutoff.setFullYear(cutoff.getFullYear() - 10)
    return rows.filter((item) => {
        const tradeDate = parseHistoryDate(item.trade_date)
        return tradeDate ? tradeDate >= cutoff : false
    })
}

function computeLatestPercentile(rows: MarketHistoryRow[], years: number | null): number | null {
    if (!rows.length) return null
    let selected = rows
    if (years !== null) {
        const latestDate = parseHistoryDate(rows[rows.length - 1]?.trade_date || '')
        if (latestDate) {
            const cutoff = new Date(latestDate)
            cutoff.setFullYear(cutoff.getFullYear() - years)
            selected = rows.filter((item) => {
                const d = parseHistoryDate(item.trade_date)
                return d ? d >= cutoff : false
            })
        }
    }
    if (!selected.length) return null
    const latestValue = Number(selected[selected.length - 1].value)
    const values = selected.map((item) => Number(item.value)).filter((item) => Number.isFinite(item))
    if (!values.length || !Number.isFinite(latestValue)) return null
    const leCount = values.filter((item) => item <= latestValue).length
    return Number(((leCount / values.length) * 100).toFixed(2))
}

function computePercentileValue(rows: MarketHistoryRow[], percentile: number): number | null {
    if (!rows.length) return null
    const values = rows
        .map((item) => Number(item.value))
        .filter((item) => Number.isFinite(item))
        .sort((a, b) => a - b)
    if (!values.length) return null
    const p = Math.min(100, Math.max(0, Number(percentile)))
    const rank = (p / 100) * (values.length - 1)
    const lower = Math.floor(rank)
    const upper = Math.ceil(rank)
    if (lower === upper) return Number(values[lower].toFixed(4))
    const weight = rank - lower
    const interpolated = values[lower] * (1 - weight) + values[upper] * weight
    return Number(interpolated.toFixed(4))
}

function buildSummaryRow(key: string, label: string, rows: MarketHistoryRow[]): MarketSummaryRow {
    const latest = rows.length ? rows[rows.length - 1] : null
    return {
        key,
        label,
        latestValue: latest?.value ?? null,
        latestDate: latest?.trade_date || '',
        fiveYearPercentilePct: computeLatestPercentile(rows, 5),
        tenYearPercentilePct: computeLatestPercentile(rows, 10),
        allHistoryPercentilePct: computeLatestPercentile(rows, null),
    }
}

const marketCompositeRows = computed(() => buildCompositeRows(
    headerMarketQuantileDialogMetric.value as MarketMetricKey,
    headerMarketQuantileDialogStyle.value,
))

const marketCompositeSummary = computed(() => buildSummaryRow(
    'market',
    `${headerMarketQuantileDialogStyleLabel.value}综合指数`,
    marketCompositeRows.value,
))
const shanghaiSummary = computed(() => buildSummaryRow('sh', '上证', getIndexRows('sh', headerMarketQuantileDialogMetric.value as MarketMetricKey)))

const marketOverallMetricRows = computed(() => {
    if (marketCompositeSummary.value.latestValue === null) return []
    return [marketCompositeSummary.value]
})

const shBenchmarkMetricRows = computed(() => {
    if (shanghaiSummary.value.latestValue === null) return []
    return [shanghaiSummary.value]
})

const headerMarketQuantileChartRows = computed(() => {
    const sourceRows = headerMarketQuantileDialogMarket.value === 'shanghai'
        ? getIndexRows('sh', headerMarketQuantileDialogMetric.value as MarketMetricKey)
        : marketCompositeRows.value
    return filterHistoryRowsByPeriod(sourceRows, headerMarketQuantileDialogPeriod.value)
})

const headerMarketQuantileSummary = computed(() => {
    const sourceRows = headerMarketQuantileChartRows.value
    const latest = sourceRows.length ? sourceRows[sourceRows.length - 1] : null
    return {
        latestValue: latest?.value ?? null,
        latestDate: latest?.trade_date || '',
        fiveYearPercentilePct: computeLatestPercentile(sourceRows, null),
        tenYearPercentilePct: computeLatestPercentile(sourceRows, null),
        allHistoryPercentilePct: computeLatestPercentile(sourceRows, null),
    }
})

const headerSimpleSummary = computed(() => {
    const summary = headerSimpleValuation.value?.summary
    return summary && typeof summary === 'object' ? summary : null
})

const headerSimpleCompositePrice = computed(() => toNullableNumber(headerSimpleSummary.value?.composite_valuation_price))
const headerSimpleCompositeStatus = computed(() => String(headerSimpleSummary.value?.composite_valuation_status || '').trim().toLowerCase())
const headerSimpleCompositeGapPct = computed(() => toNullableNumber(headerSimpleSummary.value?.composite_valuation_gap_pct))
const headerSimpleConservativePrice = computed(() => toNullableNumber(headerSimpleSummary.value?.conservative_valuation_price))
const headerSimpleConservativeStatus = computed(() => String(headerSimpleSummary.value?.conservative_valuation_status || '').trim().toLowerCase())
const headerSimpleConservativeGapPct = computed(() => toNullableNumber(headerSimpleSummary.value?.conservative_valuation_gap_pct))

const headerMarketQuantilePeriodPercentilePct = computed(() => {
    return computeLatestPercentile(headerMarketQuantileChartRows.value, null)
})

const headerMarketQuantileDynamicLevels = computed(() => {
    const rows = headerMarketQuantileChartRows.value
    return {
        p10: computePercentileValue(rows, 10),
        p50: computePercentileValue(rows, 50),
        p90: computePercentileValue(rows, 90),
    }
})

const headerMarketQuantileChartOption = computed(() => {
    const rows = headerMarketQuantileChartRows.value
    if (!rows.length) return null
    const levels = headerMarketQuantileDynamicLevels.value
    const sentimentByDate = new Map(headerMarketSentimentRows.value.map((item) => [normalizeHistoryDateKey(item.trade_date), item]))
    const sentimentData = rows.map((item) => {
        const sentiment = sentimentByDate.get(normalizeHistoryDateKey(item.trade_date))
        const unavailable = !sentiment
            || sentiment.score === null
            || sentiment.level === 'WARMING_UP'
            || sentiment.level === 'INSUFFICIENT_DATA'
            || sentiment.status === 'WARMING_UP'
            || sentiment.status === 'INSUFFICIENT_DATA'
        return unavailable ? null : sentiment.score
    })
    const markLineData = [
        { key: 'P10', value: levels.p10, color: '#10b981' },
        { key: 'P50', value: levels.p50, color: '#f59e0b' },
        { key: 'P90', value: levels.p90, color: '#ef4444' },
    ]
        .filter((item) => item.value !== null)
        .map((item) => ({
            name: item.key,
            yAxis: Number(item.value),
            lineStyle: { color: item.color, width: 1, type: 'dashed' as const },
            label: {
                show: true,
                formatter: `${item.key}: ${Number(item.value).toFixed(2)}`,
                color: item.color,
                fontSize: 11,
            },
        }))
    return {
        animation: false,
        tooltip: {
            trigger: 'axis',
            formatter: (params: any) => {
                const points = Array.isArray(params) ? params : [params]
                const point = points.find((item: any) => item?.seriesName !== '市场情绪') || points[0]
                const axisValue = String(point?.axisValue || '')
                const value = Number(rows.find((item) => item.trade_date === axisValue)?.value)
                const sentiment = sentimentByDate.get(normalizeHistoryDateKey(axisValue))
                const sentimentScore = sentiment?.score
                return [
                    axisValue,
                    `${headerMarketQuantileDialogMarketLabel.value} ${headerMarketQuantileDialogMetricLabel.value}: ${Number.isFinite(value) ? value.toFixed(2) : '-'}`,
                    `${headerMarketQuantileDialogPeriodLabel.value}分位: ${formatPercent(headerMarketQuantilePeriodPercentilePct.value)}%`,
                    `P10: ${formatMetricValue(levels.p10)}`,
                    `P50: ${formatMetricValue(levels.p50)}`,
                    `P90: ${formatMetricValue(levels.p90)}`,
                    sentimentScore === null || sentimentScore === undefined
                        ? '市场情绪: 未发布'
                        : `市场情绪: ${Number(sentimentScore).toFixed(2)} (${sentiment?.level || '-'})`,
                    `动量: ${formatMetricValue(sentiment?.momentum_score)} 热度: ${formatMetricValue(sentiment?.activity_score)} 恐慌: ${formatMetricValue(sentiment?.fear_score)}`,
                ].join('<br/>')
            },
        },
        axisPointer: {
            link: [{ xAxisIndex: [0, 1] }],
            label: { show: true },
        },
        legend: {
            top: 0,
            data: [
                headerMarketQuantileDialogMarket.value === 'shanghai' ? '上证' : `${headerMarketQuantileDialogStyleLabel.value}综合指数`,
                '市场情绪',
            ],
        },
        grid: [
            { left: 54, right: 24, top: 42, height: '48%' },
            { left: 54, right: 24, top: '66%', height: '18%' },
        ],
        dataZoom: [
            { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
            { type: 'slider', xAxisIndex: [0, 1], height: 18, bottom: 16, start: 0, end: 100 },
        ],
        xAxis: [
            {
                type: 'category',
                data: rows.map((item) => item.trade_date),
                boundaryGap: false,
                gridIndex: 0,
                axisLabel: { show: false },
                axisTick: { show: false },
            },
            {
                type: 'category',
                data: rows.map((item) => item.trade_date),
                boundaryGap: false,
                gridIndex: 1,
            },
        ],
        yAxis: [
            {
                type: 'value',
                scale: true,
                gridIndex: 0,
                axisLabel: {
                    formatter: (value: number) => Number(value).toFixed(2),
                },
            },
            {
                type: 'value',
                name: '市场情绪',
                min: 0,
                max: 100,
                gridIndex: 1,
                axisLabel: {
                    formatter: (value: number) => Number(value).toFixed(0),
                },
            },
        ],
        series: [
            ...(headerMarketQuantileDialogMarket.value === 'shanghai'
                ? [{
                    name: '上证',
                    type: 'line',
                    smooth: false,
                    symbol: 'none',
                    lineStyle: { width: 2, color: '#f97316' },
                    areaStyle: { opacity: 0.08, color: '#fdba74' },
                    data: rows.map((item) => Number(Number(item.value).toFixed(4))),
                    markLine: {
                        symbol: ['none', 'none'],
                        silent: true,
                        data: markLineData,
                    },
                }]
                : [{
                    name: `${headerMarketQuantileDialogStyleLabel.value}综合指数`,
                    type: 'line',
                    smooth: false,
                    symbol: 'none',
                    lineStyle: { width: 2.4, color: '#2563eb' },
                    areaStyle: { opacity: 0.08, color: '#93c5fd' },
                    data: rows.map((item) => Number(Number(item.value).toFixed(4))),
                    markLine: {
                        symbol: ['none', 'none'],
                        silent: true,
                        data: markLineData,
                    },
                }]),
            {
                name: '市场情绪',
                type: 'line',
                xAxisIndex: 1,
                yAxisIndex: 1,
                smooth: false,
                symbol: 'none',
                connectNulls: false,
                lineStyle: { width: 2, color: '#0f766e' },
                data: sentimentData,
                markLine: {
                    symbol: ['none', 'none'],
                    silent: true,
                    label: { formatter: '{b}', fontSize: 10 },
                    data: [
                        { name: '恐慌', yAxis: 30, lineStyle: { color: '#ef4444', type: 'dashed' } },
                        { name: '中性', yAxis: 50, lineStyle: { color: '#94a3b8', type: 'dashed' } },
                        { name: '亢奋', yAxis: 70, lineStyle: { color: '#16a34a', type: 'dashed' } },
                    ],
                },
            },
        ],
    }
})

function formatMetricValue(value: number | null | undefined): string {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return '-'
    return Number(value).toFixed(2)
}

function formatPercent(value: number | null | undefined): string {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return '-'
    return Number(value).toFixed(1)
}

function toNullableNumber(value: unknown): number | null {
    if (value === null || value === undefined || value === '') return null
    const num = Number(value)
    return Number.isFinite(num) ? num : null
}

function formatSignedPercent(value: number | null | undefined): string {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return '-'
    const num = Number(value)
    return `${num >= 0 ? '+' : ''}${num.toFixed(2)}`
}

function formatValuationStatusLabel(status: string | null | undefined): string {
    const normalized = String(status || '').trim().toLowerCase()
    if (normalized === 'under') return '低估'
    if (normalized === 'over') return '高估'
    if (normalized === 'fair') return '合理'
    return '未知'
}

function resolveHeaderSimpleValuationIndexCode(kind: 'market' | 'shanghai'): string {
    if (kind === 'shanghai') {
        return '000001.SH'
    }
    return '399300.SZ'
}

async function fetchHeaderSimpleValuation(kind: 'market' | 'shanghai') {
    if (!baseURL) {
        headerSimpleValuation.value = null
        headerSimpleValuationError.value = '未配置 baseURL'
        return
    }
    headerSimpleValuationLoading.value = true
    headerSimpleValuationError.value = ''
    try {
        const indexCode = resolveHeaderSimpleValuationIndexCode(kind)
        const resp = await axios.get(`${baseURL}/market-index/valuation-simple/`, {
            params: {
                index_code: indexCode,
                start_date: HEADER_INDEX_START_DATE,
                freq: 'D',
                band_pct: 0.1,
            },
        })
        const payload = resp?.data
        headerSimpleValuation.value = payload && typeof payload === 'object' ? payload : null
    } catch (err: any) {
        headerSimpleValuation.value = null
        headerSimpleValuationError.value = String(
            err?.response?.data?.error
            || err?.message
            || '请求失败'
        )
    } finally {
        headerSimpleValuationLoading.value = false
    }
}

function buildMarketQuantileSummaryText(
    label: string,
    asof: string,
    rows: Array<{ label: string; latestValue: number | null; fiveYearPercentilePct: number | null; tenYearPercentilePct: number | null; allHistoryPercentilePct: number | null }>,
): string {
    if (!rows.length) {
        return `${label}${asof ? `(${asof})` : ''}: 暂无数据`
    }
    const metricsText = rows
        .map((item) => `${item.label} ${formatMetricValue(item.latestValue)} 5年${formatPercent(item.fiveYearPercentilePct)}% 10年${formatPercent(item.tenYearPercentilePct)}% 全历史${formatPercent(item.allHistoryPercentilePct)}%`)
        .join(' | ')
    return `${label}${asof ? `(${asof})` : ''}(${headerMarketQuantileDialogMetricLabel.value}): ${metricsText}`
}

function buildMarketQuantileShortText(
    label: string,
    asof: string,
    rows: Array<{ label: string; latestValue: number | null; fiveYearPercentilePct: number | null; tenYearPercentilePct: number | null; allHistoryPercentilePct: number | null }>,
): string {
    const first = rows[0]
    if (!first) {
        return `${label}${asof ? `(${asof})` : ''}: 暂无数据`
    }
    const suffix = rows.length > 1 ? ' 等' : ''
    return `${label}${asof ? `(${asof})` : ''}(${headerMarketQuantileDialogMetricLabel.value}): ${first.label} ${formatMetricValue(first.latestValue)} 5年${formatPercent(first.fiveYearPercentilePct)}% 10年${formatPercent(first.tenYearPercentilePct)}% 全历史${formatPercent(first.allHistoryPercentilePct)}%${suffix}`
}

async function fetchHeaderIndexHistories() {
    if (!baseURL) {
        headerIndexHistoryMap.value = {}
        return
    }
    const nextMap: Record<string, MarketMetricSourceRow[]> = {}
    for (const indexDef of HEADER_INDEX_DEFS) {
        try {
            const resp = await axios.get(
                `${baseURL}/tushare/${encodeURIComponent(indexDef.tsCode)}/index_dailybasic/`,
                {
                    params: {
                        start_date: HEADER_INDEX_START_DATE,
                    },
                }
            )
            const rawPayload = resp?.data?.data
            const rows = Array.isArray(rawPayload)
                ? rawPayload
                : (rawPayload && typeof rawPayload === 'object' ? [rawPayload] : [])
            nextMap[indexDef.key] = rows
                .map((item: any) => ({
                    trade_date: String(item?.trade_date || '').trim(),
                    pe: Number.isFinite(Number(item?.pe)) ? Number(item.pe) : null,
                    pe_ttm: Number.isFinite(Number(item?.pe_ttm)) ? Number(item.pe_ttm) : null,
                    pb: Number.isFinite(Number(item?.pb)) ? Number(item.pb) : null,
                }))
                .filter((item: MarketMetricSourceRow) => (
                    Boolean(item.trade_date)
                    && (item.pe !== null || item.pe_ttm !== null || item.pb !== null)
                ))
                .sort((a: { trade_date: string }, b: { trade_date: string }) => a.trade_date.localeCompare(b.trade_date))
        } catch {
            nextMap[indexDef.key] = []
        }
    }
    headerIndexHistoryMap.value = nextMap
}

async function fetchHeaderMarketSentiment() {
    if (!baseURL || headerMarketSentimentRows.value.length) return
    if (headerMarketSentimentRequest) return headerMarketSentimentRequest
    headerMarketSentimentRequest = axios.get(`${baseURL}/market-sentiment/history/`, {
        params: {
            market: 'CN',
            scope: 'INDEX',
            scope_code: 'BROAD_COMPOSITE',
            engine_version: 'index_daily_v1_20260829',
            limit: 10000,
        },
    }).then((resp) => {
        const rows = Array.isArray(resp?.data?.data) ? resp.data.data : []
        headerMarketSentimentRows.value = rows.map((item: any) => ({
            trade_date: String(item?.trade_date || '').trim(),
            score: toNullableNumber(item?.score),
            level: String(item?.level || '').trim().toUpperCase(),
            status: String(item?.status || '').trim().toUpperCase(),
            momentum_score: toNullableNumber(item?.momentum_score),
            activity_score: toNullableNumber(item?.activity_score),
            fear_score: toNullableNumber(item?.fear_score),
        })).filter((item: MarketSentimentRow) => Boolean(item.trade_date))
    }).catch(() => {
        headerMarketSentimentRows.value = []
    }).finally(() => {
        headerMarketSentimentRequest = null
    })
    return headerMarketSentimentRequest
}

async function openHeaderMarketQuantileDialog(kind: 'market' | 'shanghai') {
    await Promise.all([fetchHeaderIndexHistories(), fetchHeaderMarketSentiment()])
    headerMarketQuantileDialogMarket.value = kind
    headerMarketQuantileDialogVisible.value = true
    void fetchHeaderSimpleValuation(kind)
}

watch(() => headerMarketQuantileDialogMarket.value, (kind) => {
    if (!headerMarketQuantileDialogVisible.value) {
        return
    }
    void fetchHeaderSimpleValuation(kind)
})

const loadSearchHistory = (): CorporationSuggestion[] => {
    if (typeof window === 'undefined') {
        return []
    }
    try {
        const raw = window.localStorage.getItem(SEARCH_HISTORY_KEY)
        if (!raw) {
            return []
        }
        const parsed = JSON.parse(raw)
        if (!Array.isArray(parsed)) {
            return []
        }
        return parsed
            .filter((item) => item && item.ts_code && item.name)
            .slice(0, MAX_SEARCH_HISTORY)
            .map((item) => ({
                ts_code: String(item.ts_code),
                name: String(item.name),
                listdate: item.listdate ? String(item.listdate) : '',
                __source: 'history',
            }))
    } catch {
        return []
    }
}

const saveSearchHistory = (items: CorporationSuggestion[]) => {
    searchHistory.value = items.slice(0, MAX_SEARCH_HISTORY)
    if (typeof window === 'undefined') {
        return
    }
    try {
        window.localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(searchHistory.value))
    } catch {
        // ignore localStorage failures
    }
}

const pushSearchHistory = (item: CorporationSuggestion) => {
    const normalizedCode = String(item.ts_code || '').trim().toUpperCase()
    const normalizedName = String(item.name || '').trim()
    if (!normalizedCode || !normalizedName) {
        return
    }
    const next = [
        {
            ts_code: normalizedCode,
            name: normalizedName,
            listdate: item.listdate || '',
            __source: 'history' as const,
        },
        ...searchHistory.value.filter((it) => String(it.ts_code || '').trim().toUpperCase() !== normalizedCode),
    ].slice(0, MAX_SEARCH_HISTORY)
    saveSearchHistory(next)
}

const querySearchAsync = (queryString: string, cb: (arg: any) => void) => {
    if (!queryString) {
        cb(searchHistory.value)
        return
    }
    axios.get(`${baseURL}/corporations/${encodeURIComponent(queryString)}/`)
        .then(res => {
            const rows = Array.isArray(res?.data?.data) ? res.data.data : []
            cb(rows.map((item: CorporationSuggestion) => ({ ...item, __source: 'remote' })))
        })
        .catch(() => cb([]))
}


const handleSelect = (item: Record<string, any>) => {
    state.value = item.name + ' ' + item.ts_code
    stockTradeStore.setTsCode(item.ts_code)
    stockTradeStore.setName(item.name)
    pushSearchHistory(item as CorporationSuggestion)
    console.log(item)
}

searchHistory.value = loadSearchHistory()

const focusSearchInput = () => {
    if (typeof document === 'undefined') {
        return
    }
    const input = document.querySelector('.header-search input') as HTMLInputElement | null
    if (!input) {
        return
    }
    input.focus()
    input.select()
}

const onGlobalKeydown = (event: KeyboardEvent) => {
    const isCtrlOrMeta = event.ctrlKey || event.metaKey
    if (!isCtrlOrMeta) {
        return
    }
    if (event.key.toLowerCase() !== 'k') {
        return
    }
    event.preventDefault()
    focusSearchInput()
}

onMounted(() => {
    window.addEventListener('keydown', onGlobalKeydown)
    void fetchHeaderIndexHistories()
})

onBeforeUnmount(() => {
    window.removeEventListener('keydown', onGlobalKeydown)
})

watch(() => headerMarketQuantileDialogMarket.value, () => {
    if (headerMarketQuantileDialogMarket.value === 'shanghai') {
        headerMarketQuantileDialogPeriod.value = '10Y'
    }
})

</script>

<style scoped>
.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 24px;
    background: #fff;
    height: 64px;
    box-shadow: 0 2px 10px #f0f1f2;
}

.header-left {
    display: flex;
    align-items: center;
    flex: 1;
    min-width: 0;
}

.header-nav-wrap {
    margin-left: 24px;
    min-width: 460px;
    max-width: 620px;
    width: fit-content;
}

.logo {
    height: 40px;
    margin-right: 12px;
}

.app-title {
    font-size: 14px;
    font-weight: bold;
    color: #333;
}

.header-menu {
    border-bottom: none !important;
    box-shadow: none !important;
    min-width: 460px;
    width: auto;
    /* 如果有阴影也一并去除 */
}

.header-search-wrap {
    margin-left: 8px;
    width: 180px;
    flex: 0 0 180px;
    flex-shrink: 0;
}

.header-market-quantile-wrap {
    margin-left: 10px;
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    flex: 1;
}

.header-market-quantile-chip {
    display: inline-block;
    max-width: 300px;
    border: 1px solid #dbe5f1;
    background: #f8fafc;
    border-radius: 999px;
    padding: 2px 10px;
    color: #475569;
    font-size: 12px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.header-market-quantile-chip:hover {
    border-color: #93c5fd;
    background: #eff6ff;
}

.header-market-quantile-dialog-toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
    margin-bottom: 12px;
}

.header-market-quantile-dialog-summary {
    display: flex;
    flex-wrap: wrap;
    gap: 14px;
    margin-bottom: 10px;
    font-size: 12px;
    color: #475569;
}

.header-market-quantile-chart {
    height: 500px;
}

.header-search {
    width: 100%;
}

.header-search :deep(.el-input) {
    width: 100%;
}

.header-right {
    display: flex;
    align-items: center;
    margin-left: 16px;
    flex-shrink: 0;
}

@media (max-width: 1600px) {
    .header-market-quantile-chip {
        max-width: 220px;
    }
}

.user-avatar {
    margin-right: 8px;
}

.user-name {
    font-size: 16px;
    color: #333;
}
</style>