<template>

    <el-affix :offset="75">
        <el-card class="watchlist-card" :style="cardStyle" v-loading="loading">
            <template #header>
                <div class="card-header">
                    <el-tabs v-model="activeTab" @tab-change="handleTabChange" class="watchlist-tabs">
                        <el-tab-pane name="groupA" label="组合" />
                        <el-tab-pane name="groupB" label="市场" />
                    </el-tabs>
                    <el-radio-group
                        v-if="activeTab === 'groupA'"
                        v-model="market"
                        size="small"
                        @change="handleMarketChange"
                        class="market-radio-group"
                    >
                        <el-radio-button label="HO">持</el-radio-button>
                        <el-radio-button label="WL">自</el-radio-button>
                        <el-radio-button label="RESULT">选</el-radio-button>
                        <el-radio-button label="OBS">
                            <span class="watch-observe-label">
                                <el-icon><View /></el-icon>
                                <span>观</span>
                            </span>
                        </el-radio-button>
                    </el-radio-group>
                    <el-radio-group
                        v-else
                        v-model="market"
                        size="small"
                        @change="handleMarketChange"
                        class="market-radio-group"
                    >
                        <el-radio-button label="6">沪市</el-radio-button>
                        <el-radio-button label="0">深市</el-radio-button>
                        <el-radio-button label="30">创业</el-radio-button>
                        <el-radio-button label="688">科创</el-radio-button>
                    </el-radio-group>
                    <div v-if="market === 'RESULT'" class="result-kind-row">
                        <el-radio-group v-model="selectedResultMarket" size="small" @change="handleResultMarketChange">
                            <el-radio-button label="SH">沪</el-radio-button>
                            <el-radio-button label="SZ">深</el-radio-button>
                            <el-radio-button label="CYB">创</el-radio-button>
                            <el-radio-button label="STAR">科</el-radio-button>
                        </el-radio-group>
                    </div>
                    <div v-if="market === 'RESULT'" class="result-kind-row">
                        <el-radio-group v-model="selectedResultSeason" size="small" @change="handleResultSeasonChange">
                            <el-radio-button label="Q1">Q1</el-radio-button>
                            <el-radio-button label="H1">H1</el-radio-button>
                            <el-radio-button label="Q3">Q3</el-radio-button>
                            <el-radio-button label="FY">FY</el-radio-button>
                        </el-radio-group>
                    </div>
                    <div v-if="market === 'WL' || market === 'OBS'" class="result-kind-row">
                        <el-radio-group v-model="selectedWatchlistMarket" size="small" @change="handleWatchlistMarketChange">
                            <el-radio-button label="SH">沪</el-radio-button>
                            <el-radio-button label="SZ">深</el-radio-button>
                            <el-radio-button label="CYB">创</el-radio-button>
                            <el-radio-button label="STAR">科</el-radio-button>
                        </el-radio-group>
                    </div>
                </div>
            </template>
            <el-scrollbar ref="watchlistScrollbarRef" class="watchlist-scroll">
                <div v-if="loading && watchlist.length === 0" class="watchlist-skeleton-list">
                    <div v-for="item in skeletonItems" :key="item" class="watchlist-skeleton-card">
                        <el-skeleton animated>
                            <template #template>
                                <div class="watchlist-skeleton-line watchlist-skeleton-line--title"></div>
                                <div class="watchlist-skeleton-tag-row">
                                    <el-skeleton-item variant="button" class="watchlist-skeleton-chip" />
                                    <el-skeleton-item variant="button" class="watchlist-skeleton-chip watchlist-skeleton-chip--wide" />
                                </div>
                                <div class="watchlist-skeleton-line watchlist-skeleton-line--meta"></div>
                                <div class="watchlist-skeleton-line watchlist-skeleton-line--meta short"></div>
                            </template>
                        </el-skeleton>
                    </div>
                </div>
                <div
                    v-else
                    v-for="(stock, idx) in visibleWatchlist"
                    :key="stock.ts_code"
                    :ref="setStockRowRef(stock.ts_code)"
                    :data-ts-code="stock.ts_code"
                    class="text item"
                    :class="{ 'active-stock-item': isActiveStock(stock) }"
                    style="font-size: 12px;"
                >
                    <el-row :gutter="0">
                        <el-col :span="24">
                            <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
                                <el-link type="primary" href="#" @click="handleStockClick(stock.name, stock.ts_code, stock.basic_info.website)"
                                    underline="never">
                                    {{ stock.name + ' | ' + stock.ts_code }}
                                </el-link>
                                <el-tag v-if="stock.recent_report_badge" type="warning" effect="plain" size="small">
                                    {{ formatRecentReportLabel(stock.recent_report_label) }}
                                </el-tag>
                                <span
                                    v-if="stock.forecast_badge"
                                    style="display: inline-flex; cursor: pointer;"
                                    role="button"
                                    tabindex="0"
                                    @click.stop="openForecastDialog(stock)"
                                    @keydown.enter.stop.prevent="openForecastDialog(stock)"
                                    @keydown.space.stop.prevent="openForecastDialog(stock)"
                                >
                                    <el-tag
                                        type="danger"
                                        effect="plain"
                                        size="small"
                                    >
                                        预
                                    </el-tag>
                                </span>
                            </div>
                        </el-col>
                        <el-col :span="24">
                            <div class="result-tag-row">
                                <el-tag
                                    :class="valuationToneClassBySignal(getTraditionalSignalLabel(stock))"
                                    round
                                    effect="light"
                                    type="info"
                                    size="small"
                                >
                                    传统: <span :class="signalTokenClass(getTraditionalSignalLabel(stock))">{{ getSignalDisplayLabel(getTraditionalSignalLabel(stock)) }}</span>
                                    <span class="valuation-side-meta">
                                        | <span>{{ getTraditionalScoreLabel(stock) }}</span>
                                        | <span :class="riskTokenClass(getTraditionalRiskLabel(stock))">{{ getRiskLevelDisplayLabel(getTraditionalRiskLabel(stock)) }}</span>
                                    </span>
                                </el-tag>
                                <el-tag
                                    :class="valuationToneClassBySignal(getPredictiveSignalLabel(stock))"
                                    round
                                    effect="light"
                                    type="info"
                                    size="small"
                                >
                                    预测: <span :class="signalTokenClass(getPredictiveSignalLabel(stock))">{{ getSignalDisplayLabel(getPredictiveSignalLabel(stock)) }}</span>
                                    <span class="valuation-side-meta">
                                        | <span>{{ getPredictiveScoreLabel(stock) }}</span>
                                        | <span :class="riskTokenClass(getPredictiveRiskLabel(stock))">{{ getRiskLevelDisplayLabel(getPredictiveRiskLabel(stock)) }}</span>
                                    </span>
                                </el-tag>
                            </div>
                            <div v-if="getTraditionalContextLabel(stock)" class="valuation-report-hint">
                                传统口径 {{ getTraditionalContextLabel(stock) }}
                            </div>
                            <div v-if="hasSincePickReturns(stock)" class="valuation-report-hint">
                                今 <span :class="valuationTextClass(getSincePickCurrentPct(stock))">{{ formatSignedPct(getSincePickCurrentPct(stock)) }}%</span>
                                / 高 <span :class="valuationTextClass(getSincePickPeakPct(stock))">{{ formatSignedPct(getSincePickPeakPct(stock)) }}%</span>
                                / 低 <span :class="valuationTextClass(getSincePickTroughPct(stock))">{{ formatSignedPct(getSincePickTroughPct(stock)) }}%</span>
                            </div>
                        </el-col>
                        <el-col :span="24">
                            <div style="margin-left: 2px; color: #888;">
                                <div v-if="stock.basic_info.website">
                                    <span>官网: </span>
                                    <el-link
                                        :href="stock.basic_info.website.startsWith('http') ? stock.basic_info.website : 'https://' + stock.basic_info.website"
                                        target="_blank" type="primary" style="font-size: 12px;">{{ "https://" +
                                            stock.basic_info.website }}</el-link>
                                </div>
                            </div>
                        </el-col>
                        <el-col :span="24">
                            <div style="margin-left: 2px; color: #888;">
                                <div v-if="stock.basic_info.main_business">
                                    <span>主营: </span>
                                    <span>{{ truncateMainBusiness(stock.basic_info.main_business) }}</span>
                                </div>
                            </div>
                        </el-col>
                    </el-row>
                    <el-divider v-if="idx !== visibleWatchlist.length - 1" style="margin: 8px 0;" />
                </div>
            </el-scrollbar>
            <template #footer>
                <div v-if="market === 'RESULT'" class="result-footer-secondary-filters">
                    <el-date-picker
                        v-model="selectedResultDate"
                        type="date"
                        value-format="YYYY-MM-DD"
                        format="YYYY-MM-DD"
                        placeholder="最新"
                        size="small"
                        style="width: 132px;"
                        @change="handleResultDateChange"
                    >
                        <template #default="cell">
                            <div class="result-date-cell" :class="{ 'result-date-cell--marked': hasResultDate(cell) }">
                                <span>{{ cell.text }}</span>
                                <span v-if="hasResultDate(cell)" class="result-date-cell__dot"></span>
                            </div>
                        </template>
                    </el-date-picker>
                    <el-radio-group v-model="selectedResultKind" size="small" @change="handleResultKindChange">
                        <el-radio-button label="traditional">传统</el-radio-button>
                        <el-radio-button label="predictive">预测</el-radio-button>
                    </el-radio-group>
                    <span style="font-size: 12px; color: #909399;">风格</span>
                    <el-select v-model="selectedResultStyle" size="small" style="width: 128px;" @change="handleResultStyleChange">
                        <el-option label="平衡" value="BALANCED" />
                        <el-option label="保守" value="CONSERVATIVE" />
                        <el-option label="激进" value="AGGRESSIVE" />
                    </el-select>
                    <el-popover
                        v-if="resultStyleParamEntries.length"
                        trigger="click"
                        placement="top"
                        width="480"
                    >
                        <template #reference>
                            <el-button type="primary" link size="small">查看参数</el-button>
                        </template>
                        <div class="result-style-popover-title">{{ resultStylePopoverTitle }}</div>
                        <div class="result-style-param-list">
                            <el-tag
                                v-for="entry in resultStyleParamEntries"
                                :key="entry"
                                size="small"
                                effect="plain"
                            >
                                {{ entry }}
                            </el-tag>
                        </div>
                    </el-popover>
                </div>
                <div class="watchlist-meta-row watchlist-footer-meta-row">
                    <span>第 {{ currentPage }}/{{ totalPages }} 页 · 本页 {{ loadedCount }} 条 · 共 {{ totalCount || 0 }} 条</span>
                    <span v-if="resumeMarker && resumeMarker.market === market">上次: 第{{ resumeMarker.page || 1 }}页 · {{ resumeMarker.name }} | {{ resumeMarker.ts_code }}</span>
                </div>
                <div class="watchlist-footer-actions">
                    <div class="watchlist-footer-quick-actions">
                        <el-switch
                            v-model="resumeLocateOnly"
                            size="small"
                            inline-prompt
                            active-text="仅定位"
                            inactive-text="自动翻页"
                        />
                        <el-button
                            type="primary"
                            plain
                            size="small"
                            @click="bookmarkCurrentStock"
                            :disabled="!stockTradeStore.tsCode"
                        >
                            设书签
                        </el-button>
                        <el-button
                            type="info"
                            plain
                            size="small"
                            @click="clearResumeMarker"
                            :disabled="!resumeMarker"
                        >
                            清除书签
                        </el-button>
                        <el-button
                            type="warning"
                            plain
                            size="small"
                            @click="restoreLastViewedStock"
                            :disabled="!resumeMarker"
                        >
                            恢复上次
                        </el-button>
                        <el-button type="default" size="small" :loading="loading" @click="refreshCurrentMarketLoadedStocks">
                            刷新当前市场
                        </el-button>
                    </div>
                    <div class="watchlist-footer-pagination">
                        <el-pagination
                            small
                            background
                            layout="prev, pager, next"
                            :current-page="currentPage"
                            :page-size="pageSize"
                            :total="totalCount"
                            :pager-count="5"
                            @current-change="handlePageChange"
                        />
                    </div>
                </div>
            </template>
        </el-card>
    </el-affix>

    <el-dialog
        v-model="forecastDialogVisible"
        title="业绩预告提示"
        width="560px"
    >
        <div v-if="forecastDialogStock" style="display: flex; flex-direction: column; gap: 8px; font-size: 13px; line-height: 1.7;">
            <div style="color: #606266;">
                {{ forecastDialogStock.name }} | {{ forecastDialogStock.ts_code }}
            </div>
            <div style="color: #303133;">
                {{ forecastDialogStock.forecast_narrative || '暂无预告文案' }}
            </div>
            <div v-if="forecastDialogStock.forecast_lite_estimate" style="padding: 8px 10px; border: 1px solid #ebeef5; border-radius: 6px; background: #fafafa; color: #606266;">
                <div>轻量提示: {{ forecastDialogStock.forecast_lite_estimate.implied_signal || '-' }} / {{ formatForecastLiteReturn(forecastDialogStock.forecast_lite_estimate.implied_return_pct) }}</div>
                <div>置信度: {{ forecastDialogStock.forecast_lite_estimate.confidence || '-' }}</div>
                <div>依据: {{ forecastDialogStock.forecast_lite_estimate.basis || '-' }}</div>
                <div style="color: #909399;">{{ forecastDialogStock.forecast_lite_estimate.note || '' }}</div>
            </div>
        </div>
    </el-dialog>

    <!-- <el-backtop :right="100" :bottom="100" /> -->
