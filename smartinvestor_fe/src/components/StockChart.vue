<template>
    <div class="stock-chart-container">
        <el-row style="width: 100%;">
            <el-col :span="24">
                <slot name="top">
                    <!-- Adj Price Option -->
                    <!-- <el-affix :offset="75"> -->
                    <el-card shadow="always">
                        <el-row :gutter="20">
                            <el-col :span="8">
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <el-link
                                        :href="stockStore.website.startsWith('http') ? stockStore.website : 'https://' + stockStore.website"
                                        target="_blank" type="primary" style="font-size: 12px;">{{ stockStore.name + ' | ' +
                                        stockStore.tsCode }}
                                    </el-link>
                                    <el-check-tag
                                        v-if="displayEmbed"
                                        :checked="isInWatchlist"
                                        @change="toggleWatchlistStatus"
                                        type="danger"
                                    >
                                        <el-text size="small">自</el-text>
                                    </el-check-tag>
                                    <el-check-tag
                                        v-if="displayEmbed"
                                        :checked="isHolding"
                                        @change="toggleHoldingStatus"
                                        type="primary"
                                    >
                                        <el-text size="small">持</el-text>
                                    </el-check-tag>
                                </div>
                            </el-col>
                            <el-col :span="6">

                                <el-radio-group v-model="selectedPeriodEmbed" size="small" style="float: right;"
                                    v-if="displayEmbed">
                                    <el-radio-button label="30">30</el-radio-button>
                                    <el-radio-button label="60">60</el-radio-button>
                                    <el-radio-button label="200">1y</el-radio-button>
                                    <el-radio-button label="400">2y</el-radio-button>
                                </el-radio-group>

                            </el-col>
                            <el-col :span="4">

                                <el-radio-group v-model="selectedFreqEmbed" size="small" style="float: right;"
                                    v-if="displayEmbed">
                                    <el-radio-button label="D">日</el-radio-button>
                                    <el-radio-button label="W">周</el-radio-button>
                                    <el-radio-button label="M">月</el-radio-button>
                                </el-radio-group>

                            </el-col>
                            <el-col :span="6">
                                <el-radio-group v-model="adjPriceOption" size="small" style="float: right;">
                                    <el-radio-button label="qfq">前</el-radio-button>
                                    <el-radio-button label="hfq">后</el-radio-button>
                                    <el-radio-button label="bfq">不</el-radio-button>
                                </el-radio-group>
                            </el-col>
                        </el-row>
                        <el-row :gutter="16">
                            <el-col :span="16">
                                <el-skeleton :loading="trendChartsLoading" animated>
                                    <template #template>
                                        <el-skeleton-item variant="image" class="chart-skeleton chart-skeleton-400" />
                                    </template>
                                    <v-chart ref="trendChartRef" :option="chartTrendOption" style="height:400px;" />
                                </el-skeleton>
                            </el-col>
                            <el-col :span="8">
                                <div class="chip-metrics-row">
                                    <span>获胜率: {{ chipWinRateText }}</span>
                                    <span>筹码集中率: {{ chipConcentrationRateText }}</span>
                                    <span>当前价格: {{ chipCurrentPriceText }}</span>
                                </div>
                                <el-skeleton :loading="trendChartsLoading" animated>
                                    <template #template>
                                        <el-skeleton-item variant="image" class="chart-skeleton chart-skeleton-400" />
                                    </template>
                                    <v-chart ref="chipChartRef" :option="chartChipOption" style="height:400px;" />
                                </el-skeleton>
                            </el-col>
                        </el-row>
                    </el-card>
                    <!-- </el-affix> -->
                </slot>
                <div v-if="displayEmbed && shouldShowBottom" style="margin-top: 8px; text-align: right;">
                    <el-button size="small" @click="bottomFundamentalsExpanded = !bottomFundamentalsExpanded">
                        {{ bottomFundamentalsExpanded ? '收起基本面图' : '展开基本面图' }}
                    </el-button>
                </div>
                <div v-if="shouldRenderBottom" class="fundamental-section">
                    <slot name="bottom">
                    <el-row :gutter="20" style="margin-top: 16px;">
                        <el-col :span="12">
                            <el-card shadow="always">
                                <v-chart ref="peChartRef" :option="chartPeOption" style="height:200px;" />
                            </el-card>
                        </el-col>
                        <el-col :span="12">
                            <el-card shadow="always">
                                <v-chart ref="peTTMChartRef" :option="chartPeTTMOption"
                                    style="height:200px;" />
                            </el-card>
                        </el-col>
                    </el-row>
                    <el-row :gutter="20" style="margin-top: 16px;">
                        <el-col :span="12">
                            <el-card shadow="always">
                                <v-chart ref="psChartRef" :option="chartPsOption" style="height:200px;" />
                            </el-card>
                        </el-col>
                        <el-col :span="12">
                            <el-card shadow="always">
                                <v-chart ref="psTTMChartRef" :option="chartPsTTMOption"
                                    style="height:200px;" />
                            </el-card>
                        </el-col>
                    </el-row>
                    <el-row :gutter="20" style="margin-top: 16px;">
                        <el-col :span="12">
                            <el-card shadow="always">
                                <v-chart ref="pbChartRef" :option="chartPbOption" style="height:200px;" />
                            </el-card>
                        </el-col>
                        <el-col :span="12">
                            <el-card shadow="always">
                                <v-chart ref="volRatioChartRef" :option="chartVolRatioOption"
                                    style="height:200px;" />
                            </el-card>
                        </el-col>
                    </el-row>
                    <el-row :gutter="20" style="margin-top: 16px;">
                        <el-col :span="12">
                            <el-card shadow="always">
                                <v-chart ref="turnoverChartRef" :option="chartTurnoverOption"
                                    style="height:200px;" />
                            </el-card>
                        </el-col>
                        <el-col :span="12">
                            <el-card shadow="always">
                                <v-chart ref="turnoverFChartRef" :option="chartTurnoverFOption"
                                    style="height:200px;" />
                            </el-card>
                        </el-col>
                    </el-row>
                    </slot>
                </div>
            </el-col>
        </el-row>
    </div>

</template>

<script setup>
import { onMounted, onBeforeUnmount, ref, computed, nextTick } from 'vue'
// Element Plus 组件
import { ElAffix, ElCard, ElRadioGroup, ElRadioButton, ElCol, ElRow, ElButton, ElLink, ElCheckTag, ElText, ElMessage, ElSkeleton, ElSkeletonItem } from 'element-plus'
// ECharts 相关 组件
import * as echarts from 'echarts'
import { use } from 'echarts/core'
import VChart from 'vue-echarts'
//导入Canvas渲染器
// import { CanvasRenderer } from 'echarts/renderers'
// import { TitleComponent } from 'echarts/components';
// import { TooltipComponent } from 'echarts/components'

// import the datastore
import { useStockTradeStore } from '../stores/stockTradeStore'
import { useStockChartFilterStore } from '../stores/stockChartFilterStore'

import axios from 'axios'
import { inject } from 'vue'

const baseURL = inject('baseURL')

const stockStore = useStockTradeStore();
const stockChartFilterStore = useStockChartFilterStore();
const isHolding = ref(false);
const isInWatchlist = ref(false);

function toCanonicalTsCode(code) {
    const normalized = String(code || '').trim().toUpperCase();
    if (!normalized) return '';
    if (normalized.includes('.')) return normalized;
    if (!/^\d{6}$/.test(normalized)) return normalized;
    if (normalized.startsWith('6') || normalized.startsWith('5') || normalized.startsWith('9')) return `${normalized}.SH`;
    if (normalized.startsWith('8') || normalized.startsWith('4')) return `${normalized}.BJ`;
    return `${normalized}.SZ`;
}

