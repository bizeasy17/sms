<template>
    <section class="stock-extreme-summary" :class="{ 'is-expanded': expanded }">
        <div
            class="extreme-summary-header"
            role="button"
            tabindex="0"
            :aria-expanded="expanded"
            @click="toggleExpanded"
            @keydown.enter.prevent="toggleExpanded"
            @keydown.space.prevent="toggleExpanded"
        >
            <div class="extreme-summary-heading">
                <span class="extreme-summary-title">历史极值</span>
                <span class="price-type-badge">{{ priceTypeLabel }}</span>
                <span class="extreme-summary-date">截至 {{ sourceEndDate }}</span>
            </div>
            <el-tooltip :content="expanded ? '收起历史极值' : '展开历史极值'" placement="top">
                <el-button
                    text
                    circle
                    class="extreme-toggle-button"
                    :aria-label="expanded ? '收起历史极值' : '展开历史极值'"
                    @click.stop="toggleExpanded"
                >
                    <el-icon><ArrowUp v-if="expanded" /><ArrowDown v-else /></el-icon>
                </el-button>
            </el-tooltip>
        </div>

        <Transition name="extreme-expand">
            <div v-if="expanded" class="extreme-summary-body">
                <div v-if="loading" class="extreme-loading" aria-label="历史极值加载中">
                    <span v-for="index in 6" :key="index" class="extreme-loading-line" />
                </div>
                <div v-else-if="errorMessage" class="extreme-state extreme-state-error">
                    {{ errorMessage }}
                </div>
                <div v-else-if="!extremeData" class="extreme-state">暂无历史极值</div>
                <div v-else class="extreme-metric-grid">
                    <section class="extreme-group interval-group">
                        <h4 class="extreme-group-title">区间表现</h4>
                        <div class="extreme-metric-row">
                            <span class="extreme-metric-label">
                                最大上涨
                                <el-tooltip content="历史低点到其后高点的最大涨幅" placement="top">
                                    <el-icon class="metric-info-icon"><InfoFilled /></el-icon>
                                </el-tooltip>
                            </span>
                            <span class="extreme-value value-up">{{ formatPercent(extremeData.max_runup, true) }}</span>
                        </div>
                        <div class="extreme-metric-row">
                            <span class="extreme-metric-label">
                                最大回撤
                                <el-tooltip content="历史高点到其后低点的最大跌幅" placement="top">
                                    <el-icon class="metric-info-icon"><InfoFilled /></el-icon>
                                </el-tooltip>
                            </span>
                            <span class="extreme-value value-down">{{ formatPercent(extremeData.max_drawdown) }}</span>
                        </div>
                    </section>

                    <section class="extreme-group period-group">
                        <h4 class="extreme-group-title">单周期极值</h4>
                        <div v-for="period in periodRows" :key="period.label" class="period-metric-row">
                            <span class="period-label">{{ period.label }}</span>
                            <span class="extreme-value value-up">{{ formatPercent(period.max, true) }}</span>
                            <span class="period-separator">/</span>
                            <span class="extreme-value value-down">{{ formatPercent(period.min) }}</span>
                        </div>
                    </section>

                    <section class="extreme-group valuation-group">
                        <h4 class="extreme-group-title">最新估值</h4>
                        <div class="valuation-metrics">
                            <div v-for="metric in valuationRows" :key="metric.label" class="extreme-metric-row">
                                <span class="extreme-metric-label">{{ metric.label }}</span>
                                <span class="extreme-value value-neutral">{{ formatValuation(metric.value) }}</span>
                            </div>
                        </div>
                    </section>
                </div>
            </div>
        </Transition>
    </section>
</template>

<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import axios from 'axios'
import { ElButton, ElIcon, ElTooltip } from 'element-plus'
import { ArrowDown, ArrowUp, InfoFilled } from '@element-plus/icons-vue'
import { useStockTradeStore } from '../stores/stockTradeStore'

type NullableNumber = number | null

interface StockExtremeRecord {
    code: string
    name: string
    max_runup: NullableNumber
    max_drawdown: NullableNumber
    daily_max_return: NullableNumber
    daily_min_return: NullableNumber
    weekly_max_return: NullableNumber
    weekly_min_return: NullableNumber
    monthly_max_return: NullableNumber
    monthly_min_return: NullableNumber
    PE: NullableNumber
    PB: NullableNumber
    PS: NullableNumber
    source_end_date: string | null
    price_type: string
}

