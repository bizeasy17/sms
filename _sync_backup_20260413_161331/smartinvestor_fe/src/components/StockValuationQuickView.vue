<template>
  <el-card
    :class="{ 'embedded-valuation-card': embedded }"
    :shadow="embedded ? 'never' : 'always'"
    :body-style="embedded ? { padding: '0' } : undefined"
    :style="embedded ? 'border: none;' : ''"
  >
    <template #header>
      <el-row :gutter="8" align="middle">
        <el-col :span="9">
          <span style="font-weight: 600;">估值快览</span>
        </el-col>
        <el-col :span="7" style="text-align: center;">
          <el-radio-group v-model="bandPct" size="small">
            <el-radio-button label="0.05">5%</el-radio-button>
            <el-radio-button label="0.1">10%</el-radio-button>
            <el-radio-button label="0.15">15%</el-radio-button>
          </el-radio-group>
        </el-col>
        <el-col :span="8" style="text-align: right; font-size: 12px; color: #606266;">
          <span>现价: {{ formatPrice(currentPrice) }}</span>
          <span style="margin-left: 6px;" :style="{ color: stockTradeStore.pctChg >= 0 ? '#cf1322' : '#389e0d' }">
            {{ formatGap(stockTradeStore.pctChg) }}%
          </span>
          <span v-if="currentTradeDate" style="margin-left: 8px;">{{ currentTradeDate }}</span>
        </el-col>
      </el-row>
    </template>

    <el-skeleton :loading="loading" animated :rows="4">
      <template #default>
        <div style="font-size: 12px; color: #606266; margin-bottom: 8px;">
          阈值切换仅影响“判断”标签，不改变各方法估值价；标记“阈值敏感”表示偏离在 5%-15% 之间。
        </div>
        <div style="font-size: 12px; color: #606266; margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
          <span>估值风险:</span>
          <el-tag size="small" effect="light" :type="valuationRiskTagType(valuationRisk?.risk_level)">
            {{ valuationRisk?.risk_level || '-' }}
          </el-tag>
          <span>分数 {{ formatScore(valuationRisk?.risk_score) }}</span>
          <span style="color: #334155;">{{ valuationRisk?.summary || '-' }}</span>
        </div>
        <el-alert
          v-if="activeCorporateActionImpact"
          type="warning"
          :closable="false"
          show-icon
          style="margin-bottom: 8px;"
        >
          <template #title>
            检测到除权摊薄影响: 股本变化 {{ formatGap(activeCorporateActionImpact.share_change_ratio_pct) }}%
          </template>
          <template #default>
            <div style="font-size: 12px; line-height: 1.6; color: #7c2d12;">
              {{ activeCorporateActionImpact.message || '估值回落可能由股本扩张驱动，建议结合归一化口径观察。' }}
            </div>
            <div style="font-size: 12px; color: #92400e;">
              {{ corporateActionMeta }}
            </div>
          </template>
        </el-alert>
        <div style="font-size: 12px; color: #606266; margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
          <span>财报季:</span>
          <el-radio-group v-model="selectedEarningsReportType" size="small">
            <el-radio-button label="Q1">Q1</el-radio-button>
            <el-radio-button label="H1">H1</el-radio-button>
            <el-radio-button label="Q3">Q3</el-radio-button>
            <el-radio-button label="FY">FY</el-radio-button>
            <el-radio-button label="快">快报</el-radio-button>
            <el-radio-button label="FUSION">Fusion</el-radio-button>
          </el-radio-group>
        </div>
        <el-alert
          v-if="pegUnavailableHint"
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 8px;"
        >
          <template #title>PEG 在当前口径下不可用</template>
          <template #default>
            <div style="font-size: 12px; line-height: 1.6; color: #334155;">
              {{ pegUnavailableHint }}
            </div>
          </template>
        </el-alert>
        <el-row :gutter="8" style="margin-bottom: 8px;">
          <el-col :span="12">
            <div style="padding: 6px 8px; background: #f8fafc; border-radius: 6px; font-size: 12px;">
              <span style="color: #606266;">组合估值价:</span>
              <span style="margin-left: 6px; font-weight: 600;">{{ formatPrice(summary.composite_valuation_price) }}</span>
              <span style="margin-left: 8px; color: #606266;">{{ formatGap(summary.composite_valuation_gap_pct) }}%</span>
              <el-tag size="small" effect="light" style="margin-left: 8px;" :type="statusTagType(summary.composite_valuation_status)">{{ statusLabel(summary.composite_valuation_status) }}</el-tag>
              <div style="margin-top: 6px; color: #606266;">
                <span>估值财报:</span>
                <span style="margin-left: 6px;">{{ valuationReportMeta }}</span>
              </div>
              <div style="margin-top: 6px; color: #606266;">
                <span>统一股本口径(当前):</span>
                <span style="margin-left: 6px; font-weight: 600;">{{ formatPrice(summaryNormalized.composite_valuation_price) }}</span>
                <span style="margin-left: 8px;">{{ formatGap(summaryNormalized.composite_valuation_gap_pct) }}%</span>
                <el-tag size="small" effect="light" style="margin-left: 8px;" :type="statusTagType(summaryNormalized.composite_valuation_status)">
                  {{ statusLabel(summaryNormalized.composite_valuation_status) }}
                </el-tag>
              </div>
              <div style="margin-top: 6px; padding-top: 6px; border-top: 1px dashed #e5e7eb; color: #606266;">
                <span>预测信号:</span>
                <el-tag size="small" effect="light" style="margin-left: 6px;" :type="earningsActionTagType(earningsSignal?.action)">{{ earningsSignal?.action || '-' }}</el-tag>
                <span style="margin-left: 6px;">分数 {{ formatScore(earningsSignal?.signal_score) }}</span>
                <el-tag size="small" effect="light" style="margin-left: 6px;" :type="earningsRiskTagType(earningsSignal?.risk_level)">{{ earningsSignal?.risk_level || '-' }}</el-tag>
                <span style="margin-left: 8px; color: #334155;">
                  乐观目标价 {{ formatPrice(earningsSignal?.target_price_high ?? earningsSignal?.target_price) }} / 乐观目标市值 {{ formatMarketCap(earningsSignal?.target_market_cap_high ?? earningsSignal?.target_market_cap) }}
                </span>
                <span style="margin-left: 6px;">{{ earningsSignalMeta }}</span>
              </div>
            </div>
          </el-col>
          <el-col :span="12">
            <div style="padding: 6px 8px; background: #f8fafc; border-radius: 6px; font-size: 12px;">
              <span style="color: #606266;">保守估值价:</span>
              <span style="margin-left: 6px; font-weight: 600;">{{ formatPrice(summary.conservative_valuation_price) }}</span>
              <span style="margin-left: 8px; color: #606266;">{{ formatGap(summary.conservative_valuation_gap_pct) }}%</span>
              <el-tag size="small" effect="light" style="margin-left: 8px;" :type="statusTagType(summary.conservative_valuation_status)">{{ statusLabel(summary.conservative_valuation_status) }}</el-tag>
              <div style="margin-top: 6px; color: #606266;">
                <span>估值财报:</span>
                <span style="margin-left: 6px;">{{ valuationReportMeta }}</span>
              </div>
              <div style="margin-top: 6px; color: #606266;">
                <span>统一股本口径(当前):</span>
                <span style="margin-left: 6px; font-weight: 600;">{{ formatPrice(summaryNormalized.conservative_valuation_price) }}</span>
                <span style="margin-left: 8px;">{{ formatGap(summaryNormalized.conservative_valuation_gap_pct) }}%</span>
                <el-tag size="small" effect="light" style="margin-left: 8px;" :type="statusTagType(summaryNormalized.conservative_valuation_status)">
                  {{ statusLabel(summaryNormalized.conservative_valuation_status) }}
                </el-tag>
              </div>
              <div style="margin-top: 6px; padding-top: 6px; border-top: 1px dashed #e5e7eb; color: #606266;">
                <span>预测信号:</span>
                <el-tag size="small" effect="light" style="margin-left: 6px;" :type="earningsActionTagType(earningsSignal?.action)">{{ earningsSignal?.action || '-' }}</el-tag>
                <span style="margin-left: 6px;">分数 {{ formatScore(earningsSignal?.signal_score) }}</span>
                <el-tag size="small" effect="light" style="margin-left: 6px;" :type="earningsRiskTagType(earningsSignal?.risk_level)">{{ earningsSignal?.risk_level || '-' }}</el-tag>
                <span style="margin-left: 8px; color: #334155;">
                  保守目标价 {{ formatPrice(earningsSignal?.target_price_low ?? earningsSignal?.target_price) }} / 保守目标市值 {{ formatMarketCap(earningsSignal?.target_market_cap_low ?? earningsSignal?.target_market_cap) }}
                </span>
                <span style="margin-left: 6px;">{{ earningsSignalMeta }}</span>
              </div>
            </div>
          </el-col>
        </el-row>
        <el-tabs
          v-if="variantTabs.length > 1"
          v-model="activeVariant"
          class="valuation-variant-tabs"
          @tab-change="onVariantTabChange"
        >
          <el-tab-pane
            v-for="item in variantTabs"
            :key="item.valuation_variant"
            :name="item.valuation_variant"
            :label="item.label"
          />
        </el-tabs>
        <el-table :data="rows" size="small" style="width: 100%" empty-text="暂无估值数据">
          <el-table-column prop="valuation_method" label="方法" :width="95">
            <template #default="{ row }">
              <span>{{ methodLabel(row.valuation_method) }}</span>
              <el-tag
                v-if="row.corporate_action_impact?.impact_detected"
                size="small"
                effect="light"
                type="warning"
                style="margin-left: 6px;"
              >
                除权影响
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="valuation_price" label="估值价" :width="110">
            <template #default="{ row }">
              <span>{{ formatPrice(row.valuation_price) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="valuation_gap_pct" label="偏离(%)" :width="95">
            <template #default="{ row }">
              <span :style="{ color: Number(row.valuation_gap_pct || 0) >= 0 ? '#cf1322' : '#389e0d' }">
                {{ formatGap(row.valuation_gap_pct) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="valuation_status" label="判断" :width="90">
            <template #default="{ row }">
              <el-tag v-if="row.valuation_status === 'under'" type="danger" size="small" effect="light">低估</el-tag>
              <el-tag v-else-if="row.valuation_status === 'over'" type="success" size="small" effect="light">高估</el-tag>
              <el-tag v-else-if="row.valuation_status === 'fair'" type="info" size="small" effect="light">合理</el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="敏感" :width="90">
            <template #default="{ row }">
              <el-tag v-if="isThresholdSensitive(row.valuation_gap_pct)" type="warning" size="small" effect="light">阈值敏感</el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column prop="source" label="来源" :width="90">
            <template #default="{ row }">
              <el-tag v-if="row.source === 'snapshot_cache' || row.source === 'prefill_command'" type="warning" size="small" effect="light">缓存</el-tag>
              <el-tag v-else-if="row.source === 'live_compute'" type="primary" size="small" effect="light">实时</el-tag>
              <span v-else>{{ row.source || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="profit_data_source" label="财报来源" :width="130">
            <template #default="{ row }">
              <span>{{ row.profit_data_source || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="profit_report_end_date" label="财报期" :width="110">
            <template #default="{ row }">
              <span>{{ row.profit_report_end_date || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="归一化估值" :width="122" show-overflow-tooltip>
            <template #default="{ row }">
              <span>{{ formatPrice(row.valuation_price_normalized_to_latest_share) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="归一化偏离(%)" :width="122" show-overflow-tooltip>
            <template #default="{ row }">
              <span :style="{ color: Number(row.valuation_gap_pct_normalized_to_latest_share || 0) >= 0 ? '#cf1322' : '#389e0d' }">
                {{ formatGap(row.valuation_gap_pct_normalized_to_latest_share) }}
              </span>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </el-skeleton>
  </el-card>
</template>

<script setup lang="ts">
import { ElAlert, ElCard, ElCol, ElRadioButton, ElRadioGroup, ElRow, ElSkeleton, ElTable, ElTableColumn, ElTag, ElTabs, ElTabPane } from 'element-plus'
import axios from 'axios'
import { computed, inject, ref, watch, onMounted } from 'vue'
import { useStockTradeStore } from '../stores/stockTradeStore'
import { useStockChartFilterStore } from '../stores/stockChartFilterStore'

const props = defineProps({
  embedded: {
    type: Boolean,
    default: false,
  },
})
const embedded = props.embedded

type ValuationMethodRow = {
  valuation_method: string
  valuation_variant?: string
  valuation_price: number | null
  valuation_gap_pct: number | null
  valuation_status: string
  source: string | null
  profit_data_source?: string | null
  profit_report_end_date?: string | null
  profit_report_ann_date?: string | null
  profit_report_type?: string | null
  industry_level?: string | null
  industry_code?: string | null
  industry_name?: string | null
  compare_group?: string | null
  match_score?: number | null
  valuation_price_normalized_to_latest_share?: number | null
  valuation_gap_pct_normalized_to_latest_share?: number | null
  valuation_status_normalized_to_latest_share?: string | null
  snapshot_total_share?: number | null
  current_total_share?: number | null
  corporate_action_impact?: CorporateActionImpact | null
}

type CorporateActionDividendEvent = {
  end_date?: string | null
  ann_date?: string | null
  record_date?: string | null
  ex_date?: string | null
  pay_date?: string | null
  stock_distribution_ratio?: number | null
  cash_div_tax?: number | null
  div_proc?: string | null
}

type CorporateActionImpact = {
  impact_type?: string
  impact_detected?: boolean
  snapshot_trade_date?: string | null
  current_trade_date?: string | null
  snapshot_total_share?: number | null
  current_total_share?: number | null
  share_change_ratio_pct?: number | null
  latest_dividend_event?: CorporateActionDividendEvent | null
  message?: string | null
}

type ValuationVariantTab = {
  valuation_variant: string
  label: string
  industry_level?: string | null
  industry_code?: string | null
  industry_name?: string | null
  compare_group?: string | null
  match_score?: number | null
  method_count?: number
}

type ValuationSummary = {
  composite_valuation_price: number | null
  composite_valuation_status: string
  composite_valuation_gap_pct: number | null
  conservative_valuation_price: number | null
  conservative_valuation_status: string
  conservative_valuation_gap_pct: number | null
}

type EarningsSignal = {
  ts_code: string
  report_type: string
  signal_score: number | null
  action: string
  risk_level: string
  target_price: number | null
  target_market_cap: number | null
  target_return_pct: number | null
  target_price_low: number | null
  target_price_high: number | null
  target_market_cap_low: number | null
  target_market_cap_high: number | null
  target_return_low_pct: number | null
  target_return_high_pct: number | null
  model_version: string | null
  asof_date: string | null
  financial_fiscal_year: number | null
  financial_ann_date: string | null
}

type ValuationRisk = {
  risk_level: string
  risk_score: number | null
  summary: string | null
}

const baseURL = inject<string>('baseURL', '')
const stockTradeStore = useStockTradeStore()
const stockChartFilterStore = useStockChartFilterStore()

const rows = ref<ValuationMethodRow[]>([])
const dataByVariant = ref<Record<string, ValuationMethodRow[]>>({})
const summaryByVariant = ref<Record<string, ValuationSummary>>({})
const summaryByVariantNormalized = ref<Record<string, ValuationSummary>>({})
const variantTabs = ref<ValuationVariantTab[]>([])
const activeVariant = ref('default')
const currentPrice = ref<number | null>(null)
const currentTradeDate = ref<string>('')
const currentTotalShare = ref<number | null>(null)
const loading = ref(false)
const bandPct = ref('0.1')
const fetchSeq = ref(0)
const earningsSignal = ref<EarningsSignal | null>(null)
const valuationRisk = ref<ValuationRisk | null>(null)
const earningsDegradeReason = ref<string>('')
const selectedEarningsReportType = ref('FY')
const lastValuationReportType = ref('FY')
const summary = ref<ValuationSummary>({
  composite_valuation_price: null,
  composite_valuation_status: 'unknown',
  composite_valuation_gap_pct: null,
  conservative_valuation_price: null,
  conservative_valuation_status: 'unknown',
  conservative_valuation_gap_pct: null,
})
const summaryNormalized = ref<ValuationSummary>(emptySummary())

function emptySummary(): ValuationSummary {
  return {
    composite_valuation_price: null,
    composite_valuation_status: 'unknown',
    composite_valuation_gap_pct: null,
    conservative_valuation_price: null,
    conservative_valuation_status: 'unknown',
    conservative_valuation_gap_pct: null,
  }
}

function resolveSummary(raw: any): ValuationSummary {
  return {
    composite_valuation_price: raw?.composite_valuation_price ?? null,
    composite_valuation_status: String(raw?.composite_valuation_status || 'unknown'),
    composite_valuation_gap_pct: raw?.composite_valuation_gap_pct ?? null,
    conservative_valuation_price: raw?.conservative_valuation_price ?? null,
    conservative_valuation_status: String(raw?.conservative_valuation_status || 'unknown'),
    conservative_valuation_gap_pct: raw?.conservative_valuation_gap_pct ?? null,
  }
}

const methodLabelMap: Record<string, string> = {
  scarcity_overlay: '稀缺性',
  pe: 'PE',
  pb: 'PB',
  ps: 'PS',
  peg: 'PEG',
  fcff_dcf: 'FCFF',
  ddm: 'DDM',
  market_cap: '市值法',
}

function onVariantTabChange(tabName: string | number) {
  const variant = String(tabName || 'default')
  activeVariant.value = variant
  rows.value = (dataByVariant.value[variant] || []) as ValuationMethodRow[]
  summary.value = summaryByVariant.value[variant] || emptySummary()
  summaryNormalized.value = summaryByVariantNormalized.value[variant] || emptySummary()
}

function methodLabel(method: string) {
  return methodLabelMap[method] || method?.toUpperCase?.() || '-'
}

function formatPrice(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '-'
  return Number(value).toFixed(2)
}

function formatGap(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '-'
  return Number(value).toFixed(2)
}

function formatScore(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '-'
  return Number(value).toFixed(1)
}

function formatMarketCap(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '-'
  const numeric = Number(value)
  const absValue = Math.abs(numeric)
  // target_market_cap from BE is in 10k CNY (万元).
  if (absValue >= 1e4) {
    return `${(numeric / 1e4).toFixed(2)}亿`
  }
  return `${numeric.toFixed(2)}万`
}

function toCanonicalTsCode(code: string) {
  const normalized = String(code || '').trim().toUpperCase()
  if (!normalized) return ''
  if (normalized.includes('.')) return normalized
  if (!/^\d{6}$/.test(normalized)) return normalized
  if (normalized.startsWith('6') || normalized.startsWith('5') || normalized.startsWith('9')) {
    return `${normalized}.SH`
  }
  if (normalized.startsWith('8') || normalized.startsWith('4')) {
    return `${normalized}.BJ`
  }
  return `${normalized}.SZ`
}

function isSameTsCode(requestTsCode: string, returnedTsCode: string) {
  if (!requestTsCode || !returnedTsCode) return false
  const req = String(requestTsCode).trim().toUpperCase()
  const ret = String(returnedTsCode).trim().toUpperCase()
  if (req === ret) return true
  return toCanonicalTsCode(req) === toCanonicalTsCode(ret)
}

async function fetchEarningsSignalWithFallback(tsCodeCandidates: string[], requestSeq: number, reportType: string) {
  let degradedFallback: { candidate: string; payload: any } | null = null

  const isDefaultPlaceholder = (data: any) => {
    if (!data || typeof data !== 'object') return false
    const action = String(data.action || '').toUpperCase()
    const risk = String(data.risk_level || '').toUpperCase()
    const scoreMissing = data.signal_score === null || data.signal_score === undefined || data.signal_score === ''
    const noModel = !data.model_version
    const noAsOf = !data.asof_date
    return action === 'HOLD' && risk === 'MEDIUM' && scoreMissing && noModel && noAsOf
  }

  for (const candidate of tsCodeCandidates) {
    const encoded = encodeURIComponent(candidate)
    const normalizedReportType = String(reportType || '').toUpperCase()
    const reportTypeQuery = normalizedReportType && normalizedReportType !== 'EXP' && normalizedReportType !== 'EXPRESS' && normalizedReportType !== '快'
      ? `&report_type=${encodeURIComponent(normalizedReportType)}`
      : ''
    const url = `${baseURL}/earnings/signal/${encoded}/?ts_code=${encoded}${reportTypeQuery}&_t=${requestSeq}`
    try {
      const resp = await axios.get(url)
      const data = resp?.data?.data
      if (data && typeof data === 'object') {
        const degradeReason = String(resp?.data?.degrade?.reason || '')
        const degradedDefault = degradeReason === 'upstream_error_default' || isDefaultPlaceholder(data)
        if (degradedDefault) {
          if (!degradedFallback) {
            degradedFallback = { candidate, payload: resp.data }
          }
          continue
        }
        return { candidate, payload: resp.data }
      }
    } catch {
      continue
    }
  }
  return degradedFallback
}

function statusLabel(status: string) {
  if (status === 'under') return '低估'
  if (status === 'over') return '高估'
  if (status === 'fair') return '合理'
  return '-'
}

function statusTagType(status: string) {
  if (status === 'under') return 'danger'
  if (status === 'over') return 'success'
  return 'info'
}

function earningsActionTagType(action: string | undefined) {
  const normalized = String(action || '').toUpperCase()
  if (normalized === 'BUY') return 'danger'
  if (normalized === 'SELL' || normalized === 'SELL_PART') return 'success'
  return 'info'
}

function earningsRiskTagType(riskLevel: string | undefined) {
  const normalized = String(riskLevel || '').toUpperCase()
  if (normalized === 'HIGH') return 'danger'
  if (normalized === 'LOW') return 'success'
  return 'warning'
}

function valuationRiskTagType(riskLevel: string | undefined) {
  const normalized = String(riskLevel || '').toUpperCase()
  if (normalized === 'HIGH') return 'danger'
  if (normalized === 'LOW') return 'success'
  return 'warning'
}

const earningsSignalMeta = computed(() => {
  if (!earningsSignal.value) {
    return '-'
  }
  const parts: string[] = []
  if (earningsSignal.value.model_version) {
    parts.push(`模型 ${earningsSignal.value.model_version}`)
  }
  if (earningsSignal.value.report_type) {
    parts.push(`报告 ${earningsSignal.value.report_type}`)
  }
  if (earningsSignal.value.financial_fiscal_year) {
    parts.push(`信号财年 ${earningsSignal.value.financial_fiscal_year}`)
  }
  if (earningsSignal.value.financial_ann_date) {
    parts.push(`信号公告日 ${earningsSignal.value.financial_ann_date}`)
  }
  if (earningsSignal.value.asof_date) {
    parts.push(`信号截面 ${earningsSignal.value.asof_date}`)
  }
  if (earningsDegradeReason.value) {
    parts.push(`降级 ${earningsDegradeReason.value}`)
  }
  return parts.join(' | ') || '-'
})

const valuationReportMeta = computed(() => {
  const row = rows.value.find((item) => item.profit_report_end_date || item.profit_report_ann_date || item.profit_report_type)
  if (!row) {
    return '-'
  }
  const parts: string[] = []
  const profitSource = String(row.profit_data_source || '').toLowerCase()
  if (profitSource.startsWith('express')) {
    parts.push('口径 快报')
  }
  const reportType = String(row.profit_report_type || '').toUpperCase()
  if (reportType) {
    parts.push(`报告 ${reportType === 'ANNUAL' ? 'FY' : reportType}`)
  }
  if (row.profit_report_end_date) {
    parts.push(`财报期 ${row.profit_report_end_date}`)
  }
  if (row.profit_report_ann_date) {
    parts.push(`公告日 ${row.profit_report_ann_date}`)
  }
  return parts.join(' | ') || '-'
})

const effectiveValuationReportType = computed(() => {
  const selected = String(selectedEarningsReportType.value || '').toUpperCase()
  if (selected === 'FUSION') {
    return String(lastValuationReportType.value || 'FY').toUpperCase()
  }
  return selected
})

const hasPegRow = computed(() =>
  rows.value.some((item) => String(item.valuation_method || '').toLowerCase() === 'peg')
)

const pegUnavailableHint = computed(() => {
  if (loading.value) return ''
  if (!rows.value.length || hasPegRow.value) return ''

  const reportType = effectiveValuationReportType.value
  if (reportType === '快' || reportType === 'EXP' || reportType === 'EXPRESS') {
    return '快报口径会按 express 快报快照筛选；若该股当前没有可用快报估值快照，对应方法不会显示。'
  }
  if (reportType === 'FY' || reportType === 'ANNUAL') {
    return 'FY 口径会按 ANNUAL 快照筛选；若该股无 ANNUAL PEG 快照，或净利润同比增速 <= 0，PEG 会被自动跳过。'
  }

  return 'PEG 仅在“净利润同比增速为正 + 当前报告期存在可用快照”时展示；否则系统会自动跳过。'
})

const activeCorporateActionImpact = computed<CorporateActionImpact | null>(() => {
  const impacted = rows.value.find((item) => item.corporate_action_impact?.impact_detected)
  return impacted?.corporate_action_impact || null
})

const corporateActionMeta = computed(() => {
  const impact = activeCorporateActionImpact.value
  if (!impact) return '-'
  const evt = impact.latest_dividend_event || {}
  const parts: string[] = []
  if (evt.ex_date) parts.push(`除权日 ${evt.ex_date}`)
  if (evt.record_date) parts.push(`股权登记日 ${evt.record_date}`)
  if (Number.isFinite(Number(evt.stock_distribution_ratio))) {
    parts.push(`送转比例 ${Number(evt.stock_distribution_ratio).toFixed(2)}`)
  }
  if (Number.isFinite(Number(currentTotalShare.value))) {
    parts.push(`当前总股本 ${Number(currentTotalShare.value).toFixed(2)}万股`)
  }
  return parts.join(' | ') || '-'
})

function isThresholdSensitive(gapPct: number | null | undefined) {
  const absGap = Math.abs(Number(gapPct ?? NaN))
  if (!Number.isFinite(absGap)) return false
  return absGap > 5 && absGap <= 15
}

async function fetchValuationRows() {
  const tsCode = stockTradeStore.tsCode
  const normalizedTsCode = String(tsCode || '').trim().toUpperCase()
  const canonicalTsCode = toCanonicalTsCode(normalizedTsCode)
  const requestSeq = ++fetchSeq.value
  if (!normalizedTsCode || !baseURL) {
    rows.value = []
    currentPrice.value = null
    currentTradeDate.value = ''
    currentTotalShare.value = null
    earningsSignal.value = null
    valuationRisk.value = null
    earningsDegradeReason.value = ''
    summaryNormalized.value = emptySummary()
    return
  }

  loading.value = true
  try {
    const freq = stockChartFilterStore.freq || 'D'
    const selectedReportType = String(selectedEarningsReportType.value || '').toUpperCase()
    const valuationReportType = selectedReportType === 'FUSION'
      ? String(lastValuationReportType.value || 'FY').toUpperCase()
      : selectedReportType
    if (selectedReportType && selectedReportType !== 'FUSION' && selectedReportType !== '快') {
      lastValuationReportType.value = selectedReportType
    }
    const valuationReportTypeQuery = valuationReportType
      ? `&earnings_report_type=${encodeURIComponent(valuationReportType)}`
      : ''
    const valuationTsCodeCandidates = Array.from(
      new Set([normalizedTsCode, canonicalTsCode].filter((code) => Boolean(code)))
    )
    let res: any = null
    let valuationFetchError: unknown = null
    for (const candidate of valuationTsCodeCandidates) {
      const valuationUrl = `${baseURL}/stocks/${encodeURIComponent(candidate)}/valuation/methods/?freq=${freq}&valuation_band_pct=${bandPct.value}${valuationReportTypeQuery}`
      try {
        res = await axios.get(valuationUrl)
        if (res?.data && typeof res.data === 'object') {
          break
        }
      } catch (error) {
        valuationFetchError = error
      }
    }
    if (!res?.data || typeof res.data !== 'object') {
      throw valuationFetchError || new Error('valuation_methods_unavailable')
    }
    if (requestSeq !== fetchSeq.value || normalizedTsCode !== String(stockTradeStore.tsCode || '').trim().toUpperCase()) {
      return
    }
    const variantList = Array.isArray(res.data?.valuation_variants)
      ? (res.data.valuation_variants as ValuationVariantTab[])
      : []
    const variantPayload =
      res.data?.data_by_variant && typeof res.data.data_by_variant === 'object'
        ? (res.data.data_by_variant as Record<string, ValuationMethodRow[]>)
        : {}
    const summaryPayload =
      res.data?.summary_by_variant && typeof res.data.summary_by_variant === 'object'
        ? Object.fromEntries(
            Object.entries(res.data.summary_by_variant as Record<string, unknown>).map(([variant, payload]) => [
              variant,
              resolveSummary(payload),
            ])
          )
        : {}
    const summaryPayloadNormalized =
      res.data?.summary_by_variant_normalized_to_latest_share && typeof res.data.summary_by_variant_normalized_to_latest_share === 'object'
        ? Object.fromEntries(
            Object.entries(res.data.summary_by_variant_normalized_to_latest_share as Record<string, unknown>).map(([variant, payload]) => [
              variant,
              resolveSummary(payload),
            ])
          )
        : {}
    const riskByVariant =
      res.data?.valuation_risk_by_variant && typeof res.data.valuation_risk_by_variant === 'object'
        ? (res.data.valuation_risk_by_variant as Record<string, any>)
        : {}

    variantTabs.value = variantList
    dataByVariant.value = variantPayload
    summaryByVariant.value = summaryPayload
    summaryByVariantNormalized.value = summaryPayloadNormalized

    const resolvedActive = String(
      res.data?.active_valuation_variant ||
      variantList?.[0]?.valuation_variant ||
      'default'
    )
    activeVariant.value = resolvedActive

    const resolvedRows = variantPayload[resolvedActive]
    rows.value = Array.isArray(resolvedRows)
      ? resolvedRows
      : ((res.data?.data || []) as ValuationMethodRow[])
    currentPrice.value = Number(res.data?.current_price)
    currentTradeDate.value = String(res.data?.current_trade_date || '')
    currentTotalShare.value = Number.isFinite(Number(res.data?.current_total_share)) ? Number(res.data?.current_total_share) : null
    summary.value = summaryPayload[resolvedActive] || resolveSummary(res.data?.summary)
    summaryNormalized.value = summaryPayloadNormalized[resolvedActive] || resolveSummary(res.data?.summary_normalized_to_latest_share)
    const activeRisk = riskByVariant[resolvedActive] || res.data?.valuation_risk || null
    valuationRisk.value = activeRisk
      ? {
          risk_level: String(activeRisk.risk_level || ''),
          risk_score: Number.isFinite(Number(activeRisk.risk_score)) ? Number(activeRisk.risk_score) : null,
          summary: activeRisk.summary ? String(activeRisk.summary) : null,
        }
      : null

    const valuationTsCode = String(res.data?.ts_code || '').trim().toUpperCase()
    // Respect store ts_code as source of truth to avoid suffix mutation on FE side.
    const earningsTsCodeCandidates = Array.from(
      new Set([normalizedTsCode, canonicalTsCode, valuationTsCode].filter((code) => Boolean(code)))
    )
    const earningsResp = await fetchEarningsSignalWithFallback(
      earningsTsCodeCandidates,
      requestSeq,
      selectedEarningsReportType.value
    )
    if (requestSeq !== fetchSeq.value || normalizedTsCode !== String(stockTradeStore.tsCode || '').trim().toUpperCase()) {
      return
    }

    const earningsData = earningsResp?.payload?.data
    if (earningsData && typeof earningsData === 'object') {
      const returnedTsCode = String(earningsData.ts_code || '').trim().toUpperCase()
      if (returnedTsCode && !isSameTsCode(valuationTsCode || canonicalTsCode || normalizedTsCode, returnedTsCode)) {
        earningsSignal.value = null
        earningsDegradeReason.value = 'ts_code_mismatch'
        return
      }
      earningsSignal.value = {
        ts_code: String(earningsData.ts_code || normalizedTsCode),
        report_type: String(earningsData.report_type || selectedEarningsReportType.value || 'UNKNOWN').toUpperCase(),
        signal_score: Number.isFinite(Number(earningsData.signal_score)) ? Number(earningsData.signal_score) : null,
        action: String(earningsData.action || ''),
        risk_level: String(earningsData.risk_level || ''),
        target_price: Number.isFinite(Number(earningsData.target_price)) ? Number(earningsData.target_price) : null,
        target_market_cap: Number.isFinite(Number(earningsData.target_market_cap)) ? Number(earningsData.target_market_cap) : null,
        target_return_pct: Number.isFinite(Number(earningsData.target_return_pct)) ? Number(earningsData.target_return_pct) : null,
        target_price_low: Number.isFinite(Number(earningsData.target_price_low)) ? Number(earningsData.target_price_low) : null,
        target_price_high: Number.isFinite(Number(earningsData.target_price_high)) ? Number(earningsData.target_price_high) : null,
        target_market_cap_low: Number.isFinite(Number(earningsData.target_market_cap_low)) ? Number(earningsData.target_market_cap_low) : null,
        target_market_cap_high: Number.isFinite(Number(earningsData.target_market_cap_high)) ? Number(earningsData.target_market_cap_high) : null,
        target_return_low_pct: Number.isFinite(Number(earningsData.target_return_low_pct)) ? Number(earningsData.target_return_low_pct) : null,
        target_return_high_pct: Number.isFinite(Number(earningsData.target_return_high_pct)) ? Number(earningsData.target_return_high_pct) : null,
        model_version: earningsData.model_version ? String(earningsData.model_version) : null,
        asof_date: earningsData.asof_date ? String(earningsData.asof_date) : null,
        financial_fiscal_year: Number.isFinite(Number(earningsData.financial_fiscal_year)) ? Number(earningsData.financial_fiscal_year) : null,
        financial_ann_date: earningsData.financial_ann_date ? String(earningsData.financial_ann_date) : null,
      }
      earningsDegradeReason.value = String(earningsResp?.payload?.degrade?.reason || '')
    } else {
      earningsSignal.value = null
      earningsDegradeReason.value = 'signal_unavailable'
    }
  } catch (error) {
    if (requestSeq !== fetchSeq.value || tsCode !== stockTradeStore.tsCode) {
      return
    }
    rows.value = []
    dataByVariant.value = {}
    summaryByVariant.value = {}
    summaryByVariantNormalized.value = {}
    variantTabs.value = []
    activeVariant.value = 'default'
    currentPrice.value = null
    currentTradeDate.value = ''
    currentTotalShare.value = null
    summary.value = emptySummary()
    summaryNormalized.value = emptySummary()
    earningsSignal.value = null
    valuationRisk.value = null
    earningsDegradeReason.value = ''
    console.error('Failed to fetch valuation quick view:', error)
  } finally {
    if (requestSeq === fetchSeq.value) {
      loading.value = false
    }
  }
}

watch(
  [() => stockTradeStore.tsCode, () => bandPct.value, () => selectedEarningsReportType.value],
  () => {
    fetchValuationRows()
  }
)

onMounted(() => {
  fetchValuationRows()
})
</script>

<style scoped>
:deep(.embedded-valuation-card .el-card__header) {
  padding: 10px 12px 8px;
}

:deep(.embedded-valuation-card .el-card__body) {
  padding: 0 0 2px;
}
</style>
