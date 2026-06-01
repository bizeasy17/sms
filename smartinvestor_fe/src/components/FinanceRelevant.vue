<template>
    <div class="grid-content ep-bg-purple">
        <el-card class="finance-card" :style="cardStyle">
                <template #header>
                    <el-row align="middle" justify="space-between">
                        <el-col :span="12">
                            <div style="display: flex; align-items: center; gap: 10px;">
                                <span style="font-size: 14px;">财务</span>
                                <el-radio-group v-if="showReportTypeSwitch" v-model="reportType" size="small" @change="handleReportTypeChange">
                                    <el-radio-button label="Q1">Q1</el-radio-button>
                                    <el-radio-button label="H1">H1</el-radio-button>
                                    <el-radio-button label="Q3">Q3</el-radio-button>
                                    <el-radio-button label="FY">FY</el-radio-button>
                                    <el-radio-button label="快">快</el-radio-button>
                                </el-radio-group>
                            </div>
                        </el-col>
                        <el-col :span="12" style="text-align: right;">
                            <el-radio-group v-model="tushareApi" size="small" @change="handleFinButtonChange">
                                <el-radio-button label="INDICATOR">销</el-radio-button>
                                <el-radio-button label="TOP10_FLOATHOLDERS">持</el-radio-button>
                                <el-radio-button label="HOLD">基</el-radio-button>
                                <el-radio-button label="CYQ_PERF">筹</el-radio-button>
                            </el-radio-group>
                        </el-col>
                    </el-row>
                </template>
                <el-table
                    v-if="tushareApi === 'INDICATOR' && indicatorTableRows.length > 0"
                    :data="indicatorTableRows"
                    :height="scrollMaxHeight"
                    size="small"
                    border
                    style="width: 100%;"
                >
                    <el-table-column prop="metric" label="指标" fixed="left" min-width="110" />
                    <el-table-column
                        v-for="(period, idx) in indicatorPeriods"
                        :key="period.key"
                        :label="period.label"
                        :prop="`p_${idx}`"
                        min-width="72"
                    />
                </el-table>
                <template v-else-if="tushareApi === 'HOLD'">
                    <el-row :gutter="8" style="margin-bottom: 6px;">
                        <el-col :span="24">
                            <span style="font-size: 12px; color: #606266;">
                                {{ holdSummaryText }}
                            </span>
                        </el-col>
                    </el-row>
                    <el-table
                        :data="fundHoldRows"
                        :height="Math.max(140, scrollMaxHeight - 28)"
                        size="small"
                        border
                        style="width: 100%;"
                    >
                        <el-table-column prop="fund_ts_code" label="基金代码" min-width="106" />
                        <el-table-column prop="fund_name" label="基金名称" min-width="132" />
                        <el-table-column prop="end_date" label="报告期" min-width="90" />
                        <el-table-column prop="stk_mkv_ratio" label="持仓占净值(%)" min-width="102" />
                        <el-table-column prop="ret_prev_year" label="去年全年(%)" min-width="96" />
                        <el-table-column prop="ret_ytd" label="今年以来(%)" min-width="96" />
                        <el-table-column prop="ret_month" label="本月(%)" min-width="86" />
                    </el-table>
                </template>
                <el-scrollbar v-else :max-height="scrollMaxHeight">
                    <el-row :gutter="10" size="small">
                        <el-col :span="24" v-for="(label, key) in keyNameMap" :key="key" style="margin-bottom: 2px;">
                            <el-row>
                                <el-col :span="14">
                                    <span style="font-weight: bold; font-size: small;">{{ label }}</span>
                                </el-col>
                                <el-col :span="10" style="text-align: right;">
                                    <span style="font-size: small;">
                                        {{ finData && finData[key] !== undefined ? finData[key] : '-' }}
                                    </span>
                                </el-col>
                            </el-row>
                        </el-col>
                    </el-row>
                </el-scrollbar>
        </el-card>
    </div>
</template>

<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
// element plus
import { ElCard, ElRadioGroup, ElRadioButton, ElRow, ElCol, ElScrollbar, ElTable, ElTableColumn } from 'element-plus'
import { useStockTradeStore } from '../stores/stockTradeStore'

const tushareApi = ref('INDICATOR')

import axios from 'axios'
const baseURL = inject('baseURL')

const stockTradeStore = useStockTradeStore()
const finData = ref<any>(null)
const finHistoryRows = ref<any[]>([])
const keyNameMap = ref<Record<string, string>>({})
const viewportHeight = ref(typeof window !== 'undefined' ? window.innerHeight : 900)
const reportType = ref('FY')
const financeDataCache = new Map<string, any>()
const financeDataPending = new Map<string, Promise<any | null>>()
const financeRequestToken = ref(0)