</template>

<script setup>
import { computed, inject, ref, onBeforeUnmount, onMounted, watch, nextTick } from 'vue';
import axios from 'axios';
// Element Plus
import { ElAffix, ElRow, ElCol, ElButton, ElCard, ElDatePicker, ElDialog, ElDivider, ElIcon, ElLink, ElMessage, ElOption, ElPagination, ElPopover, ElRadioButton, ElRadioGroup, ElScrollbar, ElSelect, ElSkeleton, ElSkeletonItem, ElSwitch, ElTabPane, ElTabs, ElTag } from 'element-plus';
import { View } from '@element-plus/icons-vue';
import { useStockTradeStore } from '../stores/stockTradeStore';
import { prefetchValuationMethodsWithSharedCache } from '../utils/valuationQuickViewCache';

const stockTradeStore = useStockTradeStore();

const market = ref('HO');
const activeTab = ref('groupA');
const selectedResultDate = ref('');
const selectedResultKind = ref('traditional');
const selectedResultStyle = ref('BALANCED');
const selectedResultMarket = ref('SH');
const selectedResultSeason = ref('Q1');
const selectedWatchlistMarket = ref('SH');
const resultStyleStrategy = ref(null)
const baseURL = inject('baseURL');
const watchlist = ref([]);
const resultAvailableDates = ref([])
const resultAvailableDateSet = computed(() => new Set(resultAvailableDates.value))

const currentPage = ref(1)
const pageSize = ref(25)
const totalCount = ref(0)
const loading = ref(false)
const loadedCount = computed(() => watchlist.value.length)
const totalPages = computed(() => Math.max(1, Math.ceil((Number(totalCount.value) || 0) / pageSize.value)))
const pageLoadCostMs = ref(0)
const enableListValuationPrefetch = computed(() => market.value === 'HO')
const viewportHeight = ref(typeof window !== 'undefined' ? window.innerHeight : 900)
const skeletonItems = [1, 2, 3, 4, 5]
const traditionalPctOverrideMap = ref({})
const traditionalScoreOverrideMap = ref({})
const traditionalRiskOverrideMap = ref({})
const predictiveSignalOverrideMap = ref({})
const predictiveScoreOverrideMap = ref({})
const predictiveRiskOverrideMap = ref({})
const traditionalPctCache = new Map()
const traditionalPctPending = new Map()
const predictiveSignalCache = new Map()
const predictiveSignalPending = new Map()
const watchlistScrollbarRef = ref(null)
const stockRowRefMap = new Map()
const visibleStockCodeSet = new Set()
const prefetchedVisibleStockSet = new Set()
let visibleStockObserver = null
const VISIBLE_PREFETCH_LIMIT = 6
const PAGE_PREFETCH_CACHE_LIMIT = 24
const ALIGN_OVERRIDE_LIMIT = 8
const RESULT_STAGE_SIZE = 8
const watchlistPageCache = new Map()
const watchlistPagePrefetchPending = new Map()
const watchlistFetchToken = ref(0)
const resultHydrating = ref(false)
const forecastDialogVisible = ref(false)
const forecastDialogStock = ref(null)

const RESUME_MARKER_KEY = 'smartinvestor_watchlist_resume_v1'
const RESUME_MODE_KEY = 'smartinvestor_watchlist_resume_mode_v1'
const resumeMarkerStore = ref({})
const resumeMarker = ref(null)
const resumeLocateOnly = ref(false)
const groupAMarkets = new Set(['HO', 'WL', 'RESULT', 'OBS'])
const groupBMarkets = new Set(['6', '0', '30', '688'])

const getDateCellKey = (cell) => {
    if (!cell) {
        return ''
    }
    const dayjsObj = cell.dayjs
    if (!dayjsObj || typeof dayjsObj.format !== 'function') {
        return ''
    }
    return dayjsObj.format('YYYY-MM-DD')
}

const hasResultDate = (cell) => {
    const key = getDateCellKey(cell)
    return Boolean(key && resultAvailableDateSet.value.has(key))
}

const cardStyle = computed(() => ({
    maxWidth: '480px',
    height: `${Math.max(460, viewportHeight.value - 96)}px`,
}))

const updateViewportHeight = () => {
    if (typeof window === 'undefined') {
        return
    }
    viewportHeight.value = window.innerHeight || 900
}

function normalizeMarket(value) {
    const normalized = String(value || '').trim().toUpperCase()
    if (normalized === '60') {
        return '6'
    }
    if (normalized === '00') {
        return '0'
    }
    if (normalized === '68') {
        return '688'
    }
    return normalized
}

function syncActiveTab(currentMarket) {
    if (groupAMarkets.has(currentMarket)) {
        activeTab.value = 'groupA'
    } else if (groupBMarkets.has(currentMarket)) {
        activeTab.value = 'groupB'
    }
}

function normalizeResultKind(value) {
    const normalized = String(value || '').trim().toLowerCase()
    return normalized === 'predictive' ? 'predictive' : 'traditional'
}

function normalizeResultStyle(value) {
    const normalized = String(value || '').trim().toUpperCase()
    if (['CONSERVATIVE', 'BALANCED', 'AGGRESSIVE'].includes(normalized)) {
        return normalized
    }
    return 'BALANCED'
}

function normalizeResultMarket(value) {
    const normalized = String(value || '').trim().toUpperCase()
    if (['SH', 'SZ', 'CYB', 'STAR'].includes(normalized)) {
        return normalized
    }
    return 'SH'
}