function buildTsCodeCandidates(code) {
    const normalized = String(code || '').trim().toUpperCase();
    const base = normalized.split('.')[0];
    const candidateSet = new Set();
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

function buildPositionTriggerMarkLineData(tsCode) {
    if (!stockStore.positionTriggerLineEnabled) {
        return []
    }
    const activeCode = toCanonicalTsCode(tsCode || stockStore.tsCode)
    const triggerCode = toCanonicalTsCode(stockStore.positionTriggerTsCode)
    if (!activeCode || !triggerCode || activeCode !== triggerCode) {
        return []
    }

    const upgradePrice = Number(stockStore.positionTriggerUpgradePrice)
    const downgradePrice = Number(stockStore.positionTriggerDowngradePrice)
    const lines = []

    if (Number.isFinite(upgradePrice) && upgradePrice > 0) {
        lines.push({
            name: '升仓触发',
            yAxis: Number(upgradePrice.toFixed(3)),
            lineStyle: { color: '#16a34a', type: 'dashed', width: 1.2 },
            label: {
                show: true,
                position: 'end',
                formatter: `升仓 ${upgradePrice.toFixed(2)}`,
                color: '#166534',
                fontSize: 11,
            },
        })
    }

    if (Number.isFinite(downgradePrice) && downgradePrice > 0) {
        lines.push({
            name: '降仓触发',
            yAxis: Number(downgradePrice.toFixed(3)),
            lineStyle: { color: '#ea580c', type: 'dashed', width: 1.2 },
            label: {
                show: true,
                position: 'end',
                formatter: `降仓 ${downgradePrice.toFixed(2)}`,
                color: '#9a3412',
                fontSize: 11,
            },
        })
    }
    return lines
}

function buildPositionTriggerMarkLine(tsCode) {
    const data = buildPositionTriggerMarkLineData(tsCode)
    if (!data.length) {
        return null
    }
    return {
        symbol: ['none', 'none'],
        silent: true,
        animation: false,
        data,
    }
}

function applyPositionTriggerLines(tsCode) {
    if (!Array.isArray(chartTrendOption.value.series) || !chartTrendOption.value.series.length) {
        return
    }
    const markLine = buildPositionTriggerMarkLine(tsCode || stockStore.tsCode)
    if (markLine) {
        chartTrendOption.value.series[0].markLine = markLine
    } else if (chartTrendOption.value.series[0].markLine) {
        delete chartTrendOption.value.series[0].markLine
    }
    applyPositionTriggerYAxisRange(tsCode || stockStore.tsCode)
}

function applyPositionTriggerYAxisRange(tsCode) {
    const yAxis = chartTrendOption.value?.yAxis?.[0]
    if (!yAxis) {
        return
    }
    const lineData = buildPositionTriggerMarkLineData(tsCode)
    const triggerPrices = lineData
        .map(item => Number(item?.yAxis))
        .filter(v => Number.isFinite(v) && v > 0)

    if (!triggerPrices.length) {
        yAxis.min = 'dataMin'
        yAxis.max = 'dataMax'
        return
    }

    const lows = (kdata.value || []).map(item => Number(item?.[2])).filter(v => Number.isFinite(v))
    const highs = (kdata.value || []).map(item => Number(item?.[3])).filter(v => Number.isFinite(v))
    const dataMin = lows.length ? Math.min(...lows) : null
    const dataMax = highs.length ? Math.max(...highs) : null

    if (dataMin === null || dataMax === null) {
        yAxis.min = 'dataMin'
        yAxis.max = 'dataMax'
        return
    }

    const triggerMin = Math.min(...triggerPrices)
    const triggerMax = Math.max(...triggerPrices)

    const needExtend = triggerMin < dataMin || triggerMax > dataMax
    if (!needExtend) {
        yAxis.min = 'dataMin'
        yAxis.max = 'dataMax'
        return
    }

    const low = Math.min(dataMin, triggerMin)
    const high = Math.max(dataMax, triggerMax)
    const rawSpan = high - low
    const pad = rawSpan > 0 ? rawSpan * 0.03 : Math.max(Math.abs(high) * 0.03, 0.5)
    yAxis.min = Number((low - pad).toFixed(3))
    yAxis.max = Number((high + pad).toFixed(3))
}

async function fetchStockStatus(tsCode) {
    if (!baseURL || !tsCode) {
        return;
    }
    try {
        const candidates = buildTsCodeCandidates(tsCode);
        let fallbackData = null;
        for (const candidate of candidates) {
            const res = await axios.get(`${baseURL}/watchlist/check/${candidate}/`);
            if (!res.data) continue;
            if (!fallbackData) {
                fallbackData = res.data;
            }
            if (res.data.hold_position || res.data.in_watchlist) {
                isHolding.value = !!res.data.hold_position;
                isInWatchlist.value = !!res.data.in_watchlist;
                return;
            }
        }
        if (fallbackData) {
            isHolding.value = !!fallbackData.hold_position;
            isInWatchlist.value = !!fallbackData.in_watchlist;
        }
    } catch (error) {
        console.error('Failed to fetch stock status:', error);
    }
}

async function toggleWatchlistStatus(watchlist) {
    if (!baseURL || !stockStore.tsCode) {
        return;
    }
    try {
        let res;
        if (watchlist) {
            const url = `${baseURL}/watchlist/add/${stockStore.tsCode}/`;
            res = await axios.post(url);
        } else {
            const url = `${baseURL}/watchlist/delete/${stockStore.tsCode}/`;
            res = await axios.put(url);
        }
        if (res.status === 200) {
            isInWatchlist.value = !isInWatchlist.value;
            ElMessage.success(isInWatchlist.value ? '已加入自选股' : '已移除自选股');
        }
    } catch (error) {
        console.error('Failed to toggle watchlist status:', error);
        ElMessage.error('操作失败，请稍后重试');
    }
}

async function toggleHoldingStatus(hold) {
    if (!baseURL || !stockStore.tsCode) {
        return;
    }
    try {
        const url = hold
            ? `${baseURL}/watchlist/hold/${stockStore.tsCode}/`
            : `${baseURL}/watchlist/unhold/${stockStore.tsCode}/`;
        const method = hold ? 'post' : 'put';
        const res = await axios({ url, method });
        if (res.status === 200) {
            isHolding.value = hold;
            isInWatchlist.value = !!res.data.in_watchlist;
            ElMessage.success(isHolding.value ? '已标记为持仓' : '已取消持仓标记');
        }
    } catch (error) {
        console.error('Failed to toggle holding status:', error);
        ElMessage.error('操作失败，请稍后重试');
    }
}

// 注册渲染器
// use([TitleComponent])
// use([CanvasRenderer])
// use([TooltipComponent])

// 创建联动的 group id
const chartGroup = 'stockChartsGroup'
const trendChartRef = ref()
const chipChartRef = ref()

const techChartRef = ref()
const peChartRef = ref()
const peTTMChartRef = ref()
const psChartRef = ref()
const psTTMChartRef = ref()
const pbChartRef = ref()
const turnoverChartRef = ref()
const turnoverFChartRef = ref()
const volRatioChartRef = ref()

const volOption = ref('vol')
const techOption = ref('macd')
const adjPriceOption = ref('qfq')

// 处理后的chart数据
const kdata = ref([])
const vol = ref([])
const amount = ref([])
const tradeDates = ref([])
const sl1 = ref([])
const sl2 = ref([])
const tp1 = ref([])
const tp2 = ref([])
const indicData = ref({})
const close = ref([])
const pctChg = ref([])
const chipBars = ref([])
const chipTradeDate = ref('')
const chipCurrentPrice = ref(null)
const chipWinRate = ref(0)
const chipConcentrationRate = ref(0)
const lastHoverIndex = ref(-1)
const chipCache = new Map()
const chipRequestToken = ref(0)
const tradingHistoryCache = new Map()
const tradingHistoryPending = new Map()
const parsedTradingCache = new Map()
const derivedTradingCache = new Map()
const tradingHistoryRenderPending = new Map()
const tradingHistoryPrefetched = new Set()
const topBottomCache = new Map()
const topBottomPending = new Map()
const trendChartsLoading = ref(false)
const trendInitialLoadDone = ref(false)
const TREND_ZOOM_STORAGE_KEY = 'smartinvestor_stockchart_trend_zoom_v1'
const trendZoomRange = ref({ start: 0, end: 100 })
let embedSwitchRequestToken = 0

const trendMaLineStyles = {
    MA6: { width: 1, color: '#5470C6' },
    MA10: { width: 1, color: '#91CC75' },
    MA25: { width: 1, color: '#FAC858' },
    MA43: { width: 1, color: '#EE6666' },
    MA60: { width: 1, color: '#73C0DE' },
    MA120: { width: 1, color: '#3BA272' },
    MA200: { width: 1, color: '#FC8452' }
}

function getTradingHistoryCacheKey(stockCode, freq, adj, count) {
    return [String(stockCode || '').trim().toUpperCase(), freq, adj, count].join('|')
}

function prefetchTradingHistoryVariants(stockCode = '', adj = 'qfq', count = 60, currentFreq = 'D') {
    if (!displayEmbed.value || !baseURL) {
        return
    }
    const normalizedStockCode = String(stockCode || '').trim().toUpperCase()
    if (!normalizedStockCode) {
        return
    }
    ;['D', 'W', 'M'].forEach((freqItem) => {
        if (freqItem === currentFreq) {
            return
        }
        const key = getTradingHistoryCacheKey(normalizedStockCode, freqItem, adj, count)
        if (tradingHistoryCache.has(key) || tradingHistoryPending.has(key) || tradingHistoryPrefetched.has(key)) {
            return
        }
        tradingHistoryPrefetched.add(key)
        const url = `${baseURL}/stocks/${normalizedStockCode}/trading-history/${freqItem}/${adj}/${count}/`
        const task = axios.get(url)
            .then(response => {
                tradingHistoryCache.set(key, response.data)
                return response.data
            })
            .finally(() => {
                tradingHistoryPending.delete(key)
            })
        tradingHistoryPending.set(key, task)
    })
}

function getTopBottomCacheKey(tsCode, model, freq, count, version) {
    return [String(tsCode || '').trim().toUpperCase(), String(model || '').trim().toUpperCase(), freq, count, version].join('|')
}

function clampZoomPercent(value, fallback) {
    const numeric = Number(value)
    if (!Number.isFinite(numeric)) {
        return fallback
    }
    return Math.min(100, Math.max(0, numeric))
}

function readTrendZoomRange() {
    if (typeof window === 'undefined') {
        return { start: 0, end: 100 }
    }
    try {
        const raw = window.localStorage.getItem(TREND_ZOOM_STORAGE_KEY)
        if (!raw) {
            return { start: 0, end: 100 }
        }
        const parsed = JSON.parse(raw)
        const start = clampZoomPercent(parsed?.start, 0)
        const end = clampZoomPercent(parsed?.end, 100)
        return { start: Math.min(start, end), end: Math.max(start, end) }
    } catch {
        return { start: 0, end: 100 }
    }
}

function writeTrendZoomRange(range) {
    const start = clampZoomPercent(range?.start, 0)
    const end = clampZoomPercent(range?.end, 100)
    const normalized = { start: Math.min(start, end), end: Math.max(start, end) }
    trendZoomRange.value = normalized
    if (typeof window === 'undefined') {
        return
    }
    try {
        window.localStorage.setItem(TREND_ZOOM_STORAGE_KEY, JSON.stringify(normalized))
    } catch {
        // ignore localStorage failures
    }
}

function applyTrendZoomToOption() {
    const nextZoom = {
        ...chartTrendOption.value.dataZoom[0],
        start: trendZoomRange.value.start,
        end: trendZoomRange.value.end,
    }
    chartTrendOption.value.dataZoom = [nextZoom]
}

const chipWinRateText = computed(() => `${Number(chipWinRate.value || 0).toFixed(2)}%`)
const chipConcentrationRateText = computed(() => `${Number(chipConcentrationRate.value || 0).toFixed(2)}%`)
const chipCurrentPriceText = computed(() => {
    const v = Number(chipCurrentPrice.value)
    return Number.isFinite(v) ? v.toFixed(2) : '--'
})

// 获取股票数据
const selectedFreqEmbed = ref('D')
const selectedPeriodEmbed = ref('60')
const props = defineProps({
    displayEmbed: {
        type: Boolean,
        default: false
    },
    showBottomInEmbed: {
        type: Boolean,
        default: false
    }
})
const displayEmbed = computed(() => props.displayEmbed)
const shouldShowBottom = computed(() => !displayEmbed.value || props.showBottomInEmbed)
const bottomFundamentalsExpanded = ref(!displayEmbed.value)
const shouldRenderBottom = computed(() => shouldShowBottom.value && (!displayEmbed.value || bottomFundamentalsExpanded.value))

// 处理json数据的方法
function buildParsedStockChartData(jsonData) {
    const k = []
    const v = []
    const a = []
    const c = []
    const p = []
    const sl_1 = []
    const sl_2 = []
    const tp_1 = []
    const tp_2 = []
    const dates = []
    const indic = {}

    for (const item of jsonData.data) {
        k.push([item.open, item.close, item.low, item.high])
        v.push(item.vol)
        a.push(item.amount)
        c.push(item.close)
        p.push(item.pct_chg)
        sl_1.push(item.sl1)
        sl_2.push(item.sl2)
        tp_1.push(item.tp1)
        tp_2.push(item.tp2)
        dates.push(item.trade_date)
        if (item.indicator) {
            // MACD: macd, macd_dif, macd_dea
            if ('macd' in item.indicator) {
                indic.macd = indic.macd || []
                indic.macd_dif = indic.macd_dif || []
                indic.macd_dea = indic.macd_dea || []
                indic.macd.push(item.indicator.macd.macd ?? null)
                indic.macd_dif.push(item.indicator.macd.macd_dif ?? null)
                indic.macd_dea.push(item.indicator.macd.macd_dea ?? null)
            }
            // KDJ: kdj_k, kdj_d, kdj_j
            if ('kdj' in item.indicator) {
                indic.kdj_k = indic.kdj_k || []
                indic.kdj_d = indic.kdj_d || []
                indic.kdj_j = indic.kdj_j || []
                indic.kdj_k.push(item.indicator.kdj.kdj_k ?? null)
                indic.kdj_d.push(item.indicator.kdj.kdj_d ?? null)
                indic.kdj_j.push(item.indicator.kdj.kdj_j ?? null)
            }
            // RSI: rsi
            if ('rsi' in item.indicator) {
                indic.rsi_6 = indic.rsi_6 || []
                indic.rsi_12 = indic.rsi_12 || []
                indic.rsi_24 = indic.rsi_24 || []
                indic.rsi_6.push(item.indicator.rsi.rsi_6 ?? null)
                indic.rsi_12.push(item.indicator.rsi.rsi_12 ?? null)
                indic.rsi_24.push(item.indicator.rsi.rsi_24 ?? null)
            }
            // CCI: cci
            if ('cci' in item.indicator) {
                indic.cci = indic.cci || []
                indic.cci.push(item.indicator.cci.cci ?? null)
            }
        }
    }

    return {
        kdata: k,
        vol: v,
        amount: a,
        close: c,
        pctChg: p,
        sl1: sl_1,
        sl2: sl_2,
        tp1: tp_1,
        tp2: tp_2,
        tradeDates: dates,
        indicData: indic
    }
}

function applyParsedStockChartData(parsedData) {
    kdata.value = parsedData.kdata
    vol.value = parsedData.vol
    amount.value = parsedData.amount
    close.value = parsedData.close
    pctChg.value = parsedData.pctChg
    sl1.value = parsedData.sl1
    sl2.value = parsedData.sl2
    tp1.value = parsedData.tp1
    tp2.value = parsedData.tp2
    tradeDates.value = parsedData.tradeDates
    indicData.value = parsedData.indicData
}

function buildDerivedTradingChartData(parsedData) {
    const maPeriods = [6, 10, 25, 43, 60, 120, 200]
    const positionTriggerMarkLine = buildPositionTriggerMarkLine(stockStore.tsCode)

    const trendSeries = [
        {
            name: 'K线',
            type: 'candlestick',
            data: parsedData.kdata,
            ...(positionTriggerMarkLine ? { markLine: positionTriggerMarkLine } : {})
        },
        ...maPeriods.map(period => ({
            name: `MA${period}`,
            type: 'line',
            data: calcMovingAvg(parsedData.close, period),
            smooth: true,
            lineStyle: trendMaLineStyles[`MA${period}`] || { width: 1 },
            showSymbol: false
        })),
        {
            name: '收盘价 90%分位',
            type: 'line',
            data: quantile(parsedData.close, 0.9),
            smooth: true,
            showSymbol: false,
            lineStyle: { color: 'red', width: 1 }
        },
        {
            name: '收盘价中位数',
            type: 'line',
            data: quantile(parsedData.close, 0.5),
            smooth: true,
            showSymbol: false,
            lineStyle: { color: 'blue', width: 1 }
        },
        {
            name: '收盘价 10%分位',
            type: 'line',
            data: quantile(parsedData.close, 0.1),
            smooth: true,
            showSymbol: false,
            lineStyle: { color: 'green', width: 1 }
        },
        {
            name: 'SL1',
            type: 'line',
            data: parsedData.sl1,
            smooth: true,
            showSymbol: false,
            lineStyle: { color: '#22c55e', width: 1 }
        },
        {
            name: 'SL2',
            type: 'line',
            data: parsedData.sl2,
            smooth: true,
            showSymbol: false,
            lineStyle: { color: '#15803d', width: 1 }
        },
        {
            name: 'TP1',
            type: 'line',
            data: parsedData.tp1,
            smooth: true,
            showSymbol: false,
            lineStyle: { color: '#f97316', width: 1 }
        },
        {
            name: 'TP2',
            type: 'line',
            data: parsedData.tp2,
            smooth: true,
            showSymbol: false,
            lineStyle: { color: '#ea580c', width: 1 }
        }
    ]

    const volSeries = [
        {
            name: '成交量',
            type: 'bar',
            data: parsedData.vol,
            smooth: true
        },
        {
            name: '成交量 90%分位',
            type: 'line',
            data: quantile(parsedData.vol, 0.9),
            smooth: true,
            showSymbol: false,
            lineStyle: { color: 'red', width: 1 }
        },
        {
            name: '成交量 10%分位',
            type: 'line',
            data: quantile(parsedData.vol, 0.1),
            smooth: true,
            showSymbol: false,
            lineStyle: { color: 'green', width: 1 }
        }
    ]

    const techSeriesByOption = {
        macd: [
            { name: 'MACD', key: 'macd' },
            { name: 'DIF', key: 'macd_dif' },
            { name: 'DEA', key: 'macd_dea' }
        ],
        kdj: [
            { name: 'K', key: 'kdj_k' },
            { name: 'D', key: 'kdj_d' },
            { name: 'J', key: 'kdj_j' }
        ],
        rsi: [
            { name: 'RSI', key: 'rsi' }
        ],
        cci: [
            { name: 'CCI', key: 'cci' }
        ]
    }

    return {
        trendSeries,
        volSeries,
        techXAxis: parsedData.tradeDates,
        techSeriesByOption: Object.fromEntries(
            Object.entries(techSeriesByOption).map(([option, items]) => [
                option,
                items
                    .filter(item => parsedData.indicData[item.key])
                    .map(item => ({
                        name: item.name,
                        type: item.name === 'MACD' ? 'bar' : 'line',
                        data: parsedData.indicData[item.key],
                        smooth: item.name === 'MACD' ? false : true,
                        showSymbol: false
                    }))
            ])
        )
    }
}

function applyDerivedTradingChartData(parsedData, derivedData) {
    chartTrendOption.value.xAxis[0].data = parsedData.tradeDates
    chartTrendOption.value.xAxis[1].data = parsedData.tradeDates
    applyTrendZoomToOption()
    const trendSeries = derivedData.trendSeries.map(series => ({
        ...series,
        xAxisIndex: 0,
        yAxisIndex: 0,
    }))
    const volSeries = derivedData.volSeries.map(series => ({
        ...series,
        xAxisIndex: 1,
        yAxisIndex: 1,
    }))
    chartTrendOption.value.series = [...trendSeries, ...volSeries]
    applyPositionTriggerLines(stockStore.tsCode)
    chartTechOption.value.xAxis.data = derivedData.techXAxis
    chartTechOption.value.series = (derivedData.techSeriesByOption[techOption.value] || []).map(series => ({ ...series }))
}

/**
 * Calculate moving average for a given data array and window size.
 * @param {number[]} data - Array of numbers (e.g., close prices).
 * @param {number} window - Window size for moving average.
 * @returns {number[]} - Array of moving average values (same length as data, with nulls for insufficient data).
 */
function calcMovingAvg(data, window) {
    if (!Array.isArray(data) || window <= 0) return []
    const result = []
    for (let i = 0; i < data.length; i++) {
        if (i < window - 1) {
            result.push(null)
        } else {
            const sum = data.slice(i - window + 1, i + 1).reduce((a, b) => a + b, 0)
            result.push(Number((sum / window).toFixed(4)))
        }
    }
    return result
}

// 配置三个图表的 option，并设置 group
const chartTrendOption = ref({
    animation: false,
    title: {
        text: 'K线',
        left: 'left',
        textStyle: {
            fontSize: 14
        }
    },
    tooltip: {
        trigger: 'axis',
        confine: true,
        padding: [4, 8],
        textStyle: {
            fontSize: 12
        },
        axisPointer: {
            type: 'cross'
        },
        formatter: function (params) {
            // params is an array of series data at the hovered point
            // Only show the candlestick (K线) info
            const kline = params.find(item => item.seriesType === 'candlestick')
            if (!kline) return ''
            // ECharts candlestick expects [open, close, low, high]
            // But sometimes data is [open, close, low, high], so destructure accordingly
            const [idx, open, close, low, high] = kline.data
            // If you see wrong values, log kline.data for debugging
            // console.log('kline.data', kline.data)
            let pctChange = ''
            if (kline.dataIndex > 0 && kline.seriesIndex === 0) {
                // Find previous close from the same series' data
                const seriesData = this && this.seriesData ? this.seriesData : null
                let prevClose = null
                if (seriesData && Array.isArray(seriesData[kline.dataIndex - 1])) {
                    prevClose = seriesData[kline.dataIndex - 1][1]
                } else if (Array.isArray(chartTrendOption.value.series[0].data[kline.dataIndex - 1])) {
                    prevClose = chartTrendOption.value.series[0].data[kline.dataIndex - 1][1]
                }
                if (typeof prevClose === 'number' && prevClose !== 0) {
                    pctChange = ((close - prevClose) / prevClose * 100).toFixed(2) + '%'
                }
            }
            return `
            <div>
                <strong>${kline.axisValue}</strong><br/>
                开盘: ${open}<br/>
                收盘: ${close}<br/>
                最低: ${low}<br/>
                最高: ${high}<br/>
                ${pctChange ? `涨跌幅: ${pctChange}` : ''}
            </div>
            `
        }
    },
    grid: [
        { left: '8%', right: '4%', top: 34, height: '56%' },
        { left: '8%', right: '4%', top: '72%', height: '20%' },
    ],
    xAxis: [
        {
            type: 'category',
            data: [],
            gridIndex: 0,
            axisLabel: { show: false },
        },
        {
            type: 'category',
            data: [],
            gridIndex: 1,
        },
    ],
    yAxis: [
        {
            type: 'value',
            name: '价格',
            min: 'dataMin',
            max: 'dataMax',
            splitLine: { show: true, lineStyle: { type: 'dashed', color: '#f5f5f5' } },
            gridIndex: 0,
        },
        {
            type: 'value',
            name: '量(/1000)',
            axisLabel: {
                formatter: (value) => {
                    const num = Number(value)
                    if (!Number.isFinite(num)) return ''
                    const scaled = num / 1000
                    if (Math.abs(scaled) >= 100) return scaled.toFixed(0)
                    if (Math.abs(scaled) >= 10) return scaled.toFixed(1)
                    return scaled.toFixed(2)
                }
            },
            splitLine: { show: true, lineStyle: { type: 'dashed', color: '#f5f5f5' } },
            gridIndex: 1,
        },
    ],
    legend: {
        show: true,
        left: 'center',
        // Exclude 'K线' from legend
        selector: false,
        data: [
            'MA6', 'MA10', 'MA25', 'MA43', 'MA60', 'MA120', 'MA200'
        ]
    },
    dataZoom: [
        {
            type: 'inside',
            xAxisIndex: [0, 1],
            start: 0,
            end: 100
        }
    ],
    series: [
        {
            name: 'K线',
            type: 'candlestick',
            data: []
        },
        {
            name: 'MA6',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 1,
                color: '#5470C6'
            },
            showSymbol: false
        }
        ,
        {
            name: 'MA10',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 1,
                color: '#91cc75'
            },
            showSymbol: false
        },
        {
            name: 'MA25',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 2,
                color: '#fac858'
            },
            showSymbol: false
        },
        {
            name: 'MA43',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 1,
                color: '#ee6666'
            },
            showSymbol: false
        },
        {
            name: 'MA60',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 1,
                color: '#73c0de'
            },
            showSymbol: false
        },
        {
            name: 'MA120',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 1,
                color: '#3ba272'
            },
            showSymbol: false
        },
        {
            name: 'MA200',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 2,
                color: '#fc8452'
            },
            showSymbol: false
        },
        {
            name: 'SL1',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 2,
                // color: '#fc8452'
            },
            showSymbol: false
        },
        {
            name: 'SL2',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 2,
                // color: '#fc8452'
            },
            showSymbol: false
        },
        {
            name: 'TP1',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 2,
                // color: '#fc8452'
            },
            showSymbol: false
        },
        {
            name: 'TP2',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 2,
                // color: '#fc8452'
            },
            showSymbol: false
        },
    ]
})