const reportTypeSupportedApis = new Set(['INDICATOR'])
const showReportTypeSwitch = computed(() => reportTypeSupportedApis.has(tushareApi.value))

function formatPeriodDate(value: unknown): string {
    const text = String(value || '').trim()
    if (/^\d{8}$/.test(text)) {
        return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`
    }
    return text || '-'
}

const indicatorPeriods = computed(() => {
    return finHistoryRows.value.map((item, idx) => {
        const endDate = formatPeriodDate(item?.end_date)
        return {
            key: `${endDate || 'P'}_${idx}`,
            label: endDate || `周期${idx + 1}`,
        }
    })
})

const indicatorTableRows = computed(() => {
    if (tushareApi.value !== 'INDICATOR' || !finHistoryRows.value.length) {
        return []
    }

    const reportTypeRow: Record<string, any> = { metric: '口径' }
    finHistoryRows.value.forEach((periodRow, idx) => {
        const reportTypeText = String(periodRow?.report_type || reportType.value || '').trim().toUpperCase()
        reportTypeRow[`p_${idx}`] = reportTypeText || '-'
    })

    const metricEntries = Object.entries(fIndicatorKeyNameMap).filter(([key]) => key !== 'end_date' && key !== 'ts_code')
    const metricRows = metricEntries.map(([key, label]) => {
        const row: Record<string, any> = { metric: label }
        finHistoryRows.value.forEach((periodRow, idx) => {
            const value = periodRow?.[key]
            row[`p_${idx}`] = value === null || value === undefined || value === '' ? '-' : value
        })
        return row
    })

    return [reportTypeRow, ...metricRows]
})

const fundHoldRows = computed(() => {
    if (tushareApi.value !== 'HOLD') {
        return []
    }
    return finHistoryRows.value.map((row) => ({
        ...row,
        end_date: formatPeriodDate(row?.end_date),
        stk_mkv_ratio: row?.stk_mkv_ratio ?? '-',
        ret_prev_year: row?.ret_prev_year ?? '-',
        ret_ytd: row?.ret_ytd ?? '-',
        ret_month: row?.ret_month ?? '-',
    }))
})

const cardStyle = computed(() => ({
    width: '100%',
}))

const scrollMaxHeight = computed(() => Math.max(200, Math.min(760, viewportHeight.value - 300)))

const updateViewportHeight = () => {
    if (typeof window === 'undefined') {
        return
    }
    viewportHeight.value = window.innerHeight || 900
}

interface IChipsData {
    ts_code: string
    trade_date: string
    his_low: number
    his_high: number
    cost_5pct: number
    cost_15pct: number
    cost_50pct: number
    cost_85pct: number
    cost_95pct: number
    weight_avg: number
    winner_rate: number
}

const chipsKeyNameMap: Record<string, string> = {
    // ts_code: '代码',
    trade_date: '交易日期',
    weight_avg: '加权均价',
    winner_rate: '收盘获利(%)',
    cost_95pct: '95%成本',
    cost_85pct: '85%成本',
    cost_50pct: '50%成本',
    cost_15pct: '15%成本',
    cost_5pct: '5%成本',
    his_high: '历史最高',
    his_low: '历史最低',
}

interface IFinIndicatorData {
    ts_code: string
    end_date: string
    eps: number
    total_revenue_ps: number
    revenue_ps: number
    undist_profit_ps: number
    gross_margin: number
    ar_turn: number
    ebit: number
    ebitda: number
    fcff: number
    interestdebt: number
    netprofit_margin: number
    grossprofit_margin: number
    roe: number
    roe_dt: number
    debt_to_assets: number
    ca_to_assets: number
    or_yoy: number
    q_op_qoq: number
    netprofit_yoy: number
    dt_netprofit_yoy: number
}

interface ITop10FloatHoldersData {
    ts_code: string
    end_date: string
    ann_date: string
    holder_count: number
    total_hold_amount: number
    total_hold_ratio: number
    [key: string]: string | number
}

interface IFundHoldingRow {
    fund_ts_code: string
    fund_name: string
    end_date: string
    stk_mkv_ratio: number | null
    ret_prev_year: number | null
    ret_ytd: number | null
    ret_month: number | null
}

interface IFundHoldingSummary {
    latest_end_date: string
    fund_count: number
    total_mkv: number | null
    total_amount: number | null
    hold_market_cap_ratio_pct: number | null
    hold_total_share_ratio_pct: number | null
}

function formatNumber(value: number | null | undefined, digits = 2): string {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
        return '-'
    }
    return Number(value).toLocaleString('zh-CN', {
        minimumFractionDigits: 0,
        maximumFractionDigits: digits,
    })
}

function formatCompactMetric(value: number | null | undefined, suffix = ''): string {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
        return `-${suffix}`
    }

    const numeric = Number(value)
    const absValue = Math.abs(numeric)
    if (absValue >= 100000000) {
        return `${formatNumber(numeric / 100000000, 2)}亿${suffix}`
    }
    if (absValue >= 10000) {
        return `${formatNumber(numeric / 10000, 2)}万${suffix}`
    }
    return `${formatNumber(numeric, 0)}${suffix}`
}

const holdSummaryText = computed(() => {
    if (tushareApi.value !== 'HOLD') {
        return ''
    }
    const summary = (finData.value || {}) as IFundHoldingSummary
    const periodText = formatPeriodDate(summary?.latest_end_date)
    const fundCount = Number(summary?.fund_count || 0)
    const mkvText = formatCompactMetric(summary?.total_mkv)
    const amountText = formatCompactMetric(summary?.total_amount, '股')
    const mvRatioText = formatNumber(summary?.hold_market_cap_ratio_pct, 4)
    const shareRatioText = formatNumber(summary?.hold_total_share_ratio_pct, 4)
    return `最新期 ${periodText} | ${fundCount}家 | ${mkvText} | ${amountText} | 市值占比 ${mvRatioText}% | 股本占比 ${shareRatioText}%`
})

const top10FloatHoldersEmptyData: ITop10FloatHoldersData = {
    ts_code: '',
    end_date: '',
    ann_date: '',
    holder_count: 0,
    total_hold_amount: 0,
    total_hold_ratio: 0,
    notice: '暂无前10流通股东数据'
}

const fIndicatorKeyNameMap: Record<string, string> = {
    // ts_code: '代码',
    end_date: '报告期',
    eps: '收益(股)',
    total_revenue_ps: '营总收(股)',
    revenue_ps: '营收(股)',
    undist_profit_ps: '未分配利润(股)',
    gross_margin: '毛利(百万)',
    ar_turn: '应收周转率(%)',
    ebit: 'EBIT(百万)',
    ebitda: 'EBITDA(百万)',
    fcff: 'FCF(百万)',
    interestdebt: '带息债务(百万)',
    netprofit_margin: '净利率(%)',
    grossprofit_margin: '毛利率(%)',
    roe: 'ROE(%)',
    roe_dt: 'ROE(扣非,%)',
    debt_to_assets: '负债率(%)',
    ca_to_assets: '流资占比(%)',
    or_yoy: '营收同比(%)',
    q_op_qoq: '利润环比(%)',
    netprofit_yoy: '净利同比(%)',
    dt_netprofit_yoy: '扣非净利同比(%)',
}

const top10FloatHoldersKeyNameMap: Record<string, string> = {
    notice: '提示',
    end_date: '报告期',
    ann_date: '公告日',
    holder_count: '持仓家数',
    total_hold_amount: '前10总持仓量',
    total_hold_ratio: '前10总持仓占比(%)',
    holder_1: '前1流通股东',
    holder_2: '前2流通股东',
    holder_3: '前3流通股东',
    holder_4: '前4流通股东',
    holder_5: '前5流通股东',
    holder_6: '前6流通股东',
    holder_7: '前7流通股东',
    holder_8: '前8流通股东',
    holder_9: '前9流通股东',
    holder_10: '前10流通股东',
}

function applyEmptyTop10State() {
    finData.value = top10FloatHoldersEmptyData
    keyNameMap.value = top10FloatHoldersKeyNameMap
}


function handleFinButtonChange(value: string | number | boolean | undefined) {
    tushareApi.value = String(value ?? 'INDICATOR')
    // You can add additional logic here if needed, such as fetching new data
    console.log('Finance button changed to:', value)
}

function handleReportTypeChange(value: string | number | boolean | undefined) {
    reportType.value = String(value ?? 'FY')
}

async function fetchFinanceData(tsCode: string, tushareApi = 'INDICATOR', reportTypeValue = 'FY'): Promise<any | null> {
    const normalizedTsCode = String(tsCode || '').trim().toUpperCase()
    if (!normalizedTsCode || !baseURL) {
        return null
    }

    const normalizedApi = String(tushareApi || 'INDICATOR').trim().toUpperCase()
    const normalizedReportType = String(reportTypeValue || 'FY').trim().toUpperCase()
    const cacheKey = `${normalizedTsCode}|${normalizedApi}|${reportTypeSupportedApis.has(normalizedApi) ? normalizedReportType : '-'}`

    if (financeDataCache.has(cacheKey)) {
        return financeDataCache.get(cacheKey)
    }

    const pendingRequest = financeDataPending.get(cacheKey)
    if (pendingRequest) {
        return pendingRequest
    }

    const requestPromise = (async () => {
    try {
        const params: Record<string, string> = {}
        if (reportTypeSupportedApis.has(normalizedApi)) {
            params.report_type = normalizedReportType
            params.history = '1'
            params.limit = '5'
        }
        const response = await axios.get(`${baseURL}/tushare/${normalizedTsCode}/${normalizedApi}/`, { params })
        if (normalizedApi === 'INDICATOR') {
            const rows = Array.isArray(response?.data?.data) ? response.data.data : []
            const payload = {
                data: rows[0] || null,
                historyRows: rows,
                keyNameMap: fIndicatorKeyNameMap
            }
            financeDataCache.set(cacheKey, payload)
            return payload
        } else if (normalizedApi === 'TOP10_FLOATHOLDERS') {
            const top10Data = response?.data?.data
            if (!top10Data || Object.keys(top10Data).length === 0) {
                const payload = {
                    data: top10FloatHoldersEmptyData,
                    historyRows: [],
                    keyNameMap: top10FloatHoldersKeyNameMap
                }
                financeDataCache.set(cacheKey, payload)
                return payload
            }
            const payload = {
                data: top10Data as ITop10FloatHoldersData,
                historyRows: [],
                keyNameMap: top10FloatHoldersKeyNameMap
            }
            financeDataCache.set(cacheKey, payload)
            return payload
        } else if (normalizedApi === 'HOLD') {
            const rows = Array.isArray(response?.data?.data) ? response.data.data as IFundHoldingRow[] : []
            const summary = response?.data?.meta?.summary || null
            const payload = {
                data: summary,
                historyRows: rows,
                keyNameMap: {}
            }
            financeDataCache.set(cacheKey, payload)
            return payload
        } else {
            const payload = {
                data: response.data.data as IChipsData,
                historyRows: [],
                keyNameMap: chipsKeyNameMap
            }
            financeDataCache.set(cacheKey, payload)
            return payload
        }
    } catch (error) {
        console.error('Failed to fetch finance data:', error)
        if (normalizedApi === 'TOP10_FLOATHOLDERS') {
            return {
                data: top10FloatHoldersEmptyData,
                historyRows: [],
                keyNameMap: top10FloatHoldersKeyNameMap
            }
        }
        return null
    } finally {
        financeDataPending.delete(cacheKey)
    }
    })()

    financeDataPending.set(cacheKey, requestPromise)
    return requestPromise
}

function applyFinanceState(payload: any | null, api: string) {
    if (payload) {
        finData.value = payload.data
        finHistoryRows.value = Array.isArray(payload.historyRows) ? payload.historyRows : []
        keyNameMap.value = payload.keyNameMap || {}
        return
    }
    if (api === 'TOP10_FLOATHOLDERS') {
        applyEmptyTop10State()
        return
    }
    finData.value = null
    finHistoryRows.value = []
    keyNameMap.value = {}
}

watch(
    [() => stockTradeStore.tsCode, () => tushareApi.value, () => reportType.value],
    async ([newTsCode, newApi, newReportType]) => {
        const token = ++financeRequestToken.value
        const normalizedApi = String(newApi || 'INDICATOR').trim().toUpperCase()
        const payload = await fetchFinanceData(newTsCode, normalizedApi, newReportType)
        if (token !== financeRequestToken.value) {
            return
        }
        applyFinanceState(payload, normalizedApi)
    },
    { immediate: true }
)

// Initial fetch
onMounted(() => {
    updateViewportHeight()
    window.addEventListener('resize', updateViewportHeight)
})

onBeforeUnmount(() => {
    if (typeof window === 'undefined') {
        return
    }
    window.removeEventListener('resize', updateViewportHeight)
})

</script>

<style scoped>
.stocks-relevant {
    padding: 1rem;
}

.finance-card {
    display: flex;
    flex-direction: column;
}

.finance-card :deep(.el-card__body) {
    display: flex;
    flex-direction: column;
    min-height: 0;
}

@media (max-height: 900px) {
    .finance-card :deep(.el-card__header),
    .finance-card :deep(.el-card__footer) {
        padding-top: 10px;
        padding-bottom: 10px;
    }
}
</style>