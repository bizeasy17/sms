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
            <div class="header-market-quantile-dialog-summary" v-if="headerMarketQuantileChartRows.length">
                <span>{{ headerMarketQuantileDialogMarketLabel }} {{ headerMarketQuantileDialogMetricLabel }} 最新值 {{ formatMetricValue(headerMarketQuantileSummary.latestValue) }}</span>
                <span>日期 {{ headerMarketQuantileSummary.latestDate || headerMarketQuantileDialogAsOfText || '-' }}</span>
                <span>{{ headerMarketQuantileDialogPeriodLabel }}分位 {{ formatPercent(headerMarketQuantilePeriodPercentilePct) }}%</span>
                <span>P10 {{ formatMetricValue(headerMarketQuantileDynamicLevels.p10) }}</span>
                <span>P50 {{ formatMetricValue(headerMarketQuantileDynamicLevels.p50) }}</span>
                <span>P90 {{ formatMetricValue(headerMarketQuantileDynamicLevels.p90) }}</span>
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
const headerMarketQuantileDialogPeriod = ref<'30D' | '60D' | '90D' | '1Y' | '3Y' | '5Y' | '10Y' | 'ALL'>('5Y')

const HEADER_MARKET_METRIC_OPTIONS = [
    { key: 'pe', label: 'PE' },
    { key: 'pe_ttm', label: 'PETTM' },
    { key: 'pb', label: 'PB' },
] as const

type MarketMetricKey = 'pe' | 'pe_ttm' | 'pb'
type MarketMetricSourceRow = { trade_date: string; pe: number | null; pe_ttm: number | null; pb: number | null }

const HEADER_INDEX_DEFS = [
    { key: 'sh', label: '上证', tsCode: '000001.SH' },
    { key: 'sz', label: '深成指', tsCode: '399001.SZ' },
    { key: 'hs300', label: '沪深300', tsCode: '399300.SZ' },
    { key: 'cyb', label: '创指', tsCode: '399006.SZ' },
] as const

const HEADER_COMPOSITE_WEIGHTS: Record<'sh' | 'sz' | 'hs300' | 'cyb', number> = {
    sh: 0.30,
    sz: 0.30,
    hs300: 0.25,
    cyb: 0.15,
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

function buildCompositeRows(metricKey: MarketMetricKey): MarketHistoryRow[] {
    const shRows = getIndexRows('sh', metricKey)
    const szRows = getIndexRows('sz', metricKey)
    const hsRows = getIndexRows('hs300', metricKey)
    const cybRows = getIndexRows('cyb', metricKey)
    if (!shRows.length || !szRows.length || !hsRows.length || !cybRows.length) {
        return []
    }
    const dateSet = new Set(shRows.map((item) => item.trade_date))
    for (const date of Array.from(dateSet)) {
        if (!szRows.some((item) => item.trade_date === date)
            || !hsRows.some((item) => item.trade_date === date)
            || !cybRows.some((item) => item.trade_date === date)) {
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
    const shMap = mapByDate(shRows)
    const szMap = mapByDate(szRows)
    const hsMap = mapByDate(hsRows)
    const cybMap = mapByDate(cybRows)

    const weightSh = Number(HEADER_COMPOSITE_WEIGHTS.sh) || 0
    const weightSz = Number(HEADER_COMPOSITE_WEIGHTS.sz) || 0
    const weightHs = Number(HEADER_COMPOSITE_WEIGHTS.hs300) || 0
    const weightCyb = Number(HEADER_COMPOSITE_WEIGHTS.cyb) || 0
    const weightTotal = weightSh + weightSz + weightHs + weightCyb
    if (!(weightTotal > 0)) {
        return []
    }

    return sharedDates.map((date) => {
        const rawSh = Number(shMap.get(date) || 0)
        const rawSz = Number(szMap.get(date) || 0)
        const rawHs = Number(hsMap.get(date) || 0)
        const rawCyb = Number(cybMap.get(date) || 0)

        const weightedValues = [
            rawSh * weightSh,
            rawSz * weightSz,
            rawHs * weightHs,
            rawCyb * weightCyb,
        ]
        const arithmeticMeanOfWeighted = weightedValues.reduce((acc, item) => acc + item, 0) / weightedValues.length
        const averageWeight = weightTotal / weightedValues.length
        const composite = averageWeight > 0
            ? (arithmeticMeanOfWeighted / averageWeight)
            : 0

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

const headerMarketQuantileDialogMarketLabel = computed(() => (
    headerMarketQuantileDialogMarket.value === 'shanghai' ? '上证指数' : '综合指数'
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

const marketCompositeRows = computed(() => buildCompositeRows(headerMarketQuantileDialogMetric.value as MarketMetricKey))

const marketCompositeSummary = computed(() => buildSummaryRow('market', '综合指数', marketCompositeRows.value))
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
                const point = Array.isArray(params) ? params[0] : params
                const axisValue = String(point?.axisValue || '')
                const value = Number(point?.data)
                return [
                    axisValue,
                    `${headerMarketQuantileDialogMarketLabel.value} ${headerMarketQuantileDialogMetricLabel.value}: ${Number.isFinite(value) ? value.toFixed(2) : '-'}`,
                    `${headerMarketQuantileDialogPeriodLabel.value}分位: ${formatPercent(headerMarketQuantilePeriodPercentilePct.value)}%`,
                    `P10: ${formatMetricValue(levels.p10)}`,
                    `P50: ${formatMetricValue(levels.p50)}`,
                    `P90: ${formatMetricValue(levels.p90)}`,
                ].join('<br/>')
            },
        },
        legend: {
            top: 0,
            data: [headerMarketQuantileDialogMarket.value === 'shanghai' ? '上证' : '综合指数'],
        },
        grid: {
            left: 54,
            right: 24,
            top: 42,
            bottom: 72,
        },
        dataZoom: [
            { type: 'inside', start: 0, end: 100 },
            { type: 'slider', height: 18, bottom: 22, start: 0, end: 100 },
        ],
        xAxis: {
            type: 'category',
            data: rows.map((item) => item.trade_date),
            boundaryGap: false,
        },
        yAxis: {
            type: 'value',
            scale: true,
            axisLabel: {
                formatter: (value: number) => Number(value).toFixed(2),
            },
        },
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
                    name: '综合指数',
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

async function openHeaderMarketQuantileDialog(kind: 'market' | 'shanghai') {
    await fetchHeaderIndexHistories()
    headerMarketQuantileDialogMarket.value = kind
    headerMarketQuantileDialogVisible.value = true
}

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
    height: 420px;
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