function normalizeResultSeason(value) {
    const normalized = String(value || '').trim().toUpperCase()
    if (['Q1', 'H1', 'Q3', 'FY'].includes(normalized)) {
        return normalized
    }
    return 'Q1'
}

function normalizeWatchlistMarket(value) {
    const normalized = String(value || '').trim().toUpperCase()
    if (['SH', 'SZ', 'CYB', 'STAR'].includes(normalized)) {
        return normalized
    }
    return 'SH'
}

function extractTsCodeDigits(tsCode) {
    const normalized = String(tsCode || '').trim().toUpperCase()
    if (!normalized) {
        return ''
    }
    const suffixMatch = normalized.match(/^(\d{6})\.(SH|SZ)$/)
    if (suffixMatch) {
        return suffixMatch[1]
    }
    const prefixMatch = normalized.match(/^(SH|SZ)(\d{6})$/)
    if (prefixMatch) {
        return prefixMatch[2]
    }
    const plainMatch = normalized.match(/^(\d{6})$/)
    if (plainMatch) {
        return plainMatch[1]
    }
    return ''
}

function inferTsCodeMarketBucket(tsCode) {
    const digits = extractTsCodeDigits(tsCode)
    if (!digits) {
        return ''
    }
    if (digits.startsWith('688')) {
        return 'STAR'
    }
    if (digits.startsWith('30')) {
        return 'CYB'
    }
    if (digits.startsWith('60')) {
        return 'SH'
    }
    if (digits.startsWith('0')) {
        return 'SZ'
    }
    return ''
}

const visibleWatchlist = computed(() => {
    if (market.value !== 'WL' && market.value !== 'OBS') {
        return watchlist.value
    }
    const selectedBucket = normalizeWatchlistMarket(selectedWatchlistMarket.value)
    return watchlist.value.filter((item) => inferTsCodeMarketBucket(item?.ts_code) === selectedBucket)
})

function normalizeTsCodeForPrefetch(tsCode) {
    return String(tsCode || '').trim().toUpperCase()
}

function resolveResultUndervalueScore(stock) {
    const direct = Number(stock?.undervalue_score)
    if (Number.isFinite(direct)) {
        return direct
    }
    const directValuation = Number(stock?.valuation_score)
    if (Number.isFinite(directValuation)) {
        return directValuation
    }
    const metaValue = Number(stock?.result_meta?.undervalue_score)
    if (Number.isFinite(metaValue)) {
        return metaValue
    }
    const metaValuation = Number(stock?.result_meta?.valuation_score)
    if (Number.isFinite(metaValuation)) {
        return metaValuation
    }
    return null
}

function getWatchlistScrollWrapElement() {
    const scrollbarRef = watchlistScrollbarRef.value
    const hostEl = scrollbarRef && scrollbarRef.$el ? scrollbarRef.$el : null
    if (!hostEl || typeof hostEl.querySelector !== 'function') {
        return null
    }
    return hostEl.querySelector('.el-scrollbar__wrap')
}

function prefetchStockValuationByCode(tsCode) {
    if (!enableListValuationPrefetch.value) {
        return
    }
    const normalizedTsCode = normalizeTsCodeForPrefetch(tsCode)
    if (!normalizedTsCode || !baseURL) {
        return
    }
    const key = `${normalizedTsCode}|0.1|AUTO`
    if (prefetchedVisibleStockSet.has(key)) {
        return
    }
    prefetchedVisibleStockSet.add(key)
    prefetchValuationMethodsWithSharedCache(String(baseURL), normalizedTsCode, '0.1', '')
}

function prefetchVisibleStocks() {
    if (!enableListValuationPrefetch.value) {
        return
    }
    const prefetchQueue = []
    for (const stock of visibleWatchlist.value) {
        const code = normalizeTsCodeForPrefetch(stock?.ts_code)
        if (!code) {
            continue
        }
        if (visibleStockCodeSet.has(code)) {
            prefetchQueue.push(code)
        }
        if (prefetchQueue.length >= VISIBLE_PREFETCH_LIMIT) {
            break
        }
    }
    if (!prefetchQueue.length) {
        for (const stock of visibleWatchlist.value.slice(0, VISIBLE_PREFETCH_LIMIT)) {
            const code = normalizeTsCodeForPrefetch(stock?.ts_code)
            if (code) {
                prefetchQueue.push(code)
            }
        }
    }
    for (const code of prefetchQueue) {
        prefetchStockValuationByCode(code)
    }
}

function alignSingleStockOverrides(stock, normalizedMarket) {
    if (!stock || normalizedMarket === 'RESULT') {
        return
    }
    const code = String(stock?.ts_code || '').trim().toUpperCase()
    if (!code) {
        return
    }
    const reportType = resolveWatchlistEarningsReportType(stock)
    fetchTraditionalPctOverride(code, reportType).then((snapshot) => {
        if (!snapshot || typeof snapshot !== 'object') {
            return
        }
        const nextPct = Number(snapshot?.pct)
        if (Number.isFinite(nextPct)) {
            traditionalPctOverrideMap.value = {
                ...traditionalPctOverrideMap.value,
                [code]: nextPct,
            }
        }
        const nextScore = Number(snapshot?.score)
        if (Number.isFinite(nextScore)) {
            traditionalScoreOverrideMap.value = {
                ...traditionalScoreOverrideMap.value,
                [code]: nextScore,
            }
        }
        const nextRisk = normalizeDisplayToken(snapshot?.risk)
        if (nextRisk) {
            traditionalRiskOverrideMap.value = {
                ...traditionalRiskOverrideMap.value,
                [code]: nextRisk,
            }
        }
    })

    fetchPredictiveSignalOverride(code, reportType).then((snapshot) => {
        if (!snapshot || typeof snapshot !== 'object') {
            return
        }
        const action = normalizeDisplayToken(snapshot?.action)
        if (action) {
            predictiveSignalOverrideMap.value = {
                ...predictiveSignalOverrideMap.value,
                [code]: action,
            }
        }
        const score = Number(snapshot?.score)
        if (Number.isFinite(score)) {
            predictiveScoreOverrideMap.value = {
                ...predictiveScoreOverrideMap.value,
                [code]: score,
            }
        }
        const risk = normalizeDisplayToken(snapshot?.risk)
        if (risk) {
            predictiveRiskOverrideMap.value = {
                ...predictiveRiskOverrideMap.value,
                [code]: risk,
            }
        }
    })
}

function alignVisibleStocks() {
    const normalizedMarket = normalizeMarket(market.value)
    if (normalizedMarket === 'RESULT') {
        return
    }
    if (!visibleStockCodeSet.size) {
        return
    }
    for (const code of visibleStockCodeSet) {
        const stock = visibleWatchlist.value.find((item) => String(item?.ts_code || '').trim().toUpperCase() === code)
        if (stock) {
            alignSingleStockOverrides(stock, normalizedMarket)
        }
    }
}

function observeStockRowElements() {
    if (!visibleStockObserver) {
        return
    }
    visibleStockObserver.disconnect()
    for (const element of stockRowRefMap.values()) {
        if (element && typeof visibleStockObserver.observe === 'function') {
            visibleStockObserver.observe(element)
        }
    }
}

function teardownVisibleStockObserver() {
    if (visibleStockObserver) {
        visibleStockObserver.disconnect()
        visibleStockObserver = null
    }
    visibleStockCodeSet.clear()
}

function setupVisibleStockObserver() {
    teardownVisibleStockObserver()
    if (typeof window === 'undefined' || typeof IntersectionObserver === 'undefined') {
        prefetchVisibleStocks()
        alignVisibleStocks()
        return
    }
    const root = getWatchlistScrollWrapElement()
    visibleStockObserver = new IntersectionObserver(
        (entries) => {
            for (const entry of entries) {
                const code = normalizeTsCodeForPrefetch(entry?.target?.dataset?.tsCode)
                if (!code) {
                    continue
                }
                if (entry.isIntersecting) {
                    visibleStockCodeSet.add(code)
                } else {
                    visibleStockCodeSet.delete(code)
                }
            }
            prefetchVisibleStocks()
            alignVisibleStocks()
        },
        {
            root,
            threshold: 0.05,
        }
    )
    observeStockRowElements()
    prefetchVisibleStocks()
    alignVisibleStocks()
}

const setStockRowRef = (tsCode) => (element) => {
    const code = normalizeTsCodeForPrefetch(tsCode)
    if (!code) {
        return
    }
    if (!element) {
        stockRowRefMap.delete(code)
        visibleStockCodeSet.delete(code)
        return
    }
    stockRowRefMap.set(code, element)
    if (visibleStockObserver && typeof visibleStockObserver.observe === 'function') {
        visibleStockObserver.observe(element)
    }
}

function formatRecentReportLabel(value) {
    const normalized = String(value || '').trim().toUpperCase()
    if (!normalized) {
        return '更新'
    }
    if (normalized === 'EXP') {
        return '快'
    }
    return normalized
}

function formatForecastLiteReturn(value) {
    const number = Number(value)
    if (!Number.isFinite(number)) {
        return '-'
    }
    return `${number >= 0 ? '+' : ''}${number.toFixed(2)}%`
}

function openForecastDialog(stock) {
    if (!stock) {
        return
    }
    console.debug('watchlist.forecast_dialog.open', {
        ts_code: stock.ts_code,
        forecast_badge: stock.forecast_badge,
    })
    forecastDialogStock.value = stock
    forecastDialogVisible.value = true
}