const chartVolOption = ref({
    animation: false,
    title: {
        show: false,
        text: '',
        left: 'left',
        textStyle: {
            fontSize: 14
        }
    },
    tooltip: {
        trigger: 'axis',
        confine: true,
        padding: [4, 8],
        textStyle: {
            fontSize: 12
        }
    },
    xAxis: {
        type: 'category',
        data: []
    },
    yAxis: {
        type: 'value',
        splitLine: { show: true, lineStyle: { type: 'dashed', color: '#f5f5f5' } }

    },
    dataZoom: [
        {
            type: 'inside',
            start: 0,
            end: 100
        }
    ],
    series: [
        {
            name: '成交量',
            type: 'bar',
            data: [],
            smooth: true
        }
    ]
})

const chartTechOption = ref({
    title: {
        text: '技术指标',
        left: 'left',
        textStyle: {
            fontSize: 14
        }
    },
    tooltip: {
        trigger: 'axis',
        confine: true,
        padding: [4, 8],
        textStyle: {
            fontSize: 12
        }
    },
    legend: {
        show: true,
        left: 'center'
    },
    xAxis: {
        type: 'category',
        data: []
    },
    yAxis: {
        type: 'value',
        splitLine: { show: true, lineStyle: { type: 'dashed', color: '#f5f5f5' } }
    },
    dataZoom: [
        {
            type: 'inside',
            start: 0,
            end: 100
        }
    ],
})

