<template>
    <el-card class="stock-chart-filter-card">
            <el-row :gutter="12" class="stock-top-row">
                <el-col :span="24">

                    <el-row :gutter="8">
                        <el-col :span="24">
                            <div class="stock-title-actions">
                                <div class="stock-title-left">
                                    <div class="stock-title-meta">
                                        <div class="stock-name-row">
                                            <el-text type="primary" tag="b">
                                                <el-link
                                                    :href="resolveCompanyWebsiteUrl(stockTradeStore.website, '')"
                                                    target="_blank"
                                                    type="primary"
                                                    class="stock-name-link"
                                                >
                                                    {{ stockTradeStore.name + ' | ' + stockTradeStore.tsCode }}
                                                </el-link>
                                            </el-text>
                                        </div>
                                        <div class="stock-top-price-line">
                                            <span>现价: {{ formatTopPrice(stockTradeStore.close) }}</span>
                                            <span style="margin-left: 6px;" :style="{ color: stockTradeStore.pctChg >= 0 ? '#cf1322' : '#389e0d' }">
                                                {{ formatTopGap(stockTradeStore.pctChg) }}%
                                            </span>
                                        </div>
                                    </div>
                                    <el-check-tag
                                        :checked="isInWatchlist"
                                        @change="toggleWatchlistStatus"
                                        class="compact-toggle-tag compact-toggle-watch"
                                    >
                                        <span class="compact-toggle-label">自选</span>
                                    </el-check-tag>
                                    <el-check-tag
                                        :checked="isHolding"
                                        @change="toggleHoldingStatus"
                                        class="compact-toggle-tag compact-toggle-hold"
                                    >
                                        <span class="compact-toggle-label">持仓</span>
                                    </el-check-tag>
                                    <el-check-tag
                                        :checked="isObserving"
                                        @change="toggleObserveStatus"
                                        class="compact-toggle-tag compact-toggle-observe"
                                    >
                                        <span class="compact-toggle-label compact-observe-label">
                                            <el-icon><View /></el-icon>
                                            <span>观察</span>
                                        </span>
                                    </el-check-tag>
                                </div>
                                <el-button size="small" plain @click="toggleRecentFinancialPanel">
                                    {{ props.showRecentReportPanel ? '隐藏最新财报' : '显示最新财报' }}
                                </el-button>
                            </div>
                        </el-col>
                        <el-col :span="24">
                            <el-row :gutter="8">
                                <el-col :span="8">
                                    <el-input v-if="inputVisible" ref="InputRef" v-model="inputValue" class="w-20" size="small"
                                        @keyup.enter="handleInputConfirm" @blur="handleInputConfirm" />
                                    <el-button v-else class="button-new-tag" size="small" @click="showInput">
                                        + 新标签
                                    </el-button>
                                </el-col>
                            </el-row>
                        </el-col>
                    </el-row>
                </el-col>
            </el-row>
            <el-row v-if="dynamicTags.length > 0" :gutter="12" class="tags-row">
                <el-col :span="24" style="text-align: left; font-size: x-small; color: gray;">
                    <el-tag v-for="tag in dynamicTags" :key="tag" closable :disable-transitions="false"
                        @close="handleClose(tag)">
                        {{ tag }}
                    </el-tag>
                </el-col>

            </el-row>
            <StockExtremeSummary />
            <el-row :gutter="12" class="valuation-quickview-row">
                <el-col :span="24">
                    <el-tabs v-model="overviewTab" class="overview-tabs">
                        <el-tab-pane label="估值一览" name="valuation">
                            <StockValuationQuickView :embedded="true" />
                        </el-tab-pane>
                        <el-tab-pane label="技术趋势" name="trend" lazy>
                            <div class="trend-tab-panel">
                                <div class="trend-overlay-toolbar">
                                    <el-radio-group v-model="trendOverlayMode" size="small">
                                        <el-radio-button label="traditional">传统估值</el-radio-button>
                                        <el-radio-button label="predictive">预测估值</el-radio-button>
                                    </el-radio-group>
                                    <el-radio-group v-if="trendOverlayMode === 'predictive'" v-model="trendOverlayReportType" size="small">
                                        <el-radio-button label="Q1">Q1</el-radio-button>
                                        <el-radio-button label="H1">H1</el-radio-button>
                                        <el-radio-button label="Q3">Q3</el-radio-button>
                                        <el-radio-button label="FY">FY</el-radio-button>
                                    </el-radio-group>
                                </div>
                                <StockChart
                                    ref="trendChartCompRef"
                                    :display-embed="true"
                                    :show-bottom-in-embed="true"
                                    :valuation-overlay-mode="trendOverlayMode"
                                    :valuation-overlay-report-type="trendOverlayReportType"
                                />
                            </div>
                        </el-tab-pane>
                        <el-tab-pane label="成本 / 财报" name="finance" lazy>
                            <div class="finance-tab-panel">
                                <FinanceRelevant />
                            </div>
                        </el-tab-pane>
                    </el-tabs>
                </el-col>
            </el-row>
            <el-dialog
                v-model="marketQuantileDialogVisible"
                width="78%"
                top="8vh"
                :title="`${marketQuantileDialogMarketLabel}趋势`"
            >
                <div class="market-quantile-dialog-toolbar">
                    <el-radio-group v-model="marketQuantileDialogMarket" size="small">
                        <el-radio-button label="market">大盘分位</el-radio-button>
                        <el-radio-button label="shanghai">上证分位</el-radio-button>
                    </el-radio-group>
                    <el-radio-group v-model="marketQuantileDialogMetric" size="small">
                        <el-radio-button
                            v-for="item in marketQuantileAvailableMetrics"
                            :key="item.key"
                            :label="item.key"
                        >
                            {{ item.label }}
                        </el-radio-button>
                    </el-radio-group>
                    <el-radio-group v-model="marketQuantileDialogPeriod" size="small">
                        <el-radio-button
                            v-for="item in MARKET_PERIOD_OPTIONS"
                            :key="item.key"
                            :label="item.key"
                        >
                            {{ item.label }}
                        </el-radio-button>
                    </el-radio-group>
                </div>
                <div class="market-quantile-dialog-summary" v-if="marketQuantileChartRows.length || marketSimpleValuationLoading || marketSimpleCompositePrice !== null || marketSimpleConservativePrice !== null || Boolean(marketSimpleValuationError)">
                    <template v-if="marketQuantileChartRows.length">
                        <span>{{ marketQuantileDialogMetricLabel }} 最新值 {{ formatMetricValue(marketQuantileSummary.latestValue) }}</span>
                        <span>日期 {{ marketQuantileSummary.latestDate || marketQuantileDialogAsOfText || '-' }}</span>
                        <span>90分位 {{ formatMetricValue(marketQuantileSummary.q90) }}</span>
                        <span>50分位 {{ formatMetricValue(marketQuantileSummary.q50) }}</span>
                        <span>10分位 {{ formatMetricValue(marketQuantileSummary.q10) }}</span>
                    </template>
                    <span v-if="marketSimpleValuationLoading">简化估值计算中...</span>
                    <span v-if="!marketSimpleValuationLoading && marketSimpleValuationError">简化估值不可用：{{ marketSimpleValuationError }}</span>
                    <span v-else-if="marketSimpleCompositePrice !== null">
                        组合估值 {{ formatMetricValue(marketSimpleCompositePrice) }} ({{ formatValuationStatusLabel(marketSimpleCompositeStatus) }} {{ formatSignedPercent(marketSimpleCompositeGapPct) }}%)
                    </span>
                    <span v-if="!marketSimpleValuationLoading && marketSimpleConservativePrice !== null">
                        保守估值 {{ formatMetricValue(marketSimpleConservativePrice) }} ({{ formatValuationStatusLabel(marketSimpleConservativeStatus) }} {{ formatSignedPercent(marketSimpleConservativeGapPct) }}%)
                    </span>
                </div>
                <v-chart v-if="marketQuantileChartOption" :option="marketQuantileChartOption" autoresize class="market-quantile-chart" />
                <el-empty v-else description="当前市场没有可展示的分位历史" />
            </el-dialog>
    </el-card>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