function normalizeResumeMarker(value) {
    if (!value || !value.ts_code || !value.market) {
        return null
    }
    const normalizedMarket = normalizeMarket(value.market)
    return {
        market: normalizedMarket,
        page: Math.max(1, Number(value.page || 1)),
        ts_code: String(value.ts_code || '').toUpperCase(),
        name: String(value.name || ''),
        website: String(value.website || ''),
        updated_at: Number(value.updated_at || Date.now()),
    }
}

function readResumeMarkerStore() {
    if (typeof window === 'undefined') {
        return {}
    }
    try {
        const raw = window.localStorage.getItem(RESUME_MARKER_KEY)
        if (!raw) {
            return {}
        }
        const parsed = JSON.parse(raw)
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
            return {}
        }

        // Backward compatibility: previous schema stored a single marker object.
        if (parsed.ts_code && parsed.market) {
            const single = normalizeResumeMarker(parsed)
            return single ? { [single.market]: single } : {}
        }

        const nextStore = {}
        for (const [marketKey, markerValue] of Object.entries(parsed)) {
            const normalized = normalizeResumeMarker(markerValue)
            if (!normalized) {
                continue
            }
            const normalizedMarket = normalizeMarket(normalized.market || marketKey)
            nextStore[normalizedMarket] = {
                ...normalized,
                market: normalizedMarket,
            }
        }
        return nextStore
    } catch {
        return {}
    }
}

function writeResumeMarkerStore(store) {
    resumeMarkerStore.value = store && typeof store === 'object' ? store : {}
    if (typeof window === 'undefined') {
        return
    }
    try {
        if (Object.keys(resumeMarkerStore.value).length) {
            window.localStorage.setItem(RESUME_MARKER_KEY, JSON.stringify(resumeMarkerStore.value))
        } else {
            window.localStorage.removeItem(RESUME_MARKER_KEY)
        }
    } catch {
        // ignore localStorage failures
    }
}

function readResumeMarker() {
    const normalizedMarket = normalizeMarket(market.value)
    return resumeMarkerStore.value[normalizedMarket] || null
}

function writeResumeMarker(marker) {
    const normalizedMarket = normalizeMarket(market.value)
    const nextStore = { ...resumeMarkerStore.value }
    if (marker) {
        const normalizedMarker = normalizeResumeMarker({ ...marker, market: normalizedMarket })
        if (normalizedMarker) {
            nextStore[normalizedMarket] = normalizedMarker
        }
    } else {
        delete nextStore[normalizedMarket]
    }
    writeResumeMarkerStore(nextStore)
    resumeMarker.value = nextStore[normalizedMarket] || null
}

function clearResumeMarker() {
    writeResumeMarker(null)
    ElMessage.info('已清除上次浏览书签')
}

function readResumeMode() {
    if (typeof window === 'undefined') {
        return false
    }
    try {
        const raw = window.localStorage.getItem(RESUME_MODE_KEY)
        if (raw === null) {
            return false
        }
        return String(raw) === '1'
    } catch {
        return false
    }
}

function writeResumeMode(enabled) {
    if (typeof window === 'undefined') {
        return
    }
    try {
        window.localStorage.setItem(RESUME_MODE_KEY, enabled ? '1' : '0')
    } catch {
        // ignore localStorage failures
    }
}

function saveCurrentBrowseMarker(stock) {
    if (!stock || !stock.ts_code) {
        return
    }
    writeResumeMarker({
        market: market.value,
        page: currentPage.value,
        ts_code: stock.ts_code,
        name: stock.name || '',
        website: stock?.basic_info?.website || '',
        updated_at: Date.now(),
    })
}

function bookmarkCurrentStock() {
    const tsCode = String(stockTradeStore.tsCode || '').trim().toUpperCase()
    if (!tsCode) {
        ElMessage.info('当前没有可设书签的股票')
        return
    }
    const selected = watchlist.value.find((item) => String(item?.ts_code || '').trim().toUpperCase() === tsCode)
    saveCurrentBrowseMarker(
        selected || {
            ts_code: tsCode,
            name: stockTradeStore.name || tsCode,
            basic_info: { website: stockTradeStore.website || '' },
        }
    )
    ElMessage.success('已设为当前书签')
}

function isActiveStock(stock) {
    return String(stock?.ts_code || '').toUpperCase() === String(stockTradeStore.tsCode || '').toUpperCase()
}

function hasCurrentSelectionInList() {
    const current = String(stockTradeStore.tsCode || '').toUpperCase()
    if (!current) {
        return false
    }
    return watchlist.value.some((item) => String(item?.ts_code || '').toUpperCase() === current)
}

const selectStock = (stock, options = {}) => {
    if (!stock) {
        return;
    }
    stockTradeStore.setTsCode(stock.ts_code);
    stockTradeStore.setName(stock.name);
    stockTradeStore.setWebsite(stock.basic_info.website);
    const persistResume = options.persistResume !== false
    if (persistResume) {
        saveCurrentBrowseMarker(stock)
    }
};

const formatPct = (value) => {
    const number = Number(value)
    if (value === null || value === undefined || Number.isNaN(number)) {
        return '0.00'
    }
    return number.toFixed(2)
}

const formatSignedPct = (value) => {
    const number = Number(value)
    if (value === null || value === undefined || Number.isNaN(number)) {
        return '0.00'
    }
    return `${number >= 0 ? '+' : ''}${number.toFixed(2)}`
}

const truncateMainBusiness = (value) => {
    const text = String(value || '').trim()
    if (!text) {
        return ''
    }
    return text.length > 100 ? `${text.slice(0, 100)}...` : text
}

const getTraditionalPct = (stock) => {
    const tsCode = String(stock?.ts_code || '').trim().toUpperCase()
    if (tsCode && Object.prototype.hasOwnProperty.call(traditionalPctOverrideMap.value, tsCode)) {
        const overridePct = Number(traditionalPctOverrideMap.value[tsCode])
        if (Number.isFinite(overridePct)) {
            return overridePct
        }
    }
    const pct = Number(stock?.result_meta?.traditional_return_pct)
    if (!Number.isFinite(pct)) {
        return 0
    }
    return pct
}

const inferReportTypeFromEndDate = (reportEndDate) => {
    const text = String(reportEndDate || '').trim()
    if (!text) {
        return ''
    }
    const digits = text.replace(/-/g, '')
    if (digits.length < 8) {
        return ''
    }
    const md = digits.slice(4, 8)
    if (md === '0331') return 'Q1'
    if (md === '0630') return 'H1'
    if (md === '0930') return 'Q3'
    if (md === '1231') return 'FY'
    return ''
}

const normalizeReportType = (value) => {
    const normalized = String(value || '').trim().toUpperCase()
    if (!normalized) {
        return ''
    }
    if (normalized === 'ANNUAL') {
        return 'FY'
    }
    if (['Q1', 'H1', 'Q3', 'FY', 'FUSION'].includes(normalized)) {
        return normalized
    }
    return ''
}

const resolveWatchlistEarningsReportType = (stock) => {
    const meta = stock?.result_meta || {}
    const explicitReportType = normalizeReportType(
        pickFirstDisplayValue(meta?.traditional_report_type, meta?.report_type)
    )
    if (explicitReportType) {
        return explicitReportType === 'FY' ? 'FUSION' : explicitReportType
    }
    const inferred = inferReportTypeFromEndDate(meta?.valuation_report_end_date || meta?.report_end_date)
    if (!inferred) {
        return 'FUSION'
    }
    // Overlap window preference: when FY and Q1 may coexist, prefer latest Q1 semantics.
    if (inferred === 'FY') {
        return 'FUSION'
    }
    return inferred
}

const normalizeReportTypeForPredictiveSignal = (reportType) => {
    const normalized = String(reportType || '').trim().toUpperCase()
    if (!normalized) {
        return 'FUSION'
    }
    if (normalized === 'ANNUAL') {
        return 'FY'
    }
    if (['Q1', 'H1', 'Q3', 'FY', 'FUSION', 'ALL'].includes(normalized)) {
        return normalized
    }
    return 'FUSION'
}

const fetchPredictiveSignalOverride = async (tsCode, reportType = 'FUSION') => {
    const normalizedTsCode = String(tsCode || '').trim().toUpperCase()
    if (!normalizedTsCode || !baseURL) {
        return null
    }
    const normalizedReportType = normalizeReportTypeForPredictiveSignal(reportType)
    const cacheKey = `${normalizedTsCode}|${normalizedReportType}|ann`
    if (predictiveSignalCache.has(cacheKey)) {
        return predictiveSignalCache.get(cacheKey)
    }
    const pending = predictiveSignalPending.get(cacheKey)
    if (pending) {
        return pending
    }

    const encoded = encodeURIComponent(normalizedTsCode)
    const url = `${baseURL}/earnings/signal/${encoded}/?ts_code=${encoded}&report_type=${encodeURIComponent(normalizedReportType)}&anchor_mode=ann`

    const task = axios
        .get(url)
        .then((resp) => {
            const payload = resp?.data?.data
            const action = normalizeDisplayToken(payload?.action)
            const score = Number(payload?.signal_score)
            const risk = normalizeDisplayToken(payload?.risk_level)
            const snapshot = {
                action: action || '',
                score: Number.isFinite(score) ? score : null,
                risk: risk || '',
            }
            predictiveSignalCache.set(cacheKey, snapshot)
            return snapshot
        })
        .catch(() => null)
        .finally(() => {
            predictiveSignalPending.delete(cacheKey)
        })

    predictiveSignalPending.set(cacheKey, task)
    return task
}