const chartChipOption = ref({
    animation: false,
    title: {
        text: '筹码分布',
        left: 'left',
        textStyle: { fontSize: 14 }
    },
    tooltip: {
        trigger: 'axis',
        confine: true,
        padding: [4, 8],
        textStyle: { fontSize: 12 },
        axisPointer: { type: 'shadow' },
        formatter: function (params) {
            const item = params && params[0]
            if (!item) return ''
            const idx = Number(item.dataIndex)
            const row = chipBars.value[idx]
            if (!row) return ''
            return `价格: ${Number(row.price).toFixed(2)}<br/>筹码占比: ${Number(row.percent || 0).toFixed(2)}%`
        }
    },
    xAxis: {
        type: 'value',
        name: 'percent',
        splitLine: { show: true, lineStyle: { type: 'dashed', color: '#f5f5f5' } }
    },
    yAxis: {
        type: 'category',
        name: 'price',
        inverse: false,
        splitLine: { show: false },
        data: []
    },
    series: [
        {
            name: '筹码',
            type: 'bar',
            barMaxWidth: 8,
            data: []
        }
    ]
})

function buildPaddedChipBuckets(sortedRows) {
    if (!Array.isArray(sortedRows) || !sortedRows.length) return []
    const minDisplayPrice = 0.01
    let minStep = Number.POSITIVE_INFINITY
    for (let i = 1; i < sortedRows.length; i++) {
        const diff = Number((sortedRows[i].price - sortedRows[i - 1].price).toFixed(6))
        if (diff > 0 && diff < minStep) minStep = diff
    }
    if (!Number.isFinite(minStep)) minStep = 0.01
    minStep = Math.max(minStep, 0.0001)

    const padCount = Math.max(8, Math.ceil(sortedRows.length * 0.25))
    const minPrice = sortedRows[0].price
    const maxPrice = sortedRows[sortedRows.length - 1].price
    const out = []
    for (let i = padCount; i >= 1; i--) {
        const p = Number((minPrice - minStep * i).toFixed(4))
        if (p < minDisplayPrice) continue
        out.push({ price: p, percent: 0, isReal: false })
    }
    for (const row of sortedRows) {
        out.push({ price: row.price, percent: row.percent, isReal: true })
    }
    for (let i = 1; i <= padCount; i++) {
        const p = Number((maxPrice + minStep * i).toFixed(4))
        out.push({ price: p, percent: 0, isReal: false })
    }
    return out
}