// Element Plus
import type { InputInstance } from 'element-plus';
import { ElMessage, ElRow, ElCol, ElCard, ElText, ElCheckTag, ElButton, ElTag, ElInput, ElLink, ElTabs, ElTabPane, ElIcon, ElDialog, ElRadioGroup, ElRadioButton, ElEmpty } from 'element-plus';
import { View } from '@element-plus/icons-vue';
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { TooltipComponent, GridComponent, DataZoomComponent, LegendComponent, MarkLineComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { useStockTradeStore } from '../stores/stockTradeStore';
import StockValuationQuickView from './StockValuationQuickView.vue';
import FinanceRelevant from './FinanceRelevant.vue';
import StockChart from './StockChart.vue';
import StockExtremeSummary from './StockExtremeSummary.vue';
import axios from 'axios';
import { inject } from 'vue';
import { fetchValuationMethodsWithSharedCache } from '../utils/valuationQuickViewCache';
import { resolveCompanyWebsiteUrl } from '../utils/companyWebsite';

use([CanvasRenderer, LineChart, TooltipComponent, GridComponent, DataZoomComponent, LegendComponent, MarkLineComponent])

const stockTradeStore = useStockTradeStore();

const props = withDefaults(
    defineProps<{
        showRecentReportPanel?: boolean
    }>(),
    {
        showRecentReportPanel: true,
    },
)

const emit = defineEmits<{
    (e: 'toggle-recent-report-panel'): void
}>()

const isHolding = ref(false);
const isInWatchlist = ref(false);
const isObserving = ref(false);

const inputValue = ref('')
const dynamicTags = ref<string[]>([])
const inputVisible = ref(false)
const InputRef = ref<InputInstance>()
const overviewTab = ref('valuation')
const trendChartCompRef = ref<InstanceType<typeof StockChart> | null>(null)
const trendOverlayMode = ref<'traditional' | 'predictive'>('traditional')
const trendOverlayReportType = ref<'Q1' | 'H1' | 'Q3' | 'FY'>('FY')
const marketOverallValuation = ref<any | null>(null)
const topQuoteFetchSeq = ref(0)
const marketQuantileDialogVisible = ref(false)
const marketQuantileDialogMarket = ref<'market' | 'shanghai'>('market')
const marketQuantileDialogMetric = ref<'pe' | 'pe_ttm' | 'pb'>('pe')
const marketQuantileDialogPeriod = ref<'30D' | '90D' | '1Y' | '3Y' | '5Y' | '10Y' | 'ALL'>('5Y')
const marketSimpleValuation = ref<any | null>(null)
const marketSimpleValuationLoading = ref(false)
const marketSimpleValuationError = ref('')

const baseURL = inject<string>('baseURL', '');

const MARKET_METRIC_OPTIONS = [
    { key: 'pe', label: 'PE' },
    { key: 'pe_ttm', label: 'PETTM' },
    { key: 'pb', label: 'PB' },
] as const

const MARKET_PERIOD_OPTIONS = [
    { key: '30D', label: '30D' },
    { key: '60D', label: '60D' },
    { key: '90D', label: '90D' },
    { key: '1Y', label: '1Y' },
    { key: '3Y', label: '3Y' },
    { key: '5Y', label: '5Y' },
    { key: '10Y', label: '10Y' },
    { key: 'ALL', label: '所有' },
] as const

const marketOverallAsOfText = computed(() => String(marketOverallValuation.value?.asof_trade_date || '').trim())

const shBenchmarkAsOfText = computed(() =>
    String(marketOverallValuation.value?.shanghai_benchmark?.asof_trade_date || '').trim()
)

const marketOverallMetricRows = computed(() => {
    const metrics = marketOverallValuation.value?.metrics
    if (!metrics || typeof metrics !== 'object') return []
    const rows = [
        { key: 'pe', label: 'PE', payload: metrics.pe },
        { key: 'pe_ttm', label: 'PETTM', payload: metrics.pe_ttm },
        { key: 'pb', label: 'PB', payload: metrics.pb },
    ]
    return rows
        .filter((item) => item.payload)
        .map((item) => ({
            key: item.key,
            label: item.label,
            current: toNullableNumber(item.payload?.current),
            historyPercentilePct: toNullableNumber(item.payload?.history_percentile_pct),
            fiveYearPercentilePct: toNullableNumber(item.payload?.five_year_percentile_pct),
        }))
})

const shBenchmarkMetricRows = computed(() => {
    const metrics = marketOverallValuation.value?.shanghai_benchmark?.metrics
    if (!metrics || typeof metrics !== 'object') return []
    const rows = [
        { key: 'pe', label: 'PE', payload: metrics.pe },
        { key: 'pe_ttm', label: 'PETTM', payload: metrics.pe_ttm },
        { key: 'pb', label: 'PB', payload: metrics.pb },
    ]
    return rows
        .filter((item) => item.payload)
        .map((item) => ({
            key: item.key,
            label: item.label,
            current: toNullableNumber(item.payload?.current),
            historyPercentilePct: toNullableNumber(item.payload?.history_percentile_pct),
            fiveYearPercentilePct: toNullableNumber(item.payload?.five_year_percentile_pct),
        }))
})

type MarketHistoryRow = {
    trade_date: string
    value: number
}

function getMarketSourcePayload(kind: 'market' | 'shanghai') {
    if (kind === 'shanghai') {
        return marketOverallValuation.value?.shanghai_benchmark || null
    }
    return marketOverallValuation.value || null
}

function getMetricHistory(kind: 'market' | 'shanghai', metricKey: 'pe' | 'pe_ttm' | 'pb'): MarketHistoryRow[] {
    const payload = getMarketSourcePayload(kind)
    const history = payload?.metrics?.[metricKey]?.history
    if (!Array.isArray(history)) return []
    return history
        .map((item) => ({
            trade_date: String(item?.trade_date || '').trim(),
            value: toNullableNumber(item?.value),
        }))
        .filter((item): item is MarketHistoryRow => Boolean(item.trade_date) && item.value !== null)
}

const marketQuantileAvailableMetrics = computed(() => (
    MARKET_METRIC_OPTIONS.filter((item) => getMetricHistory(marketQuantileDialogMarket.value, item.key).length > 0)
))

const marketQuantileDialogMarketLabel = computed(() => (
    marketQuantileDialogMarket.value === 'shanghai' ? '上证分位' : '大盘分位'
))

const marketQuantileDialogMetricLabel = computed(() => (
    MARKET_METRIC_OPTIONS.find((item) => item.key === marketQuantileDialogMetric.value)?.label || 'PE'
))

const marketQuantileDialogAsOfText = computed(() => {
    const payload = getMarketSourcePayload(marketQuantileDialogMarket.value)
    return String(payload?.asof_trade_date || '').trim()
})

function alignMetricSelection() {
    if (marketQuantileAvailableMetrics.value.some((item) => item.key === marketQuantileDialogMetric.value)) {
        return
    }
    marketQuantileDialogMetric.value = marketQuantileAvailableMetrics.value[0]?.key || 'pe'
}

watch(() => marketQuantileDialogMarket.value, () => {
    alignMetricSelection()
    if (!marketQuantileDialogVisible.value) {
        return
    }
    void fetchMarketSimpleValuation(marketQuantileDialogMarket.value)
})

watch(() => marketOverallValuation.value, () => {
    alignMetricSelection()
})

async function openMarketQuantileDialog(kind: 'market' | 'shanghai') {
    if (!marketOverallMetricRows.value.length && !shBenchmarkMetricRows.value.length) {
        await fetchMarketOverallValuation(stockTradeStore.tsCode || '')
    }
    marketQuantileDialogMarket.value = kind
    alignMetricSelection()
    marketQuantileDialogVisible.value = true
    void fetchMarketSimpleValuation(kind)
}

function resolveSimpleValuationIndexCode(kind: 'market' | 'shanghai'): string {
    if (kind === 'shanghai') {
        return '000001.SH'
    }
    return '399300.SZ'
}

async function fetchMarketSimpleValuation(kind: 'market' | 'shanghai') {
    if (!baseURL) {
        marketSimpleValuation.value = null
        marketSimpleValuationError.value = '未配置 baseURL'
        return
    }
    marketSimpleValuationLoading.value = true
    marketSimpleValuationError.value = ''
    try {
        const indexCode = resolveSimpleValuationIndexCode(kind)
        const resp = await axios.get(`${baseURL}/market-index/valuation-simple/`, {
            params: {
                index_code: indexCode,
                start_date: '20040101',
                freq: 'D',
                band_pct: 0.1,
            },
        })
        const payload = resp?.data
        marketSimpleValuation.value = payload && typeof payload === 'object' ? payload : null
    } catch (err: any) {
        marketSimpleValuation.value = null
        marketSimpleValuationError.value = String(
            err?.response?.data?.error
            || err?.message
            || '请求失败'
        )
    } finally {
        marketSimpleValuationLoading.value = false
    }
}

function onOpenMarketQuantileChartDialog(event: Event) {
    const customEvent = event as CustomEvent<{ kind?: 'market' | 'shanghai' }>
    const kind = customEvent?.detail?.kind === 'shanghai' ? 'shanghai' : 'market'
    void openMarketQuantileDialog(kind)
}

function parseHistoryDate(value: string): Date | null {
    const parsed = new Date(`${String(value || '').trim()}T00:00:00`)
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
    if (period === '30D') {
        cutoff.setDate(cutoff.getDate() - 30)
    } else if (period === '60D') {
        cutoff.setDate(cutoff.getDate() - 60)
    } else if (period === '90D') {
        cutoff.setDate(cutoff.getDate() - 90)
    } else if (period === '1Y') {
        cutoff.setFullYear(cutoff.getFullYear() - 1)
    } else if (period === '3Y') {
        cutoff.setFullYear(cutoff.getFullYear() - 3)
    } else if (period === '5Y') {
        cutoff.setFullYear(cutoff.getFullYear() - 5)
    } else if (period === '10Y') {
        cutoff.setFullYear(cutoff.getFullYear() - 10)
    }
    return rows.filter((item) => {
        const tradeDate = parseHistoryDate(item.trade_date)
        return tradeDate ? tradeDate >= cutoff : false
    })
}

function computeQuantileValue(rows: MarketHistoryRow[], quantile: number): number | null {
    const values = rows
        .map((item) => Number(item.value))
        .filter((value) => Number.isFinite(value))
        .sort((a, b) => a - b)
    if (!values.length) return null
    if (values.length === 1) return Number(values[0].toFixed(4))
    const position = (values.length - 1) * quantile
    const lowerIndex = Math.floor(position)
    const upperIndex = Math.ceil(position)
    const lowerValue = values[lowerIndex]
    const upperValue = values[upperIndex]
    if (lowerIndex === upperIndex) return Number(lowerValue.toFixed(4))
    const ratio = position - lowerIndex
    return Number((lowerValue + (upperValue - lowerValue) * ratio).toFixed(4))
}

const marketQuantileChartRows = computed(() => {
    const rows = getMetricHistory(marketQuantileDialogMarket.value, marketQuantileDialogMetric.value)
    return filterHistoryRowsByPeriod(rows, marketQuantileDialogPeriod.value)
})

const marketQuantileSummary = computed(() => {
    const rows = marketQuantileChartRows.value
    const latest = rows[rows.length - 1] || null
    return {
        latestValue: latest ? Number(Number(latest.value).toFixed(4)) : null,
        latestDate: latest?.trade_date || marketQuantileDialogAsOfText.value || '',
        q90: computeQuantileValue(rows, 0.9),
        q50: computeQuantileValue(rows, 0.5),
        q10: computeQuantileValue(rows, 0.1),
    }
})

const marketSimpleSummary = computed(() => {
    const summary = marketSimpleValuation.value?.summary
    return summary && typeof summary === 'object' ? summary : null
})

const marketSimpleCompositePrice = computed(() => toNullableNumber(marketSimpleSummary.value?.composite_valuation_price))
const marketSimpleCompositeStatus = computed(() => String(marketSimpleSummary.value?.composite_valuation_status || '').trim().toLowerCase())
const marketSimpleCompositeGapPct = computed(() => toNullableNumber(marketSimpleSummary.value?.composite_valuation_gap_pct))
const marketSimpleConservativePrice = computed(() => toNullableNumber(marketSimpleSummary.value?.conservative_valuation_price))
const marketSimpleConservativeStatus = computed(() => String(marketSimpleSummary.value?.conservative_valuation_status || '').trim().toLowerCase())
const marketSimpleConservativeGapPct = computed(() => toNullableNumber(marketSimpleSummary.value?.conservative_valuation_gap_pct))

const marketQuantileChartOption = computed(() => {
    const rows = marketQuantileChartRows.value
    if (!rows.length) return null
    const summary = marketQuantileSummary.value
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
                    `${marketQuantileDialogMetricLabel.value}: ${Number.isFinite(value) ? value.toFixed(2) : '-'}`,
                    `90分位: ${formatMetricValue(summary.q90)}`,
                    `50分位: ${formatMetricValue(summary.q50)}`,
                    `10分位: ${formatMetricValue(summary.q10)}`,
                ].join('<br/>')
            },
        },
        legend: {
            top: 0,
            data: [marketQuantileDialogMetricLabel.value],
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
            {
                name: marketQuantileDialogMetricLabel.value,
                type: 'line',
                smooth: false,
                symbol: 'none',
                lineStyle: {
                    width: 2,
                    color: marketQuantileDialogMarket.value === 'shanghai' ? '#f97316' : '#2563eb',
                },
                areaStyle: {
                    opacity: 0.08,
                    color: marketQuantileDialogMarket.value === 'shanghai' ? '#fdba74' : '#93c5fd',
                },
                data: rows.map((item) => Number(Number(item.value).toFixed(4))),
                markLine: {
                    symbol: 'none',
                    label: {
                        formatter: ({ name, value }: { name?: string, value?: number }) => `${name || ''} ${formatMetricValue(value)}`,
                    },
                    lineStyle: {
                        type: 'dashed',
                        width: 1.2,
                    },
                    data: [
                        { name: '90分位', yAxis: summary.q90 },
                        { name: '50分位', yAxis: summary.q50 },
                        { name: '10分位', yAxis: summary.q10 },
                    ].filter((item) => item.yAxis !== null),
                },
            },
        ],
    }
})