const alignPredictiveSignalForStocks = (stocks, normalizedMarket) => {
    if (normalizedMarket === 'RESULT') {
        return
    }
    const uniqueEntries = Array.from(
        new Map(
            (stocks || [])
                .map((item) => [String(item?.ts_code || '').trim().toUpperCase(), item])
                .filter(([code]) => Boolean(code))
        ).values()
    ).slice(0, ALIGN_OVERRIDE_LIMIT)
    if (!uniqueEntries.length) {
        return
    }

    for (const stock of uniqueEntries) {
        const code = String(stock?.ts_code || '').trim().toUpperCase()
        const reportType = resolveWatchlistEarningsReportType(stock)
        fetchPredictiveSignalOverride(code, reportType).then((snapshot) => {
            if (!snapshot || typeof snapshot !== 'object') {
                return
            }
            const action = normalizeDisplayToken(snapshot?.action)
            if (action) {
                predictiveSignalOverrideMap.value = {
                    ...predictiveSignalOverrideMap.value,
                    [code]: action,
                }
            }
            const score = Number(snapshot?.score)
            if (Number.isFinite(score)) {
                predictiveScoreOverrideMap.value = {
                    ...predictiveScoreOverrideMap.value,
                    [code]: score,
                }
            }
            const risk = normalizeDisplayToken(snapshot?.risk)
            if (risk) {
                predictiveRiskOverrideMap.value = {
                    ...predictiveRiskOverrideMap.value,
                    [code]: risk,
                }
            }
        })
    }
}

const fetchTraditionalPctOverride = async (tsCode, earningsReportType = 'FUSION') => {
    const normalizedTsCode = String(tsCode || '').trim().toUpperCase()
    if (!normalizedTsCode || !baseURL) {
        return null
    }
    const normalizedReportType = String(earningsReportType || 'FUSION').trim().toUpperCase() || 'FUSION'
    const cacheKey = `${normalizedTsCode}|${normalizedReportType}`
    if (traditionalPctCache.has(cacheKey)) {
        return traditionalPctCache.get(cacheKey)
    }
    const pending = traditionalPctPending.get(cacheKey)
    if (pending) {
        return pending
    }

    const task = axios
        .get(
            `${baseURL}/stocks/${encodeURIComponent(normalizedTsCode)}/valuation/methods/?freq=D&valuation_band_pct=0.1&earnings_report_type=${encodeURIComponent(normalizedReportType)}`
        )
        .then((res) => {
            const summary = res?.data?.summary || {}
            const pct = Number(summary?.composite_valuation_gap_pct)
            const score = Number(summary?.undervalue_score)
            const activeVariant = String(res?.data?.active_valuation_variant || '').trim()
            const riskByVariant = res?.data?.valuation_risk_by_variant || {}
            const activeRisk = (activeVariant && riskByVariant?.[activeVariant]) || res?.data?.valuation_risk || {}
            const risk = normalizeDisplayToken(activeRisk?.risk_level)
            const value = {
                pct: Number.isFinite(pct) ? pct : null,
                score: Number.isFinite(score) ? score : null,
                risk: risk || '',
            }
            traditionalPctCache.set(cacheKey, value)
            return value
        })
        .catch(() => null)
        .finally(() => {
            traditionalPctPending.delete(cacheKey)
        })

    traditionalPctPending.set(cacheKey, task)
    return task
}

const alignTraditionalPctForStocks = (stocks, normalizedMarket) => {
    if (normalizedMarket === 'RESULT') {
        return
    }
    const uniqueEntries = Array.from(
        new Map(
            (stocks || [])
                .map((item) => [String(item?.ts_code || '').trim().toUpperCase(), item])
                .filter(([code]) => Boolean(code))
        ).values()
    ).slice(0, ALIGN_OVERRIDE_LIMIT)
    if (!uniqueEntries.length) {
        return
    }

    for (const stock of uniqueEntries) {
        const code = String(stock?.ts_code || '').trim().toUpperCase()
        const reportType = resolveWatchlistEarningsReportType(stock)
        fetchTraditionalPctOverride(code, reportType).then((snapshot) => {
            if (!snapshot || typeof snapshot !== 'object') {
                return
            }
            const nextPct = Number(snapshot?.pct)
            if (Number.isFinite(nextPct)) {
                traditionalPctOverrideMap.value = {
                    ...traditionalPctOverrideMap.value,
                    [code]: nextPct,
                }
            }
            const nextScore = Number(snapshot?.score)
            if (Number.isFinite(nextScore)) {
                traditionalScoreOverrideMap.value = {
                    ...traditionalScoreOverrideMap.value,
                    [code]: nextScore,
                }
            }
            const nextRisk = normalizeDisplayToken(snapshot?.risk)
            if (nextRisk) {
                traditionalRiskOverrideMap.value = {
                    ...traditionalRiskOverrideMap.value,
                    [code]: nextRisk,
                }
            }
        })
    }
}

const getPredictiveOptimisticPct = (stock) => {
    const pct = Number(stock?.result_meta?.predictive_optimistic_return_pct)
    if (!Number.isFinite(pct)) {
        return 0
    }
    return pct
}

const getPredictiveConservativePct = (stock) => {
    const pct = Number(stock?.result_meta?.predictive_conservative_return_pct)
    if (!Number.isFinite(pct)) {
        return 0
    }
    return pct
}

const getSincePickCurrentPct = (stock) => {
    const pct = Number(stock?.result_meta?.since_pick_current_return_pct)
    if (!Number.isFinite(pct)) {
        return 0
    }
    return pct
}

const getSincePickPeakPct = (stock) => {
    const pct = Number(stock?.result_meta?.since_pick_peak_return_pct)
    if (!Number.isFinite(pct)) {
        return 0
    }
    return pct
}

const getSincePickTroughPct = (stock) => {
    const pct = Number(stock?.result_meta?.since_pick_trough_return_pct)
    if (!Number.isFinite(pct)) {
        return 0
    }
    return pct
}

const hasSincePickReturns = (stock) => {
    const meta = stock?.result_meta || {}
    return [
        meta?.since_pick_current_return_pct,
        meta?.since_pick_peak_return_pct,
        meta?.since_pick_trough_return_pct,
    ].some((value) => Number.isFinite(Number(value)))
}

const pickFirstDisplayValue = (...candidates) => {
    for (const candidate of candidates) {
        if (candidate === null || candidate === undefined) {
            continue
        }
        const text = String(candidate).trim()
        if (text) {
            return text
        }
    }
    return ''
}

const pickFirstFiniteNumber = (...candidates) => {
    for (const candidate of candidates) {
        const value = Number(candidate)
        if (Number.isFinite(value)) {
            return value
        }
    }
    return null
}

const clampScore = (value) => {
    const number = Number(value)
    if (!Number.isFinite(number)) {
        return null
    }
    return Math.max(0, Math.min(100, number))
}

const normalizeDisplayToken = (value) => String(value || '').trim().replace(/\s+/g, '_').toUpperCase()

const normalizeSignalToken = (value) => {
    const normalized = normalizeDisplayToken(value)
    if (!normalized) {
        return ''
    }
    if (normalized === 'STRONG_BUY' || normalized === 'B' || normalized.includes('BUY')) {
        return 'BUY'
    }
    if (normalized === 'SELL' || normalized === 'SELL_PART' || normalized === 'REDUCE' || normalized === 'S' || normalized.includes('SELL') || normalized.includes('REDUCE')) {
        return 'SELL'
    }
    if (normalized === 'HOLD' || normalized === 'H' || normalized.includes('HOLD')) {
        return 'HOLD'
    }
    return normalized
}

const formatStyleParamValue = (value) => {
    if (Array.isArray(value)) {
        return value.map((item) => String(item)).filter(Boolean).join('/')
    }
    if (value === null || value === undefined) {
        return ''
    }
    if (typeof value === 'boolean') {
        return value ? 'true' : 'false'
    }
    return String(value)
}

const buildStyleParamEntries = () => {
    const strategy = resultStyleStrategy.value || {}
    const output = []
    const pushEntry = (key, value) => {
        const textValue = formatStyleParamValue(value)
        if (!textValue) {
            return
        }
        output.push(`${key}=${textValue}`)
    }

    const selectionParams = strategy?.selection_params
    if (selectionParams && typeof selectionParams === 'object') {
        for (const key of Object.keys(selectionParams).sort()) {
            pushEntry(key, selectionParams[key])
        }
    }

    if (!output.length) {
        const job = strategy?.job || {}
        const fallbackKeys = [
            'pick_strategy',
            'valuation_band_pct',
            'min_signal_score',
            'traditional_min_signal_score',
            'min_target_return_pct',
            'risk_level',
            'traditional_risk_level',
            'buy_candidate_only',
            'predictive_buy_signal_only',
            'priority_policy',
        ]
        for (const key of fallbackKeys) {
            pushEntry(key, job[key])
        }

        const quickProfiles = strategy?.quick_profiles || {}
        const activeKind = normalizeResultKind(selectedResultKind.value)
        const activeProfile = quickProfiles?.[activeKind]
        if (activeProfile && typeof activeProfile === 'object') {
            pushEntry('profile', activeKind)
            const profileKeys = [
                'earnings_report_type',
                'valuation_method',
                'valuation_status',
                'valuation_pick_strategy',
                'signal_action',
                'min_signal_score',
                'risk_level',
            ]
            for (const key of profileKeys) {
                pushEntry(key, activeProfile[key])
            }
        }
    }
    return output
}

const resultStyleParamEntries = computed(() => buildStyleParamEntries())

const resultStyleParamSummary = computed(() => {
    const entries = resultStyleParamEntries.value
    if (!entries.length) {
        return ''
    }
    return `参数: ${entries.slice(0, 3).join(' | ')}${entries.length > 3 ? ' ...' : ''}`
})