function refreshChipChartOption() {
    const realBars = chipBars.value.filter(item => item && item.isReal)
    const totalPercent = realBars.reduce((sum, item) => sum + Number(item.percent || 0), 0)

    if (!realBars.length || totalPercent <= 0) {
        chipWinRate.value = 0
        chipConcentrationRate.value = 0
    } else {
        const currentPrice = Number(chipCurrentPrice.value)
        if (Number.isFinite(currentPrice)) {
            const winPercent = realBars
                .filter(item => Number(item.price) <= currentPrice)
                .reduce((sum, item) => sum + Number(item.percent || 0), 0)
            chipWinRate.value = (winPercent / totalPercent) * 100
        } else {
            chipWinRate.value = 0
        }

        const topCount = Math.max(1, Math.ceil(realBars.length * 0.1))
        const concentrationPercent = [...realBars]
            .sort((a, b) => Number(b.percent || 0) - Number(a.percent || 0))
            .slice(0, topCount)
            .reduce((sum, item) => sum + Number(item.percent || 0), 0)
        chipConcentrationRate.value = (concentrationPercent / totalPercent) * 100
    }

    chartChipOption.value.title.text = `筹码分布 ${chipTradeDate.value || ''}`.trim()
    chartChipOption.value.yAxis.data = chipBars.value.map(item => Number(item.price).toFixed(2))
    chartChipOption.value.series[0].data = chipBars.value.map(item => ({
        value: item.percent,
        itemStyle: {
            color: !item.isReal
                ? 'rgba(0,0,0,0)'
                : (chipCurrentPrice.value !== null && Number(item.price) <= Number(chipCurrentPrice.value)
                    ? '#d14a61'
                    : '#8f9399')
        }
    }))
}

function normalizeTradeDateKey(tradeDate) {
    return String(tradeDate || '').replace(/-/g, '').trim()
}

function getChipCacheKey(tsCode, tradeDate) {
    return `${tsCode}|${normalizeTradeDateKey(tradeDate)}`
}

function buildChipBucketsFromRows(rows) {
    const map = new Map()
    for (const item of rows || []) {
        const price = Number(item.price)
        const percent = Number(item.percent)
        if (!Number.isFinite(price) || !Number.isFinite(percent)) continue
        map.set(price, (map.get(price) || 0) + percent)
    }
    const sorted = Array.from(map.entries())
        .map(([price, percent]) => ({ price, percent }))
        .sort((a, b) => a.price - b.price)
    return buildPaddedChipBuckets(sorted)
}