const extremeCache = new Map<string, StockExtremeRecord | null>()
const pendingRequests = new Map<string, Promise<StockExtremeRecord | null>>()

const stockTradeStore = useStockTradeStore()
const baseURL = inject<string>('baseURL', '')
const expanded = ref(false)
const loading = ref(false)
const errorMessage = ref('')
const extremeData = ref<StockExtremeRecord | null>(null)
let requestSequence = 0

const sourceEndDate = computed(() => extremeData.value?.source_end_date || '-')
const priceTypeLabel = computed(() => {
    const priceType = extremeData.value?.price_type || 'qfq'
    return ({ qfq: '前复权', hfq: '后复权', raw: '不复权' } as Record<string, string>)[priceType] || priceType
})
const periodRows = computed(() => [
    { label: '日', max: extremeData.value?.daily_max_return ?? null, min: extremeData.value?.daily_min_return ?? null },
    { label: '周', max: extremeData.value?.weekly_max_return ?? null, min: extremeData.value?.weekly_min_return ?? null },
    { label: '月', max: extremeData.value?.monthly_max_return ?? null, min: extremeData.value?.monthly_min_return ?? null },
])
const valuationRows = computed(() => [
    { label: 'PE', value: extremeData.value?.PE ?? null },
    { label: 'PB', value: extremeData.value?.PB ?? null },
    { label: 'PS', value: extremeData.value?.PS ?? null },
])

function normalizeRecord(payload: unknown): StockExtremeRecord | null {
    if (!payload || typeof payload !== 'object') return null
    const responseData = payload as { data?: { results?: unknown[] } }
    const record = responseData.data?.results?.[0]
    return record && typeof record === 'object' ? record as StockExtremeRecord : null
}

async function requestExtremeData(code: string): Promise<StockExtremeRecord | null> {
    const existingRequest = pendingRequests.get(code)
    if (existingRequest) return existingRequest

    const request = axios.get(`${baseURL}/v1/stocks/extremes/`, {
        params: { code },
    }).then((response) => normalizeRecord(response.data))
        .finally(() => pendingRequests.delete(code))
    pendingRequests.set(code, request)
    return request
}

async function loadExtremeData(codeValue: string) {
    const code = String(codeValue || '').trim().toUpperCase()
    const sequence = ++requestSequence
    errorMessage.value = ''

    if (!code) {
        extremeData.value = null
        loading.value = false
        return
    }
    if (extremeCache.has(code)) {
        extremeData.value = extremeCache.get(code) ?? null
        loading.value = false
        return
    }

    loading.value = true
    try {
        const record = await requestExtremeData(code)
        extremeCache.set(code, record)
        if (sequence === requestSequence && code === String(stockTradeStore.tsCode || '').trim().toUpperCase()) {
            extremeData.value = record
        }
    } catch (error) {
        if (sequence === requestSequence) {
            extremeData.value = null
            errorMessage.value = '极值数据暂不可用'
        }
    } finally {
        if (sequence === requestSequence) loading.value = false
    }
}

function toggleExpanded() {
    expanded.value = !expanded.value
    if (expanded.value) void loadExtremeData(stockTradeStore.tsCode)
}

function formatPercent(value: NullableNumber, showPositiveSign = false): string {
    const numeric = Number(value)
    if (value === null || value === undefined || !Number.isFinite(numeric)) return '-'
    const percentage = numeric * 100
    const prefix = showPositiveSign && percentage > 0 ? '+' : ''
    return `${prefix}${percentage.toFixed(2)}%`
}

function formatValuation(value: NullableNumber): string {
    const numeric = Number(value)
    if (value === null || value === undefined || !Number.isFinite(numeric)) return '-'
    return numeric.toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}

watch(
    () => stockTradeStore.tsCode,
    (code) => {
        requestSequence += 1
        errorMessage.value = ''
        extremeData.value = extremeCache.get(String(code || '').trim().toUpperCase()) ?? null
        loading.value = false
        if (expanded.value) void loadExtremeData(code)
    },
)
</script>

<style scoped>
.stock-extreme-summary {
    container-type: inline-size;
    margin-top: 8px;
    overflow: hidden;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    background: #f8fafc;
}