const resultStylePopoverTitle = computed(() => {
    const strategy = resultStyleStrategy.value || {}
    const style = String(strategy?.style || selectedResultStyle.value || '').trim().toUpperCase()
    const name = String(strategy?.strategy_name || '').trim()
    if (name) {
        return `${style} | ${name}`
    }
    return `${style} | 当前策略参数`
})

const getTraditionalSignalLabel = (stock) => {
    const meta = stock?.result_meta || {}
    const raw = pickFirstDisplayValue(
        meta?.traditional_signal_live,
        meta?.traditional_signal,
        meta?.traditional_signal_label,
        stock?.traditional_signal_live,
        stock?.traditional_signal,
        stock?.traditional_signal_label,
    )
    const normalized = normalizeSignalToken(raw)
    if (normalized) {
        return normalized
    }
    const pct = Number(getTraditionalPct(stock))
    if (Number.isFinite(pct)) {
        if (pct > 0) {
            return 'BUY'
        }
        if (pct < 0) {
            return 'SELL'
        }
        return 'HOLD'
    }
    return '--'
}

const getTraditionalScoreLabel = (stock) => {
    const tsCode = String(stock?.ts_code || '').trim().toUpperCase()
    if (tsCode && Object.prototype.hasOwnProperty.call(traditionalScoreOverrideMap.value, tsCode)) {
        const overrideScore = Number(traditionalScoreOverrideMap.value[tsCode])
        if (Number.isFinite(overrideScore)) {
            return `${overrideScore.toFixed(0)}`
        }
    }
    const meta = stock?.result_meta || {}
    let score = pickFirstFiniteNumber(
        resolveResultUndervalueScore(stock),
        meta?.traditional_signal_score,
        meta?.signal_score,
        stock?.traditional_signal_score,
        stock?.signal_score,
    )
    if (!Number.isFinite(Number(score))) {
        const pctProxy = Math.abs(Number(getTraditionalPct(stock)))
        score = Number.isFinite(pctProxy) ? pctProxy : null
    }
    const normalizedScore = clampScore(score)
    if (!Number.isFinite(Number(normalizedScore))) {
        return '0'
    }
    return `${Number(normalizedScore).toFixed(0)}`
}

const getTraditionalRiskLabel = (stock) => {
    const tsCode = String(stock?.ts_code || '').trim().toUpperCase()
    if (tsCode && Object.prototype.hasOwnProperty.call(traditionalRiskOverrideMap.value, tsCode)) {
        const overrideRisk = normalizeDisplayToken(traditionalRiskOverrideMap.value[tsCode])
        if (overrideRisk) {
            return overrideRisk
        }
    }
    const meta = stock?.result_meta || {}
    const raw = pickFirstDisplayValue(
        meta?.traditional_risk_level,
        meta?.valuation_risk_level,
        stock?.valuation_risk_level,
    )
    const normalized = normalizeDisplayToken(raw)
    return normalized || '--'
}

const shortenVariantLabel = (variant) => {
    const text = String(variant || '').trim()
    if (!text) {
        return ''
    }
    const parts = text.split('|').map((item) => String(item || '').trim()).filter(Boolean)
    if (!parts.length) {
        return text
    }
    const tail = parts[parts.length - 1]
    if (tail && tail.length <= 24) {
        return tail
    }
    const head = parts[0]
    return head.length > 24 ? `${head.slice(0, 24)}...` : head
}

const getTraditionalContextLabel = (stock) => {
    const meta = stock?.result_meta || {}
    const reportTypeRaw = pickFirstDisplayValue(
        meta?.traditional_report_type,
        inferReportTypeFromEndDate(meta?.valuation_report_end_date),
        inferReportTypeFromEndDate(meta?.report_end_date),
    )
    const reportType = String(reportTypeRaw || '').trim().toUpperCase()
    const variantLabel = shortenVariantLabel(meta?.traditional_valuation_variant || meta?.valuation_variant)
    const chunks = []
    if (reportType) {
        chunks.push(reportType)
    }
    if (variantLabel) {
        chunks.push(variantLabel)
    }
    return chunks.join(' | ')
}

const getPredictiveSignalLabel = (stock) => {
    const tsCode = String(stock?.ts_code || '').trim().toUpperCase()
    if (tsCode && Object.prototype.hasOwnProperty.call(predictiveSignalOverrideMap.value, tsCode)) {
        const overrideSignal = normalizeDisplayToken(predictiveSignalOverrideMap.value[tsCode])
        if (overrideSignal) {
            return overrideSignal
        }
    }
    const meta = stock?.result_meta || {}
    const prediction = stock?.prediction || {}
    const raw = pickFirstDisplayValue(
        meta?.predictive_signal,
        meta?.predictive_signal_label,
        meta?.action,
        prediction?.action,
        prediction?.signal,
        prediction?.signal_label,
    )
    if (raw) {
        return normalizeDisplayToken(raw)
    }
    const signalScore = Number(pickFirstDisplayValue(meta?.signal_score, prediction?.signal_score))
    if (Number.isFinite(signalScore)) {
        return `S${signalScore.toFixed(0)}`
    }
    return '--'
}

const getPredictiveScoreLabel = (stock) => {
    const tsCode = String(stock?.ts_code || '').trim().toUpperCase()
    if (tsCode && Object.prototype.hasOwnProperty.call(predictiveScoreOverrideMap.value, tsCode)) {
        const overrideScore = Number(predictiveScoreOverrideMap.value[tsCode])
        if (Number.isFinite(overrideScore)) {
            return `${overrideScore.toFixed(0)}`
        }
    }
    const meta = stock?.result_meta || {}
    const prediction = stock?.prediction || {}
    let score = pickFirstFiniteNumber(
        meta?.predictive_signal_score,
        meta?.signal_score,
        meta?.predictive_pick_score,
        prediction?.signal_score,
        stock?.predictive_signal_score,
        stock?.signal_score,
        stock?.predictive_pick_score,
    )
    if (!Number.isFinite(Number(score))) {
        const optimistic = Math.abs(Number(getPredictiveOptimisticPct(stock)))
        const conservative = Math.abs(Number(getPredictiveConservativePct(stock)))
        const pctProxy = Math.max(optimistic, conservative)
        score = Number.isFinite(pctProxy) ? pctProxy : null
    }
    const normalizedScore = clampScore(score)
    if (!Number.isFinite(Number(normalizedScore))) {
        return '0'
    }
    return `${Number(normalizedScore).toFixed(0)}`
}

const getPredictiveRiskLabel = (stock) => {
    const tsCode = String(stock?.ts_code || '').trim().toUpperCase()
    if (tsCode && Object.prototype.hasOwnProperty.call(predictiveRiskOverrideMap.value, tsCode)) {
        const overrideRisk = normalizeDisplayToken(predictiveRiskOverrideMap.value[tsCode])
        if (overrideRisk) {
            return overrideRisk
        }
    }
    const meta = stock?.result_meta || {}
    const prediction = stock?.prediction || {}
    const raw = pickFirstDisplayValue(
        meta?.predictive_risk_level,
        meta?.risk_level,
        prediction?.risk_level,
        prediction?.risk,
    )
    const normalized = normalizeDisplayToken(raw)
    return normalized || '--'
}

const getSignalDisplayLabel = (value) => {
    const normalized = normalizeSignalToken(value)
    if (normalized === 'BUY') {
        return '买'
    }
    if (normalized === 'SELL') {
        return '卖'
    }
    if (normalized === 'HOLD') {
        return '持'
    }
    return normalized || '--'
}

const getRiskDisplayLabel = (value) => {
    const normalized = normalizeDisplayToken(value)
    if (normalized === 'LOW' || normalized === 'L') {
        return '低'
    }
    if (normalized === 'MEDIUM' || normalized === 'M') {
        return '中'
    }
    if (normalized === 'HIGH' || normalized === 'VERY_HIGH' || normalized === 'H') {
        return '高'
    }
    return normalized || '--'
}

const getRiskLevelDisplayLabel = (value) => {
    const normalized = getRiskDisplayLabel(value)
    if (!normalized || normalized === '--') {
        return '--'
    }
    return normalized
}

const signalTokenClass = (value) => {
    const normalized = normalizeSignalToken(value)
    if (normalized === 'BUY') {
        return 'signal-token signal-token-danger'
    }
    if (normalized === 'SELL') {
        return 'signal-token signal-token-success'
    }
    if (normalized === 'HOLD') {
        return 'signal-token signal-token-info'
    }
    return 'signal-token signal-token-neutral'
}

const riskTokenClass = (value) => {
    const normalized = normalizeDisplayToken(value)
    if (normalized === 'LOW' || normalized === 'L') {
        return 'risk-token risk-token-low'
    }
    if (normalized === 'MEDIUM' || normalized === 'M') {
        return 'risk-token risk-token-medium'
    }
    if (normalized === 'HIGH' || normalized === 'VERY_HIGH' || normalized === 'H') {
        return 'risk-token risk-token-high'
    }
    return 'risk-token risk-token-neutral'
}

const valuationToneClassBySignal = (signalLabel) => {
    const signal = normalizeSignalToken(signalLabel)
    if (signal === 'BUY') {
        return 'valuation-tone-red'
    }
    if (signal === 'SELL') {
        return 'valuation-tone-green'
    }
    return 'valuation-tone-gray'
}

const valuationTextClass = (value) => {
    const number = Number(value)
    if (!Number.isFinite(number) || number === 0) {
        return 'valuation-text-gray'
    }
    return number > 0 ? 'valuation-text-red' : 'valuation-text-green'
}