function toNullableNumber(value: unknown): number | null {
    if (value === null || value === undefined || value === '') return null
    const num = Number(value)
    return Number.isFinite(num) ? num : null
}

function formatMetricValue(value: number | null | undefined): string {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return '-'
    return Number(value).toFixed(2)
}

function formatPercent(value: number | null | undefined): string {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return '-'
    return Number(value).toFixed(1)
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

function formatTopPrice(value: number | null | undefined): string {
    const num = Number(value)
    if (!Number.isFinite(num) || num <= 0) return '-'
    return num.toFixed(2)
}

function formatTopGap(value: number | null | undefined): string {
    const num = Number(value)
    if (!Number.isFinite(num)) return '-'
    return (num >= 0 ? '+' : '') + num.toFixed(2)
}

async function fetchTopQuote(tsCode: string) {
    const normalized = String(tsCode || '').trim().toUpperCase()
    const requestSeq = ++topQuoteFetchSeq.value
    if (!baseURL || !normalized) {
        return
    }
    const candidates = buildTsCodeCandidates(normalized)
    for (const candidate of candidates) {
        try {
            const res = await axios.get(`${baseURL}/stocks/${candidate}/trading-history/D/qfq/2/`)
            const rows = Array.isArray(res.data?.data) ? res.data.data : []
            const latest = rows.length ? rows[rows.length - 1] : null
            if (!latest || requestSeq !== topQuoteFetchSeq.value) {
                continue
            }
            if (normalized !== String(stockTradeStore.tsCode || '').trim().toUpperCase()) {
                return
            }
            const closeNum = Number(latest.close)
            const pctNum = Number(latest.pct_chg)
            if (Number.isFinite(closeNum)) {
                stockTradeStore.setClose(closeNum)
            }
            if (Number.isFinite(pctNum)) {
                stockTradeStore.setPctChg(pctNum)
            }
            return
        } catch {
            continue
        }
    }
}

async function fetchMarketOverallValuation(tsCode: string = '') {
    const normalized = String(tsCode || '').trim().toUpperCase()
    if (!baseURL) {
        marketOverallValuation.value = null
        return
    }

    const fallbackCandidates = ['000001.SH', '399001.SZ', '399006.SZ']
    const canonical = toCanonicalTsCode(normalized)
    const primaryCandidate = canonical || normalized
    const candidates = primaryCandidate
        ? [primaryCandidate]
        : fallbackCandidates

    for (const candidate of candidates) {
        try {
            const payload = await fetchValuationMethodsWithSharedCache(baseURL, candidate, '0.1', '', '')
            const marketOverall = payload?.market_overall_valuation
            if (marketOverall && typeof marketOverall === 'object') {
                marketOverallValuation.value = marketOverall
                return
            }
        } catch {
            continue
        }
    }
    marketOverallValuation.value = null
}

watch(
    () => overviewTab.value,
    (tab) => {
        if (tab !== 'trend') {
            return
        }
        nextTick(() => {
            trendChartCompRef.value?.refreshTrendLayout?.()
        })
    }
)

function toCanonicalTsCode(code: string): string {
    const normalized = String(code || '').trim().toUpperCase();
    if (!normalized) return '';
    if (normalized.includes('.')) return normalized;
    if (!/^\d{6}$/.test(normalized)) return normalized;
    if (normalized.startsWith('6') || normalized.startsWith('5') || normalized.startsWith('9')) return `${normalized}.SH`;
    if (normalized.startsWith('8') || normalized.startsWith('4')) return `${normalized}.BJ`;
    return `${normalized}.SZ`;
}

function buildTsCodeCandidates(code: string): string[] {
    const normalized = String(code || '').trim().toUpperCase();
    const base = normalized.split('.')[0];
    const candidateSet = new Set<string>();
    if (normalized) candidateSet.add(normalized);
    if (base) candidateSet.add(base);
    const canonical = toCanonicalTsCode(normalized);
    if (canonical) candidateSet.add(canonical);
    if (base && /^\d{6}$/.test(base)) {
        candidateSet.add(`${base}.SH`);
        candidateSet.add(`${base}.SZ`);
        candidateSet.add(`${base}.BJ`);
    }
    return Array.from(candidateSet);
}

const stockStatusPending = new Map<string, Promise<any>>()

async function fetchStockStatus(tsCode: string) {
    if (!baseURL || !tsCode) return;
    const canonicalTsCode = toCanonicalTsCode(tsCode)
    const requestTsCode = canonicalTsCode || String(tsCode || '').trim().toUpperCase()
    if (!requestTsCode) return

    try {
        const pending = stockStatusPending.get(requestTsCode)
        const task = pending || axios
            .get(`${baseURL}/watchlist/check/${requestTsCode}/`)
            .then((res) => res?.data)
            .finally(() => {
                stockStatusPending.delete(requestTsCode)
            })

        if (!pending) {
            stockStatusPending.set(requestTsCode, task)
        }

        const payload = await task
        if (payload && typeof payload === 'object') {
            isHolding.value = !!payload.hold_position;
            isInWatchlist.value = !!payload.in_watchlist;
            isObserving.value = !!payload.observe_status;
        }
    } catch (error) {
        console.error('Failed to fetch stock status:', error);
    }
}

async function toggleWatchlistStatus(watchlist: boolean) {
    try {
        let res;
        if (watchlist) {
            const url = `${baseURL}/watchlist/add/${stockTradeStore.tsCode}/`;
            res = await axios.post(url);
        } else {
            const url = `${baseURL}/watchlist/delete/${stockTradeStore.tsCode}/`;
            res = await axios.put(url);
        }
        if (res.status === 200) {
            isInWatchlist.value = !!res.data.in_watchlist;
            isHolding.value = !!res.data.hold_position;
            isObserving.value = !!res.data.observe_status;
            ElMessage.success(isInWatchlist.value ? '已加入自选股' : '已移除自选股');
        }
    } catch (error) {
        console.error('Failed to toggle watchlist status:', error);
        ElMessage.error('操作失败，请稍后重试');
    }
}

async function toggleHoldingStatus(hold: boolean) {
    try {
        const url = hold
            ? `${baseURL}/watchlist/hold/${stockTradeStore.tsCode}/`
            : `${baseURL}/watchlist/unhold/${stockTradeStore.tsCode}/`;
        const method = hold ? 'post' : 'put';
        const res = await axios({ url, method });
        if (res.status === 200) {
            isHolding.value = hold;
            isInWatchlist.value = res.data.in_watchlist; // 持仓后自动加入自选股，否则移除
            isObserving.value = !!res.data.observe_status;
            ElMessage.success(isHolding.value ? '已标记为持仓' : '已取消持仓标记');
        }
    } catch (error) {
        console.error('Failed to toggle holding status:', error);
        ElMessage.error('操作失败，请稍后重试');
    }
}

async function toggleObserveStatus(observe: boolean) {
    try {
        const url = observe
            ? `${baseURL}/watchlist/observe/${stockTradeStore.tsCode}/`
            : `${baseURL}/watchlist/unobserve/${stockTradeStore.tsCode}/`;
        const method = observe ? 'post' : 'put';
        const res = await axios({ url, method });
        if (res.status === 200) {
            isObserving.value = !!res.data.observe_status;
            isHolding.value = !!res.data.hold_position;
            isInWatchlist.value = !!res.data.in_watchlist;
            ElMessage.success(isObserving.value ? '已标记为观察' : '已取消观察');
        }
    } catch (error) {
        console.error('Failed to toggle observe status:', error);
        ElMessage.error('操作失败，请稍后重试');
    }
}

async function fetchStockTags(tsCode: string) {
    try {
        const res = await axios.get(`${baseURL}/tags/${tsCode}/`);
        if (Array.isArray(res.data.tags)) {
            dynamicTags.value = res.data.tags;
        }
    } catch (error) {
        console.error('Failed to fetch stock tags:', error);
    }
}


async function addStockTag(tsCode: string, tag: string) {
    try {
        const url = `${baseURL}/tags/add/${tsCode}/${encodeURIComponent(tag)}/`;
        const res = await axios.post(url);
        if (res.status === 200) {
            dynamicTags.value.push(tag);
            ElMessage.success('已添加标签');
        }
    } catch (error) {
        console.error('Failed to add stock tag:', error);
        ElMessage.error('添加标签失败，可能标签已存在');
    }
}

async function deleteStockTag(tsCode: string, tag: string) {
    try {
        const url = `${baseURL}/tags/delete/${tsCode}/${encodeURIComponent(tag)}/`;
        const res = await axios.delete(url);
        if (res.status === 200) {
            dynamicTags.value = dynamicTags.value.filter((t) => t !== tag);
            // dynamicTags.value.splice(dynamicTags.value.indexOf(tag), 1);
            ElMessage.success('已删除标签');
        }
    } catch (error) {
        console.error('Failed to delete stock tag:', error);
        ElMessage.error('删除标签失败，请稍后重试');
    }
}


const handleClose = (tag: string) => {
    deleteStockTag(stockTradeStore.tsCode, tag);
}

const showInput = () => {
    inputVisible.value = true;
    nextTick(() => {
        InputRef.value!.input!.focus()
    })
}

const handleInputConfirm = () => {
    addStockTag(stockTradeStore.tsCode, inputValue.value);
    inputVisible.value = false
    inputValue.value = ''
}

function toggleRecentFinancialPanel() {
    emit('toggle-recent-report-panel')
}

onMounted(() => {
    if (stockTradeStore.tsCode) {
        fetchStockStatus(stockTradeStore.tsCode);
        fetchStockTags(stockTradeStore.tsCode);
        fetchMarketOverallValuation(stockTradeStore.tsCode);
        fetchTopQuote(stockTradeStore.tsCode);
    } else {
        fetchMarketOverallValuation('');
    }
    if (typeof window !== 'undefined') {
        window.addEventListener('smartinvestor:openMarketQuantileChartDialog', onOpenMarketQuantileChartDialog as EventListener)
    }
});

onBeforeUnmount(() => {
    if (typeof window !== 'undefined') {
        window.removeEventListener('smartinvestor:openMarketQuantileChartDialog', onOpenMarketQuantileChartDialog as EventListener)
    }
})

watch(
    () => stockTradeStore.tsCode,
    (newTsCode) => {
        topQuoteFetchSeq.value += 1
        if (newTsCode) {
            fetchStockStatus(newTsCode);
            fetchStockTags(newTsCode);
            fetchMarketOverallValuation(newTsCode);
            fetchTopQuote(newTsCode);
        } else {
            fetchMarketOverallValuation('')
        }
    }
);

watch(
    () => stockTradeStore.marketQuantileDialogRequestId,
    () => {
        const kind = stockTradeStore.marketQuantileDialogRequestKind === 'shanghai' ? 'shanghai' : 'market'
        openMarketQuantileDialog(kind)
    }
)

defineOptions({
    name: 'StockChartFilter'
});
</script>

<style scoped>
.stock-title-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
}