.extreme-summary-header {
    min-height: 32px;
    padding: 0 8px 0 10px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    cursor: pointer;
    user-select: none;
}

.extreme-summary-header:focus-visible {
    outline: 2px solid #409eff;
    outline-offset: -2px;
}

.extreme-summary-heading {
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
}

.extreme-summary-title {
    color: #303133;
    font-size: 12px;
    font-weight: 600;
}

.price-type-badge {
    padding: 1px 5px;
    border: 1px solid #dcdfe6;
    border-radius: 3px;
    color: #606266;
    background: #fff;
    font-size: 11px;
    line-height: 16px;
}

.extreme-summary-date {
    color: #909399;
    font-size: 11px;
}

.extreme-toggle-button {
    flex: 0 0 auto;
    width: 26px;
    height: 26px;
    color: #606266;
}

.extreme-summary-body {
    border-top: 1px solid #e5e7eb;
    padding: 8px 10px 10px;
}

.extreme-metric-grid {
    display: grid;
    grid-template-columns: minmax(150px, 0.9fr) minmax(230px, 1.35fr) minmax(120px, 0.7fr);
}

.extreme-group {
    min-width: 0;
    padding: 0 14px;
    border-left: 1px solid #e5e7eb;
}

.extreme-group:first-child {
    padding-left: 0;
    border-left: 0;
}

.extreme-group:last-child {
    padding-right: 0;
}

.extreme-group-title {
    margin: 0 0 4px;
    color: #909399;
    font-size: 11px;
    font-weight: 600;
    line-height: 16px;
}

.extreme-metric-row,
.period-metric-row {
    min-height: 20px;
    display: flex;
    align-items: center;
    gap: 6px;
}

.extreme-metric-row {
    justify-content: space-between;
}

.extreme-metric-label,
.period-label {
    color: #606266;
    font-size: 11px;
    white-space: nowrap;
}

.extreme-metric-label {
    display: inline-flex;
    align-items: center;
    gap: 3px;
}

.metric-info-icon {
    color: #a8abb2;
    font-size: 12px;
    cursor: help;
}

.period-label {
    width: 18px;
    flex: 0 0 auto;
}

.period-metric-row .extreme-value {
    min-width: 72px;
    text-align: right;
}

.period-separator {
    color: #c0c4cc;
    font-size: 11px;
}

.extreme-value {
    font-size: 14px;
    line-height: 20px;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}

.value-up {
    color: #cf1322;
}

.value-down {
    color: #389e0d;
}

.value-neutral {
    color: #303133;
}

.extreme-state {
    height: 60px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #909399;
    font-size: 12px;
}

.extreme-state-error {
    color: #b88230;
}

.extreme-loading {
    height: 60px;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px 24px;
    align-content: center;
}

.extreme-loading-line {
    height: 12px;
    border-radius: 3px;
    background: linear-gradient(90deg, #ebeef5 25%, #f5f7fa 50%, #ebeef5 75%);
    background-size: 200% 100%;
    animation: extreme-loading 1.2s ease-in-out infinite;
}

.extreme-expand-enter-active,
.extreme-expand-leave-active {
    transition: opacity 0.16s ease, transform 0.16s ease;
    transform-origin: top;
}

.extreme-expand-enter-from,
.extreme-expand-leave-to {
    opacity: 0;
    transform: scaleY(0.96);
}

@keyframes extreme-loading {
    from { background-position: 100% 0; }
    to { background-position: -100% 0; }
}

@container (max-width: 720px) {
    .extreme-metric-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        row-gap: 10px;
    }

    .valuation-group {
        grid-column: 1 / -1;
        padding: 8px 0 0;
        border-top: 1px solid #e5e7eb;
        border-left: 0;
    }

    .valuation-metrics {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 16px;
    }
}

@container (max-width: 500px) {
    .extreme-metric-grid {
        grid-template-columns: 1fr;
    }

    .valuation-metrics {
        grid-template-columns: 1fr;
        gap: 0;
    }

    .extreme-group,
    .extreme-group:first-child {
        padding: 8px 0 0;
        border-top: 1px solid #e5e7eb;
        border-left: 0;
    }

    .extreme-group:first-child {
        padding-top: 0;
        border-top: 0;
    }
}
</style>