function buildWatchlistParams(normalizedMarket) {
    const params = new URLSearchParams()
    params.set('format', 'json')
    params.set('market', normalizedMarket)
    if (normalizedMarket === 'RESULT' && selectedResultDate.value) {
        params.set('pick_date', selectedResultDate.value)
    }
    if (normalizedMarket === 'RESULT') {
        params.set('pick_kind', normalizeResultKind(selectedResultKind.value))
        params.set('result_style', normalizeResultStyle(selectedResultStyle.value))
        params.set('result_market', normalizeResultMarket(selectedResultMarket.value))
        params.set('result_season', normalizeResultSeason(selectedResultSeason.value))
    }
    if (normalizedMarket === 'WL' || normalizedMarket === 'OBS') {
        params.set('wl_market', normalizeWatchlistMarket(selectedWatchlistMarket.value))
    }
    return params
}

function buildWatchlistCacheKey(normalizedMarket, targetPage, params) {
    return `${normalizedMarket}|${pageSize.value}|${targetPage}|${params.toString()}`
}

function pruneWatchlistPageCache() {
    while (watchlistPageCache.size > PAGE_PREFETCH_CACHE_LIMIT) {
        const oldestKey = watchlistPageCache.keys().next().value
        if (!oldestKey) {
            break
        }
        watchlistPageCache.delete(oldestKey)
    }
}

function resetWatchlistPageCache() {
    watchlistPageCache.clear()
    watchlistPagePrefetchPending.clear()
}

function applyWatchlistResponse(responseData, normalizedMarket, targetPage) {
    watchlist.value = Array.isArray(responseData.data) ? responseData.data : []
    totalCount.value = Number(responseData.total) || 0
    currentPage.value = targetPage
    if (normalizedMarket === 'RESULT' && Array.isArray(responseData.result_available_dates)) {
        resultAvailableDates.value = responseData.result_available_dates
            .map((item) => String(item || '').slice(0, 10))
            .filter((item) => Boolean(item))
    }
    if (normalizedMarket === 'RESULT' && !selectedResultDate.value && responseData.result_file_date) {
        selectedResultDate.value = responseData.result_file_date
    }
        if (normalizedMarket !== 'RESULT') {
        alignTraditionalPctForStocks(responseData.data || [], normalizedMarket)
            alignPredictiveSignalForStocks(responseData.data || [], normalizedMarket)
    }
    if (normalizedMarket === 'RESULT') {
        selectedResultKind.value = normalizeResultKind(responseData.result_kind)
        selectedResultStyle.value = normalizeResultStyle(responseData.result_style || selectedResultStyle.value)
        resultStyleStrategy.value = responseData.result_style_strategy || null
    } else {
        resultStyleStrategy.value = null
    }
    // Keep right panel passive: do not auto-select first stock when list page changes.
}

function prefetchWatchlistPage(normalizedMarket, nextPage, params, total) {
    if (normalizedMarket === 'RESULT') {
        return
    }
    if (!baseURL || loading.value) {
        return
    }
    if (!Number.isFinite(total) || nextPage < 1 || nextPage > Math.max(1, Math.ceil(total / pageSize.value))) {
        return
    }
    const cacheKey = buildWatchlistCacheKey(normalizedMarket, nextPage, params)
    if (watchlistPageCache.has(cacheKey) || watchlistPagePrefetchPending.has(cacheKey)) {
        return
    }
    const fromIndex = (nextPage - 1) * pageSize.value
    const toIndex = fromIndex + pageSize.value
    const task = axios
        .get(`${baseURL}/watchlist/${fromIndex}/${toIndex}/?${params.toString()}`)
        .then((response) => {
            const responseData = response?.data || {}
            watchlistPageCache.set(cacheKey, responseData)
            pruneWatchlistPageCache()
        })
        .catch(() => {
            // Ignore prefetch failures; foreground request will retry when user actually flips page.
        })
        .finally(() => {
            watchlistPagePrefetchPending.delete(cacheKey)
        })
    watchlistPagePrefetchPending.set(cacheKey, task)
}

const fetchWatchlist = async (marketCode, options = {}) => {
    const requestToken = ++watchlistFetchToken.value
    const targetPage = Math.max(1, Number(options.page || currentPage.value || 1))
    const fromIndex = (targetPage - 1) * pageSize.value
    const toIndex = fromIndex + pageSize.value
    loading.value = true;
    resultHydrating.value = false
    const fetchStartedAt = Date.now()
    try {
        const normalizedMarket = normalizeMarket(marketCode)
        const isStaleRequest = () => {
            return requestToken !== watchlistFetchToken.value || normalizeMarket(market.value) !== normalizedMarket
        }
        const params = buildWatchlistParams(normalizedMarket)
        const cacheKey = buildWatchlistCacheKey(normalizedMarket, targetPage, params)
        const forceRefresh = options.force === true
        let responseData = null
        if (!forceRefresh) {
            responseData = watchlistPageCache.get(cacheKey) || null
        }
        if (responseData) {
            if (isStaleRequest()) {
                return
            }
            applyWatchlistResponse(responseData, normalizedMarket, targetPage)
            prefetchWatchlistPage(normalizedMarket, targetPage + 1, params, Number(responseData.total) || 0)
            return
        }

        const canUseResultStagedLoad = normalizedMarket === 'RESULT' && !forceRefresh
        if (canUseResultStagedLoad) {
            const stagedToIndex = Math.min(toIndex, fromIndex + RESULT_STAGE_SIZE)
            if (stagedToIndex > fromIndex && stagedToIndex < toIndex) {
                const stageParams = new URLSearchParams(params.toString())
                stageParams.set('lite', '1')
                const stageResp = await axios.get(`${baseURL}/watchlist/${fromIndex}/${stagedToIndex}/?${stageParams.toString()}`)
                const stageData = stageResp?.data || {}
                if (isStaleRequest()) {
                    return
                }
                applyWatchlistResponse(stageData, normalizedMarket, targetPage)
                pageLoadCostMs.value = Date.now() - fetchStartedAt
                loading.value = false
                resultHydrating.value = true

                axios
                    .get(`${baseURL}/watchlist/${fromIndex}/${toIndex}/?${params.toString()}`)
                    .then((fullResp) => {
                        if (isStaleRequest()) {
                            return
                        }
                        const fullData = fullResp?.data || {}
                        watchlistPageCache.set(cacheKey, fullData)
                        pruneWatchlistPageCache()
                        applyWatchlistResponse(fullData, normalizedMarket, targetPage)
                        prefetchWatchlistPage(normalizedMarket, targetPage + 1, params, Number(fullData.total) || 0)
                    })
                    .catch((error) => {
                        if (!isStaleRequest()) {
                            console.error('Error hydrating RESULT watchlist:', error)
                        }
                    })
                    .finally(() => {
                        if (!isStaleRequest()) {
                            resultHydrating.value = false
                        }
                    })
                return
            }
        }

        if (!responseData) {
            const response = await axios.get(`${baseURL}/watchlist/${fromIndex}/${toIndex}/?${params.toString()}`)
            responseData = response?.data || {}
            watchlistPageCache.set(cacheKey, responseData)
            pruneWatchlistPageCache()
        }
        if (isStaleRequest()) {
            return
        }
        applyWatchlistResponse(responseData, normalizedMarket, targetPage)
        prefetchWatchlistPage(normalizedMarket, targetPage + 1, params, Number(responseData.total) || 0)
    } catch (error) {
        if (requestToken === watchlistFetchToken.value) {
            console.error('Error fetching watchlist:', error);
        }
    } finally {
        if (requestToken === watchlistFetchToken.value) {
            pageLoadCostMs.value = Date.now() - fetchStartedAt
            if (!resultHydrating.value) {
                loading.value = false;
            }
        }
    }
};

const fetchPrevPage = async () => {
    if (currentPage.value <= 1 || loading.value) {
        return
    }
    await fetchWatchlist(market.value, { page: currentPage.value - 1 })
}

const fetchNextPage = async () => {
    if (currentPage.value >= totalPages.value || loading.value) {
        return
    }
    await fetchWatchlist(market.value, { page: currentPage.value + 1 })
}

const handlePageChange = async (page) => {
    if (loading.value) {
        return
    }
    await fetchWatchlist(market.value, { page })
}

const refreshCurrentMarketLoadedStocks = async () => {
    watchlist.value = [];
    resetWatchlistPageCache()
    await fetchWatchlist(market.value, { page: currentPage.value, force: true });
};

const handleMarketChange = async (market) => {
    const normalizedMarket = normalizeMarket(market)
    market = normalizedMarket
    if (normalizedMarket !== 'RESULT') {
        selectedResultDate.value = ''
    }
    if (normalizedMarket === 'WL' || normalizedMarket === 'OBS') {
        selectedWatchlistMarket.value = 'SH'
    }
    syncActiveTab(normalizedMarket)
    currentPage.value = 1
    await fetchWatchlist(normalizedMarket, { page: 1 });
};

const handleTabChange = async (tabName) => {
    if (tabName === 'groupA' && !groupAMarkets.has(market.value)) {
        market.value = 'HO'
    }
    if (tabName === 'groupB' && !groupBMarkets.has(market.value)) {
        market.value = '6'
    }
    await handleMarketChange(market.value)
}

const handleResultDateChange = async () => {
    if (market.value !== 'RESULT') {
        return
    }
    await handleMarketChange('RESULT')
}

const handleResultKindChange = async () => {
    selectedResultKind.value = normalizeResultKind(selectedResultKind.value)
    selectedResultStyle.value = normalizeResultStyle(selectedResultStyle.value)
    if (market.value !== 'RESULT') {
        return
    }
    await handleMarketChange('RESULT')
}