.stock-title-left {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    min-width: 0;
}

.stock-title-meta {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
}

.stock-name-row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    min-width: 0;
}

.stock-top-price-line {
    font-size: 12px;
    color: #606266;
    line-height: 1.2;
}

.stock-name-link {
    font-size: 14px;
    font-weight: bold;
}

.stock-top-row {
    align-items: stretch;
}

.compact-toggle-tag {
    border-radius: 999px;
    border: 1px solid #d0d7de;
    background: #ffffff;
    padding: 2px 10px;
    line-height: 1.15;
    color: #475569;
    transition: all 0.2s ease;
}

.compact-toggle-tag:hover {
    border-color: #94a3b8;
}

.compact-toggle-tag.is-checked.compact-toggle-watch {
    background: #fff1f2;
    border-color: #fb7185;
    color: #be123c;
}

.compact-toggle-tag.is-checked.compact-toggle-hold {
    background: #eff6ff;
    border-color: #60a5fa;
    color: #1d4ed8;
}

.compact-toggle-tag.is-checked.compact-toggle-observe {
    background: #ecfdf3;
    border-color: #34d399;
    color: #047857;
}

.compact-observe-label {
    display: inline-flex;
    align-items: center;
    gap: 4px;
}

.compact-toggle-label {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.2px;
}

.tags-row {
    margin-top: 4px;
}

.valuation-quickview-row {
    margin-top: 10px;
}

.trend-overlay-toolbar {
    display: flex;
    gap: 8px;
    align-items: center;
    margin-bottom: 8px;
    flex-wrap: wrap;
}

.market-quantile-dialog-toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
    margin-bottom: 12px;
}

.finance-tab-panel :deep(.finance-card .el-card__header),
.finance-tab-panel :deep(.finance-card .el-card__footer) {
    padding-left: 0;
    padding-right: 0;
}

.finance-tab-panel :deep(.finance-card .el-card__body) {
    padding: 0 8px 8px;
}

.finance-tab-panel :deep(.finance-card .el-scrollbar__wrap) {
    overflow-x: hidden !important;
}
</style>