async function fetchChipDistributionBatch(tsCode, tradeDateList) {
    if (!tsCode || !Array.isArray(tradeDateList) || tradeDateList.length === 0) return
    const normalizedDates = tradeDateList
        .map(normalizeTradeDateKey)
        .filter(Boolean)
    if (!normalizedDates.length) return

    const uniqueDates = Array.from(new Set(normalizedDates)).sort()
    const startDate = uniqueDates[0]
    const endDate = uniqueDates[uniqueDates.length - 1]

    const missingDates = uniqueDates.filter(dateKey => !chipCache.has(getChipCacheKey(tsCode, dateKey)))
    if (missingDates.length === 0) {
        return
    }

    const batchCacheKey = `${tsCode}|RANGE|${startDate}|${endDate}`
    if (chipCache.has(batchCacheKey) && missingDates.length === 0) {
        return
    }

    try {
        const url = `${baseURL}/tushare/${encodeURIComponent(tsCode)}/CYQ_CHIPS/`
        const resp = await axios.get(url, { params: { start_date: startDate, end_date: endDate } })
        const rows = Array.isArray(resp?.data?.data) ? resp.data.data : []

        const byDate = new Map()
        for (const row of rows) {
            const key = normalizeTradeDateKey(row.trade_date)
            if (!key) continue
            if (!byDate.has(key)) byDate.set(key, [])
            byDate.get(key).push(row)
        }

        for (const dateKey of uniqueDates) {
            const cacheKey = getChipCacheKey(tsCode, dateKey)
            if (chipCache.has(cacheKey)) continue
            const dayRows = byDate.get(dateKey) || []
            const padded = buildChipBucketsFromRows(dayRows)
            if (padded.length > 0) {
                chipCache.set(cacheKey, padded)
            }
        }

        chipCache.set(batchCacheKey, true)
    } catch (error) {
        // batch加载失败时回退到按日加载
    }
}

async function fetchChipDistribution(tsCode, tradeDate, currentPrice = null) {
    if (!tsCode || !tradeDate) return
    chipTradeDate.value = tradeDate
    chipCurrentPrice.value = currentPrice

    const cacheKey = getChipCacheKey(tsCode, tradeDate)
    if (chipCache.has(cacheKey)) {
        const cached = chipCache.get(cacheKey)
        if (Array.isArray(cached) && cached.length > 0) {
            chipBars.value = cached
            refreshChipChartOption()
            return
        }
    }

    const ymd = String(tradeDate).replace(/-/g, '')
    try {
        const url = `${baseURL}/tushare/${encodeURIComponent(tsCode)}/CYQ_CHIPS/`
        const resp = await axios.get(url, { params: { start_date: ymd, end_date: ymd } })
        const rows = Array.isArray(resp?.data?.data) ? resp.data.data : []
        chipBars.value = buildChipBucketsFromRows(rows)
        chipCache.set(cacheKey, chipBars.value)
        refreshChipChartOption()
    } catch (error) {
        chipBars.value = []
        refreshChipChartOption()
    }
}

function loadLatestChipDistribution(stockCode) {
    if (tradeDates.value.length === 0) return

    const idx = tradeDates.value.length - 1
    const tradeDate = tradeDates.value[idx]
    const currentClose = close.value[idx]
    const requestToken = ++chipRequestToken.value

    lastHoverIndex.value = idx
    chipTradeDate.value = tradeDate
    chipCurrentPrice.value = currentClose

    const cacheKey = getChipCacheKey(stockCode, tradeDate)
    const cached = chipCache.get(cacheKey)
    if (Array.isArray(cached) && cached.length > 0) {
        chipBars.value = cached
        refreshChipChartOption()
    } else {
        chipBars.value = []
        refreshChipChartOption()
    }

    fetchChipDistributionBatch(stockCode, tradeDates.value).catch(() => undefined)
    fetchChipDistribution(stockCode, tradeDate, currentClose).then(() => {
        if (requestToken !== chipRequestToken.value) {
            return
        }
    }).catch(() => undefined)
}

function resolveKlineIndexFromPointer(event) {
    const info = event?.axesInfo?.find(x => x.axisDim === 'x')
    if (!info) return -1

    const infoDataIndex = Number(info.dataIndex)
    if (Number.isInteger(infoDataIndex) && infoDataIndex >= 0 && infoDataIndex < tradeDates.value.length) {
        return infoDataIndex
    }

    const raw = info.value
    const idx = Number(raw)
    if (Number.isInteger(idx) && idx >= 0 && idx < tradeDates.value.length) {
        return idx
    }
    const asText = String(raw ?? '')
    const normalized = asText.replace(/-/g, '')
    return tradeDates.value.findIndex(d => String(d) === asText || String(d).replace(/-/g, '') === normalized)
}

function onTrendAxisPointer(event) {
    const idx = resolveKlineIndexFromPointer(event)
    if (idx < 0 || idx >= tradeDates.value.length) return

    if (idx === lastHoverIndex.value) {
        const latestClose = close.value[idx]
        if (chipCurrentPrice.value !== latestClose) {
            chipCurrentPrice.value = latestClose
            refreshChipChartOption()
        }
        return
    }

    lastHoverIndex.value = idx
    chipRequestToken.value += 1
    const tradeDate = tradeDates.value[idx]
    const currentClose = close.value[idx]
    fetchChipDistribution(stockStore.tsCode, tradeDate, currentClose)
}

function onTrendDataZoom(event) {
    const payload = Array.isArray(event?.batch) && event.batch.length ? event.batch[0] : event
    const hasStart = Number.isFinite(Number(payload?.start))
    const hasEnd = Number.isFinite(Number(payload?.end))
    if (!hasStart || !hasEnd) {
        return
    }
    writeTrendZoomRange({ start: payload.start, end: payload.end })
    applyTrendZoomToOption()
}

function bindTrendHoverSync() {
    const chart = trendChartRef.value?.chart
    if (!chart) return
    chart.off('updateAxisPointer', onTrendAxisPointer)
    chart.on('updateAxisPointer', onTrendAxisPointer)
    chart.off('datazoom', onTrendDataZoom)
    chart.on('datazoom', onTrendDataZoom)
    chart.dispatchAction({
        type: 'dataZoom',
        start: trendZoomRange.value.start,
        end: trendZoomRange.value.end,
    })
}

function refreshTrendLayout() {
    nextTick(() => {
        ;[trendChartRef, chipChartRef].forEach(refItem => {
            const chart = refItem.value?.chart
            if (chart && typeof chart.resize === 'function') {
                chart.resize()
            }
        })
        bindTrendHoverSync()
    })
}

defineExpose({
    refreshTrendLayout,
})


// 配置8个基本面图表的 option，并设置 group
function createFundamentalChartOption(title) {
    return ref({
        title: {
            text: title,
            left: 'left',
            textStyle: { fontSize: 14 }
        },
        tooltip: {
            trigger: 'axis',
            confine: true,
            padding: [4, 8],
            textStyle: {
                fontSize: 12
            }
        },
        legend: { show: false, left: 'center' },
        xAxis: { type: 'category', data: [] },
        yAxis: {
            type: 'value',
            min: 'dataMin',
            max: 'dataMax',
            splitLine: { show: true, lineStyle: { type: 'dashed', color: '#f5f5f5' } }
        },
        dataZoom: [
            {
                type: 'inside',
                start: 0,
                end: 100
            }
        ],
    })
}

const chartPeOption = createFundamentalChartOption('市盈率')
const chartPeTTMOption = createFundamentalChartOption('市盈率(TTM)')
const chartPsOption = createFundamentalChartOption('市销率')
const chartPsTTMOption = createFundamentalChartOption('市销率(TTM)')
const chartPbOption = createFundamentalChartOption('市净率')
const chartVolRatioOption = createFundamentalChartOption('量比')
const chartTurnoverOption = createFundamentalChartOption('换手率')
const chartTurnoverFOption = createFundamentalChartOption('换手率(自由流通)')