const handleResultStyleChange = async () => {
    selectedResultStyle.value = normalizeResultStyle(selectedResultStyle.value)
    if (market.value !== 'RESULT') {
        return
    }
    await handleMarketChange('RESULT')
}

const handleResultMarketChange = async () => {
    selectedResultMarket.value = normalizeResultMarket(selectedResultMarket.value)
    if (market.value !== 'RESULT') {
        return
    }
    await handleMarketChange('RESULT')
}

const handleResultSeasonChange = async () => {
    selectedResultSeason.value = normalizeResultSeason(selectedResultSeason.value)
    if (market.value !== 'RESULT') {
        return
    }
    await handleMarketChange('RESULT')
}

const handleWatchlistMarketChange = async () => {
    selectedWatchlistMarket.value = normalizeWatchlistMarket(selectedWatchlistMarket.value)
    if (market.value !== 'WL' && market.value !== 'OBS') {
        return
    }
    currentPage.value = 1
    watchlist.value = []
    resetWatchlistPageCache()
    await fetchWatchlist(market.value, { page: 1 })
}

async function restoreLastViewedStock() {
    const marker = resumeMarker.value || readResumeMarker()
    if (!marker || !marker.ts_code || !marker.market) {
        ElMessage.info('没有可恢复的浏览记录')
        return
    }

    const markerMarket = normalizeMarket(marker.market)
    if (market.value !== markerMarket) {
        market.value = markerMarket
        syncActiveTab(markerMarket)
        await handleMarketChange(markerMarket)
    }

    const markerTsCode = String(marker.ts_code || '').toUpperCase()
    const markerPage = Math.max(1, Number(marker.page || 1))
    if (currentPage.value !== markerPage) {
        await fetchWatchlist(market.value, { page: markerPage })
    }

    let target = watchlist.value.find((item) => String(item?.ts_code || '').toUpperCase() === markerTsCode)
    if (!target && resumeLocateOnly.value) {
        selectStock({
            ts_code: marker.ts_code,
            name: marker.name || marker.ts_code,
            basic_info: { website: marker.website || '' },
        })
        ElMessage.info('已恢复到上次股票（仅定位模式未自动切页）')
        return
    }

    if (target) {
        selectStock(target)
        ElMessage.success('已恢复到上次浏览股票')
        return
    }

    selectStock({
        ts_code: marker.ts_code,
        name: marker.name || marker.ts_code,
        basic_info: { website: marker.website || '' },
    })

    ElMessage.info('已跳转到上次浏览股票，但该页未找到对应条目')
}

const handleStockClick = (name, ts_code, website) => {
    selectStock({ name, ts_code, basic_info: { website } });
};

onMounted(() => {
    market.value = normalizeMarket(market.value)
    selectedWatchlistMarket.value = normalizeWatchlistMarket(selectedWatchlistMarket.value)
    resumeMarkerStore.value = readResumeMarkerStore()
    resumeMarker.value = readResumeMarker()
    resumeLocateOnly.value = readResumeMode()
    syncActiveTab(market.value)
    updateViewportHeight()
    window.addEventListener('resize', updateViewportHeight)
    fetchWatchlist(market.value, { page: 1 });
    void nextTick(() => {
        setupVisibleStockObserver()
    })
});

onBeforeUnmount(() => {
    if (typeof window === 'undefined') {
        return
    }
    window.removeEventListener('resize', updateViewportHeight)
    teardownVisibleStockObserver()
})

watch(resumeLocateOnly, (value) => {
    writeResumeMode(!!value)
})

watch(
    () => market.value,
    () => {
        resumeMarker.value = readResumeMarker()
    }
)

watch(
    () => visibleWatchlist.value.map((stock) => String(stock?.ts_code || '').trim().toUpperCase()).join('|'),
    () => {
        void nextTick(() => {
            setupVisibleStockObserver()
        })
    }
)

defineOptions({
    name: 'Watchlist'
});
</script>

<style scoped>
.card-header {
    width: 100%;
}

.watchlist-card {
    display: flex;
    flex-direction: column;
}

.watchlist-card :deep(.el-card__body) {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    overflow: hidden;
}

.watchlist-scroll {
    flex: 1;
    min-height: 0;
}

.watchlist-skeleton-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 10px 20px 10px 0;
}

.watchlist-skeleton-card {
    padding: 10px 0 12px;
    border-bottom: 1px solid #ebeef5;
}

.watchlist-skeleton-line {
    height: 12px;
    border-radius: 999px;
    background: linear-gradient(90deg, #eef2f7 0%, #f8fafc 50%, #eef2f7 100%);
    margin-bottom: 8px;
}

.watchlist-skeleton-line--title {
    width: 68%;
    height: 14px;
}

.watchlist-skeleton-line--meta {
    width: 92%;
}

.watchlist-skeleton-line--meta.short {
    width: 56%;
    margin-bottom: 0;
}

.watchlist-skeleton-tag-row {
    display: flex;
    gap: 8px;
    margin: 10px 0;
}

.watchlist-skeleton-chip {
    width: 88px;
    height: 24px;
}

.watchlist-skeleton-chip--wide {
    width: 156px;
}

.watchlist-tabs {
    margin-bottom: 6px;
}

.watchlist-tabs :deep(.el-tabs__header) {
    margin: 0 0 6px 0;
}

.market-radio-group {
    display: flex;
    width: 100%;
}

.market-radio-group :deep(.el-radio-button) {
    flex: 1;
}

.market-radio-group :deep(.el-radio-button__inner) {
    width: 100%;
    padding-left: 0;
    padding-right: 0;
    text-align: center;
}

.watch-observe-label {
    display: inline-flex;
    align-items: center;
    gap: 4px;
}

.result-date-row {
    margin-top: 6px;
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 8px;
}

.result-kind-row {
    margin-top: 6px;
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 8px;
}

.result-footer-secondary-filters {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
    margin-bottom: 6px;
}

.result-style-param-summary {
    max-width: 100%;
    font-size: 11px;
    color: #909399;
    line-height: 1.4;
}

.result-style-popover-title {
    font-size: 12px;
    font-weight: 600;
    color: #303133;
    margin-bottom: 8px;
}

.result-style-param-list {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    max-height: 220px;
    overflow: auto;
}

.result-date-cell {
    position: relative;
    width: 24px;
    height: 24px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 12px;
}

.result-date-cell--marked {
    color: #c8161d;
    font-weight: 600;
}

.result-date-cell__dot {
    position: absolute;
    right: -2px;
    top: -2px;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #c8161d;
}

.item {
    margin-top: 10px;
    margin-right: 20px;
}

.result-tag-row {
    margin-top: 6px;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}

.valuation-report-hint {
    margin-top: 4px;
    margin-left: 2px;
    font-size: 11px;
    line-height: 1.35;
    color: #909399;
}

.result-tag-row :deep(.valuation-tone-red) {
    --el-tag-bg-color: #fde2e2;
    --el-tag-border-color: #f56c6c;
    --el-tag-text-color: #c45656;
}

.result-tag-row :deep(.valuation-tone-green) {
    --el-tag-bg-color: #e8f8ee;
    --el-tag-border-color: #67c23a;
    --el-tag-text-color: #3f9a2a;
}

.result-tag-row :deep(.valuation-tone-gray) {
    --el-tag-bg-color: #f4f4f5;
    --el-tag-border-color: #dcdfe6;
    --el-tag-text-color: #909399;
}

.result-tag-row :deep(.valuation-tone-light-blue) {
    --el-tag-bg-color: #ecf5ff;
    --el-tag-border-color: #c6e2ff;
    --el-tag-text-color: #409eff;
}

.valuation-text-red {
    color: #c45656;
    font-weight: 600;
}

.valuation-text-green {
    color: #3f9a2a;
    font-weight: 600;
}

.valuation-text-gray {
    color: #909399;
}

.valuation-side-meta {
    margin-left: 4px;
    color: #606266;
}

.signal-token,
.risk-token {
    font-weight: 700;
}

.signal-token-danger {
    color: #c45656;
}

.signal-token-success {
    color: #67c23a;
}

.signal-token-info {
    color: #909399;
}

.signal-token-neutral,
.risk-token-neutral {
    color: #868e96;
}

.risk-token-low {
    color: #2b8a3e;
}

.risk-token-medium {
    color: #b26a00;
}

.risk-token-high {
    color: #c92a2a;
}

.watchlist-meta-row {
    margin-top: 6px;
    display: flex;
    justify-content: space-between;
    font-size: 11px;
    color: #606266;
    gap: 8px;
    flex-wrap: wrap;
}

.watchlist-footer-meta-row {
    margin-top: 0;
    margin-bottom: 6px;
}

.watchlist-footer-actions {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 6px;
}

.watchlist-footer-quick-actions {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
}

.watchlist-footer-pagination {
    display: flex;
    justify-content: center;
    width: 100%;
    overflow-x: auto;
    padding-bottom: 2px;
}

.watchlist-footer-pagination :deep(.el-pagination) {
    white-space: nowrap;
}

.watchlist-card :deep(.el-card__footer) {
    padding-top: 8px;
    padding-bottom: 8px;
}

.active-stock-item {
    background: #f0f9ff;
    border-radius: 6px;
    padding: 4px 6px;
}

@media (max-height: 900px) {
    .watchlist-card :deep(.el-card__header),
    .watchlist-card :deep(.el-card__footer) {
        padding-top: 10px;
        padding-bottom: 10px;
    }
}
</style>