async function fetchTradingHistory(stockCode = '', freq = 'D', adj = 'qfq', count = 60) {
    const normalizedStockCode = String(stockCode || '').trim().toUpperCase()
    if (!normalizedStockCode || !baseURL) {
        return
    }
    const cacheKey = getTradingHistoryCacheKey(normalizedStockCode, freq, adj, count)
    let renderTask = tradingHistoryRenderPending.get(cacheKey)
    if (!renderTask) {
        renderTask = (async () => {
            try {
                let parsedData = parsedTradingCache.get(cacheKey)
                let derivedData = derivedTradingCache.get(cacheKey)
                const shouldShowSkeleton = !trendInitialLoadDone.value && !parsedData && !tradingHistoryCache.has(cacheKey)
                if (shouldShowSkeleton) {
                    trendChartsLoading.value = true
                    await nextTick()
                }

                if (!parsedData) {
                    let jsonData = tradingHistoryCache.get(cacheKey)
                    if (!jsonData) {
                        let pendingRequest = tradingHistoryPending.get(cacheKey)
                        if (!pendingRequest) {
                            const url = `${baseURL}/stocks/${normalizedStockCode}/trading-history/${freq}/${adj}/${count}/`
                            pendingRequest = axios.get(url)
                                .then(response => {
                                    tradingHistoryCache.set(cacheKey, response.data)
                                    return response.data
                                })
                                .finally(() => {
                                    tradingHistoryPending.delete(cacheKey)
                                })
                            tradingHistoryPending.set(cacheKey, pendingRequest)
                        }
                        jsonData = await pendingRequest
                    }
                    parsedData = buildParsedStockChartData(jsonData)
                    parsedTradingCache.set(cacheKey, parsedData)
                }
                if (!derivedData) {
                    derivedData = buildDerivedTradingChartData(parsedData)
                    derivedTradingCache.set(cacheKey, derivedData)
                }

                applyParsedStockChartData(parsedData)
                applyDerivedTradingChartData(parsedData, derivedData)
                trendInitialLoadDone.value = true

                // Get the last item of kdata array
                const lastKData = kdata.value.length > 0 ? kdata.value[kdata.value.length - 1] : null

                // update stock trade store
                if (lastKData) {
                    stockStore.setOpen(lastKData[0])
                    stockStore.setClose(lastKData[1])
                    stockStore.setLow(lastKData[2])
                    stockStore.setHigh(lastKData[3])
                }
                stockStore.setPctChg(pctChg.value.length > 0 ? pctChg.value[pctChg.value.length - 1] : null)

                loadLatestChipDistribution(stockCode)
                prefetchTradingHistoryVariants(normalizedStockCode, adj, count, freq)

                await nextTick()
                bindTrendHoverSync()
            } catch (error) {
                console.error('Failed to fetch trading history:', error)
            } finally {
                trendChartsLoading.value = false
                tradingHistoryRenderPending.delete(cacheKey)
            }
        })()
        tradingHistoryRenderPending.set(cacheKey, renderTask)
    }
    await renderTask
}

const fundamentalData = ref([])

import { quantile } from './helper'

async function fetchFundamentalHistory(tsCode = stockStore.tsCode, freq = stockChartFilterStore.freq, count = stockChartFilterStore.period) {
    try {
        const url = `${baseURL}/stocks/${tsCode}/fundamental-history/${freq}/${count}/`
        const response = await axios.get(url)
        // The response data is in response.data.data
        fundamentalData.value = response.data.data

        // Assume response.data.data is an array of objects with fields: trade_date, pe, pe_ttm, ps, ps_ttm, pb, volume_ratio, turnover_rate, turnover_rate_f
        const dates = fundamentalData.value.map(item => item.trade_date)


        // Helper to set chart option for a metric
        function setChartOption(optionRef, arr, name) {
            optionRef.value.xAxis.data = dates
            optionRef.value.series = [
                { name, type: 'line', data: arr, smooth: true, showSymbol: false, },
                {
                    name: `${name} 90%分位`, type: 'line', data: quantile(arr, 0.9), smooth: true, showSymbol: false, lineStyle: { color: 'red', width: 1 },
                },
                {
                    name: `${name} 10%分位`, type: 'line', data: quantile(arr, 0.1), smooth: true, showSymbol: false, lineStyle: { color: 'green', width: 1 },
                }
            ]
        }

        setChartOption(chartPeOption, fundamentalData.value.map(i => i.pe), 'PE')
        setChartOption(chartPeTTMOption, fundamentalData.value.map(i => i.pe_ttm), 'PE(TTM)')
        setChartOption(chartPsOption, fundamentalData.value.map(i => i.ps), 'PS')
        setChartOption(chartPsTTMOption, fundamentalData.value.map(i => i.ps_ttm), 'PS(TTM)')
        setChartOption(chartPbOption, fundamentalData.value.map(i => i.pb), 'PB')
        setChartOption(chartVolRatioOption, fundamentalData.value.map(i => i.volume_ratio), '量比')
        setChartOption(chartTurnoverOption, fundamentalData.value.map(i => i.turnover_rate), '换手率')
        setChartOption(chartTurnoverFOption, fundamentalData.value.map(i => i.turnover_rate_f), '换手率(自由流通)')
    } catch (error) {
        console.error('Failed to fetch fundamental history:', error)
    }
}

// 在+k线图上渲染顶和低
// 获取顶底数据并在K线图上渲染
async function renderTopsBottomsOnTrendChart(tsCode = stockStore.tsCode, model = stockChartFilterStore.model,
    freq = stockChartFilterStore.freq, count = stockChartFilterStore.period, topBottomSwitch = stockChartFilterStore.topBottomSwitch, version = '1.2') {
    try {
        // 假设后端接口返回格式为 [{trade_date: '20240101', type: 'T'}, ...]
        if (!topBottomSwitch) {
            // 如果开关关闭，清除markPoint
            if (chartTrendOption.value.series[0].markPoint) {
                chartTrendOption.value.series[0].markPoint.data = []
            }
            return
        }
        const cacheKey = getTopBottomCacheKey(tsCode, model, freq, count, version)
        let tbData = topBottomCache.get(cacheKey)
        if (!tbData) {
            let pendingRequest = topBottomPending.get(cacheKey)
            if (!pendingRequest) {
                const url = `${baseURL}/stocks/${tsCode}/prediction/${model.toUpperCase()}/STDOPT/${count}/${freq}/${version}/`
                pendingRequest = axios.get(url)
                    .then(response => {
                        topBottomCache.set(cacheKey, response.data)
                        return response.data
                    })
                    .finally(() => {
                        topBottomPending.delete(cacheKey)
                    })
                topBottomPending.set(cacheKey, pendingRequest)
            }
            tbData = await pendingRequest
        }
        // tbData is an array of objects with { ts_code, trade_date, top_or_bottom }
        if (!Array.isArray(tbData.data) || tbData.data.length === 0) return

        // tradeDates.value: ['20240101', ...] or ['2025-08-29', ...]
        // Normalize trade_date format if needed
        const markPoints = tbData.data
            .map(tb => {
                // Try to match trade_date directly
                let idx = tradeDates.value.findIndex(d => d === tb.trade_date)
                // If not found, try removing dashes for comparison
                if (idx === -1) {
                    const normalizedDate = tb.trade_date.replace(/-/g, '')
                    idx = tradeDates.value.findIndex(d => d.replace(/-/g, '') === normalizedDate)
                }
                if (idx === -1) return null
                const k = kdata.value[idx]
                if (!k) return null
                // top_or_bottom: 'T' for top, 'B' for bottom
                return {
                    name: tb.top_or_bottom,
                    value: tb.top_or_bottom,
                    xAxis: idx,
                    yAxis: tb.top_or_bottom === 'T' ? k[3] : k[2], // high for T, low for B
                    symbol: 'pin',
                    symbolSize: 20,
                    symbolRotate: tb.top_or_bottom === 'B' ? 180 : 0,
                    itemStyle: {
                        color: tb.top_or_bottom === 'T' ? '#4caf50' : '#d14a61'
                    },
                    label: {
                        show: true,
                        formatter: tb.top_or_bottom,
                        color: '#fff',
                        fontWeight: 'bold'
                    }
                }
            })
            .filter(Boolean)

        // 更新K线series的markPoint
        if (!chartTrendOption.value.series[0].markPoint) {
            chartTrendOption.value.series[0].markPoint = { data: [] }
        }
        chartTrendOption.value.series[0].markPoint.data = markPoints
    } catch (error) {
        console.error('Failed to fetch tops/bottoms:', error)
    }
}

// 更新股票k线图顶和底标记
const renderTopBottomSymbol = (tradeChartData, entryPoints) => {
    //添加series
    // mixChartOption.series.slice(7,1);
    var ohlcDateLabel = tradeChartData.categoryData;
    var ohlc = tradeChartData.values;
    var markData = [];

    entryPoints.forEach(entryPoint => {
        if (entryPoint[0] != null) {
            var indexTradeDate = ohlcDateLabel.indexOf(entryPoint[2]);
            if (entryPoint[1] == "B") {
                markData.push(
                    {
                        coord: [entryPoint[2], ohlc[indexTradeDate][2]],
                        value: "B",
                        symbol: "pin",
                        symbolSize: 20,
                        symbolRotate: 180,
                        symbolOffset: [0, 5],
                        itemStyle: {
                            //设置标记点的样式
                            normal: { color: "red" },
                        },
                    }
                );
            }
            if (entryPoint[1] == "T") {
                markData.push(
                    {
                        coord: [entryPoint[2], ohlc[indexTradeDate][3]],
                        value: "S",
                        symbol: "pin",
                        symbolSize: 20,
                        // symbolRotate: 180,
                        itemStyle: {
                            //设置标记点的样式
                            normal: { color: "green" },
                        },
                    }
                );
            }
        }
    });

    var tradeOption =
    {
        series: [
            {
                id: 'CLOSE',
                markPoint: {
                    data: markData,
                }
            }
        ]
    };
}

// 在fetchTradingHistory后调用
watch(
    () => ({ topBtmSwitch: stockChartFilterStore.topBottomSwitch }),
    () => {
        renderTopsBottomsOnTrendChart()
    }
)

// 事件处理
// 处理周期，时常，顶底和模型切换导致stock chart的变化
// 处理成交量和成交额的切换
function onVolOptionChange() {
    // Update the chartVolOption based on volOption
    // If 'amount', use vol.value; if 'vol', use amount (if available in your data)
    // Here, assuming 'vol' is volume and 'amount' is not available, so just use vol.value for both
    // If you have 'amount' in your data, adjust accordingly

    if (volOption.value === 'vol') {
        chartVolOption.value.series[0].data = vol.value
        chartVolOption.value.series[0].name = '成交量'
    } else if (volOption.value === 'amount') {
        // If you have amount data, use it here. Otherwise, just use vol.value as a placeholder.
        chartVolOption.value.series[0].data = amount.value
        chartVolOption.value.series[0].name = '成交额'
    }
}

// 处理技术指标切换
function onTechOptionChange() {
    const techMap = {
        macd: [
            { name: 'MACD', key: 'macd' },
            { name: 'DIF', key: 'macd_dif' },
            { name: 'DEA', key: 'macd_dea' }
        ],
        kdj: [
            { name: 'K', key: 'kdj_k' },
            { name: 'D', key: 'kdj_d' },
            { name: 'J', key: 'kdj_j' }
        ],
        rsi: [
            { name: 'RSI', key: 'rsi_6' },
            { name: 'RSI12', key: 'rsi_12' },
            { name: 'RSI24', key: 'rsi_24' }
        ],
        cci: [
            { name: 'CCI', key: 'cci' }
        ]
    }

    const series = (techMap[techOption.value] || [])
        .filter(item => indicData.value[item.key])
        .map(item => ({
            name: item.name,
            type: 'line',
            data: indicData.value[item.key],
            smooth: true,
            showSymbol: false
        }))

    // Directly assign new series array to avoid leftover data
    chartTechOption.value.series = []
    chartTechOption.value.series = series
}
// 处理adj变化事件
// function onAdjPriceOptionChange() {
//     fetchTradingHistory(stockStore.tsCode, stockChartFilterStore.freq, adjPriceOption.value, stockChartFilterStore.period)
// }

// Watch volOption and update chart when changed
import { watch } from 'vue'
import { sl } from 'element-plus/es/locales.mjs'
// watch(adjPriceOption, onAdjPriceOptionChange)
// watch(volOption, onVolOptionChange, { immediate: true })
// watch(techOption, onTechOptionChange, { immediate: true })
watch(
    () => ({
        ts_code: stockStore.tsCode,
        freq: stockChartFilterStore.freq,
        period: stockChartFilterStore.period,
        adj: adjPriceOption.value
    }),
    (newVal) => {
        if (!String(newVal.ts_code || '').trim()) {
            return
        }
        fetchStockStatus(newVal.ts_code)
        fetchTradingHistory(newVal.ts_code, newVal.freq, newVal.adj, newVal.period)
        if (shouldRenderBottom.value) {
            fetchFundamentalHistory(newVal.ts_code, newVal.freq, newVal.period)
        }
        renderTopsBottomsOnTrendChart(newVal.ts_code, stockChartFilterStore.model, newVal.freq, newVal.period, stockChartFilterStore.topBottomSwitch)
    }
)

watch(
    () => bottomFundamentalsExpanded.value,
    (expanded) => {
        if (!expanded || !displayEmbed.value || !shouldShowBottom.value) {
            return
        }
        if (!String(stockStore.tsCode || '').trim()) {
            return
        }
        fetchFundamentalHistory(stockStore.tsCode, stockChartFilterStore.freq, stockChartFilterStore.period)
    }
)

watch(
    () => ({
        tsCode: stockStore.tsCode,
        enabled: stockStore.positionTriggerLineEnabled,
        triggerTsCode: stockStore.positionTriggerTsCode,
        upgradePrice: stockStore.positionTriggerUpgradePrice,
        downgradePrice: stockStore.positionTriggerDowngradePrice,
    }),
    (state) => {
        applyPositionTriggerLines(state.tsCode)
    },
    { deep: false }
)


watch([selectedFreqEmbed, selectedPeriodEmbed], ([newFreq, newPeriod]) => {
    if (!displayEmbed.value) {
        return
    }
    const currentToken = ++embedSwitchRequestToken
    nextTick().then(() => {
        requestAnimationFrame(() => {
            if (currentToken !== embedSwitchRequestToken) {
                return
            }
            if (stockChartFilterStore.freq !== newFreq) {
                stockChartFilterStore.setFreq(newFreq)
            }
            if (stockChartFilterStore.period !== newPeriod) {
                stockChartFilterStore.setPeriod(newPeriod)
            }
        })
    })
})



// Call the function and set up chart group on mount
onMounted(() => {
    if (!String(stockStore.tsCode || '').trim()) {
        return
    }
    trendZoomRange.value = readTrendZoomRange()
    applyTrendZoomToOption()
    if (displayEmbed.value) {
        selectedFreqEmbed.value = stockChartFilterStore.freq
        selectedPeriodEmbed.value = stockChartFilterStore.period
    }
    fetchStockStatus(stockStore.tsCode)
    fetchTradingHistory(
        stockStore.tsCode,
        stockChartFilterStore.freq,
        adjPriceOption.value,
        stockChartFilterStore.period
    )
    if (shouldRenderBottom.value) {
        fetchFundamentalHistory(
            stockStore.tsCode,
            stockChartFilterStore.freq
        )
    }
    renderTopsBottomsOnTrendChart(
        stockStore.tsCode,
        stockChartFilterStore.model,
        stockChartFilterStore.freq,
        stockChartFilterStore.period,
        stockChartFilterStore.topBottomSwitch
    )

        // 绑定 group 到每个 v-chart
        ;[trendChartRef, techChartRef].forEach(refItem => {
            if (refItem.value && refItem.value.chart) {
                refItem.value.chart.group = chartGroup
            }
        })
    echarts.connect(chartGroup)
        // 绑定 group 到每个 v-chart
        ;[
            techChartRef,
            peChartRef,
            peTTMChartRef,
            psChartRef,
            psTTMChartRef,
            pbChartRef,
            turnoverChartRef,
            turnoverFChartRef,
            volRatioChartRef
        ].forEach(refItem => {
            if (refItem.value && refItem.value.chart) {
                refItem.value.chart.group = chartGroup
            }
        })
    echarts.connect(chartGroup)

    nextTick(() => {
        bindTrendHoverSync()
    })
})

onBeforeUnmount(() => {
    const chart = trendChartRef.value?.chart
    if (!chart) return
    chart.off('updateAxisPointer', onTrendAxisPointer)
    chart.off('datazoom', onTrendDataZoom)
})

</script>

<style scoped>
.stock-chart-container {
    width: 100%;
    /* height: 800px; */
    display: flex;
    justify-content: center;
    align-items: center;
}

.echart-placeholder {
    width: 100%;
    height: 100%;
    background: #f5f5f5;
    /* border: 1px dashed #ccc; */
}

.chip-metrics-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    margin: 0 4px 8px;
    font-size: 12px;
    color: #606266;
}

.fundamental-section {
    content-visibility: auto;
    contain-intrinsic-size: 1400px;
}

.chart-skeleton {
    width: 100%;
    border-radius: 6px;
}

.chart-skeleton-400 {
    height: 400px;
}

.chart-skeleton-200 {
    height: 200px;
}
</style>
