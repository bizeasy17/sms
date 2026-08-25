<template>
    <el-row :gutter="18">
        <el-col :span="24">
            <el-card>
                    <el-row v-if="showFinancialStageHint" style="margin-bottom: 8px;">
                        <el-col :span="24">
                            <el-tag size="small" type="warning" effect="light">
                                财务条件二阶段过滤已启用：首轮先按估值/风险出候选，再按净利YoY、EBITYoY和上一年净利/EBIT条件过滤。
                            </el-tag>
                        </el-col>
                    </el-row>
                    <el-row v-if="resultStatusText" style="margin-bottom: 8px;">
                        <el-col :span="24">
                            <div style="display:flex; flex-direction:column; gap:6px;">
                                <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap; font-size:12px; color:#606266;">
                                    <el-tag size="small" :type="isResultLoading ? 'warning' : 'success'" effect="light">{{ resultStatusText }}</el-tag>
                                    <span v-if="resultMessage">{{ resultMessage }}</span>
                                    <span v-if="jobMatchedCount > 0">已命中 {{ jobMatchedCount }} 条</span>
                                    <span v-if="jobTotalCandidates > 0">候选 {{ jobTotalCandidates }} 支</span>
                                </div>
                                <el-progress
                                    v-if="isResultLoading"
                                    :percentage="isFinancialMode ? financialProgressPct : jobProgressPct"
                                    :stroke-width="12"
                                />
                            </div>
                        </el-col>
                    </el-row>
                    <el-row>
                        <el-col :span="24">
                            <div ref="tableWrapperRef" class="result-table-wrapper">
                            <el-table v-loading="isResultLoading" :data="pickingResult" style="width: 100%" size="small" :height="tableHeight" @row-dblclick="onRowDblClick">
                                    <el-table-column prop="ts_code" label="代码" fixed="left">
                                        <template #default="{ row }">
                                            <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                                                <el-link
                                                    type="primary"
                                                    :href="resolveCompanyWebsiteUrl(row.website_url, row.website) || undefined"
                                                    target="_blank"
                                                    style="font-size:12px"
                                                    underline="never"
                                                >{{ row.name + ' | ' + row.ts_code }}</el-link>
                                                <RecentReportBadge :visible="row.recent_report_badge" />
                                            </div>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="!isFinancialMode" prop="signal_peak_return_pct" label="最高涨幅(%)" :width="138">
                                        <template #default="{ row }">
                                            <span :style="{ color: (row.signal_peak_return_pct || 0) >= 0 ? 'red' : 'green' }">{{ formatPercentWithSymbol(row.signal_peak_return_pct) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="!isFinancialMode" prop="signal_trough_return_pct" label="最低涨幅(%)" :width="138">
                                        <template #default="{ row }">
                                            <span :style="{ color: (row.signal_trough_return_pct || 0) >= 0 ? 'red' : 'green' }">{{ formatPercentWithSymbol(row.signal_trough_return_pct) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="!isFinancialMode" prop="signal_current_return_pct" label="当前涨幅(%)" :width="138">
                                        <template #default="{ row }">
                                            <span :style="{ color: (row.signal_current_return_pct || 0) >= 0 ? 'red' : 'green' }">{{ formatPercentWithSymbol(row.signal_current_return_pct) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="sw_l3_name" label="SW行业" :width="150">
                                        <template #default="{ row }">
                                            <span>{{ row.sw_l3_name || row.industry_name || '-' }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="isFinancialMode" prop="financial_end_date" label="财报期" :width="96" />
                                    <el-table-column v-if="isFinancialMode" prop="financial_ann_date" label="公告日" :width="96" />
                                    <el-table-column v-if="isFinancialMode" prop="revenue_yoy_pct" label="营收YoY(%)" :width="105"><template #default="{ row }">{{ formatPercent(row.revenue_yoy_pct) }}</template></el-table-column>
                                    <el-table-column v-if="isFinancialMode" prop="revenue_qoq_pct" label="营收QoQ(%)" :width="105"><template #default="{ row }">{{ formatPercent(row.revenue_qoq_pct) }}</template></el-table-column>
                                    <el-table-column v-if="isFinancialMode" prop="netprofit_yoy_pct" label="净利YoY(%)" :width="105"><template #default="{ row }">{{ formatPercent(row.netprofit_yoy_pct) }}</template></el-table-column>
                                    <el-table-column v-if="isFinancialMode" prop="netprofit_qoq_pct" label="净利QoQ(%)" :width="105"><template #default="{ row }">{{ formatPercent(row.netprofit_qoq_pct) }}</template></el-table-column>
                                    <el-table-column v-if="isFinancialMode" prop="ebit_yoy_pct" label="EBITYoY(%)" :width="105"><template #default="{ row }">{{ formatPercent(row.ebit_yoy_pct) }}</template></el-table-column>
                                    <el-table-column v-if="isFinancialMode" prop="ebit_qoq_pct" label="EBITQoQ(%)" :width="105"><template #default="{ row }">{{ formatPercent(row.ebit_qoq_pct) }}</template></el-table-column>
                                    <el-table-column v-if="isFinancialMode" prop="roe_pct" label="ROE(%)" :width="88"><template #default="{ row }">{{ formatPercent(row.roe_pct) }}</template></el-table-column>
                                    <el-table-column v-if="isFinancialMode" prop="roe_dt_pct" label="扣非ROE(%)" :width="98"><template #default="{ row }">{{ formatPercent(row.roe_dt_pct) }}</template></el-table-column>
                                    <el-table-column v-if="isFinancialMode" prop="financial_score" label="财务分" :width="80"><template #default="{ row }">{{ formatScore(row.financial_score) }}</template></el-table-column>
                                    <el-table-column v-if="isFinancialMode" prop="traditional_valuation_price" label="传统估值价" :width="105"><template #default="{ row }">{{ formatPrice(row.traditional_valuation_price) }}</template></el-table-column>
                                    <el-table-column v-if="isFinancialMode" prop="traditional_conservative_price" label="传统保守价" :width="105"><template #default="{ row }">{{ formatPrice(row.traditional_conservative_price) }}</template></el-table-column>
                                    <el-table-column v-if="isFinancialMode" prop="traditional_valuation_score" label="传统估值分" :width="98"><template #default="{ row }">{{ formatScore(row.traditional_valuation_score) }}</template></el-table-column>
                                    <el-table-column v-if="isFinancialMode" prop="predictive_signal_score" label="预测信号分" :width="98"><template #default="{ row }">{{ formatScore(row.predictive_signal_score) }}</template></el-table-column>
                                    <el-table-column v-if="isFinancialMode" prop="predictive_action" label="预测建议" :width="90"><template #default="{ row }">{{ actionLabel(row.predictive_action) }}</template></el-table-column>
                                    <el-table-column v-if="isFinancialMode" prop="predictive_risk_level" label="预测风险" :width="90"><template #default="{ row }">{{ riskLabel(row.predictive_risk_level) }}</template></el-table-column>
                                    <el-table-column v-if="isFinancialMode" prop="predictive_target_price" label="预测目标价" :width="98"><template #default="{ row }">{{ formatPrice(row.predictive_target_price) }}</template></el-table-column>
                                    <el-table-column v-if="isFinancialMode" prop="predictive_target_return_pct" label="预测收益(%)" :width="105"><template #default="{ row }">{{ formatPercent(row.predictive_target_return_pct) }}</template></el-table-column>
                                    <el-table-column v-if="!isFinancialMode" prop="valuation_method" label="估值法" :width="90">
                                        <template #default="{ row }">
                                            <span>{{ methodLabel(row.valuation_method) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="!isFinancialMode" prop="close_qfq" label="当前价格" :width="90">
                                        <template #default="{ row }">
                                            <span>{{ formatPrice(row.close_qfq) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="!isFinancialMode" prop="valuation_price" label="估值价" :width="90" />
                                    <el-table-column v-if="!isFinancialMode" prop="valuation_snapshot_updated_at" label="快照更新时间" :width="170">
                                        <template #default="{ row }">
                                            <span>{{ formatDateTime(row.valuation_snapshot_updated_at) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="!isFinancialMode" prop="valuation_profit_report_ann_date" label="财报发布日" :width="120">
                                        <template #default="{ row }">
                                            <span>{{ formatDateOnly(row.valuation_profit_report_ann_date || row.financial_ann_date) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="!isFinancialMode" prop="conservative_valuation_price" label="保守估值价" :width="110">
                                        <template #default="{ row }">
                                            <span>{{ formatPrice(row.conservative_valuation_price) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="!isFinancialMode" prop="composite_valuation_price" label="组合估值价" :width="110">
                                        <template #default="{ row }">
                                            <span>{{ formatPrice(row.composite_valuation_price) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="!isFinancialMode" prop="valuation_gap_pct" label="偏离(%)" :width="90">
                                        <template #default="{ row }">
                                            <span :style="{ color: (row.valuation_gap_pct || 0) >= 0 ? 'red' : 'green' }">{{ row.valuation_gap_pct ?? '-' }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="!isFinancialMode" prop="valuation_status" label="估值判断" :width="90">
                                        <template #default="{ row }">
                                            <el-tag v-if="row.valuation_status === 'under'" round effect="light" type="danger" size="small">低估</el-tag>
                                            <el-tag v-else-if="row.valuation_status === 'over'" round effect="light" type="success" size="small">高估</el-tag>
                                            <el-tag v-else-if="row.valuation_status === 'fair'" round effect="light" type="info" size="small">正常</el-tag>
                                            <span v-else>-</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="!isFinancialMode" prop="buy_candidate" label="候选" :width="88">
                                        <template #default="{ row }">
                                            <el-tag v-if="row.buy_candidate" round effect="light" type="danger" size="small">可买</el-tag>
                                            <el-tag v-else round effect="light" type="info" size="small">观察</el-tag>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="!isFinancialMode" prop="valuation_score" label="估值分数" :width="88">
                                        <template #default="{ row }">
                                            <span :style="{ color: getUndervalueScoreColor(row.valuation_score ?? row.undervalue_score) }">{{ formatScore(row.valuation_score ?? row.undervalue_score) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="!isPredictiveMode" prop="valuation_risk_level" label="风险级别" :width="92">
                                        <template #default="{ row }">
                                            <el-tag v-if="traditionalRiskTagType(row.valuation_risk_level)" round effect="light" :type="traditionalRiskTagType(row.valuation_risk_level)" size="small">{{ riskLabel(row.valuation_risk_level) }}</el-tag>
                                            <span v-else>-</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="showFinancialColumns" prop="financial_netprofit_yoy" label="净利YoY(%)" :width="95">
                                        <template #default="{ row }">
                                            <span>{{ formatPercent(row.financial_netprofit_yoy) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="showFinancialColumns" prop="financial_ebit_yoy" label="EBITYoY(%)" :width="95">
                                        <template #default="{ row }">
                                            <span>{{ formatPercent(row.financial_ebit_yoy) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="showFinancialColumns" prop="financial_prev_netprofit" label="上一年净利" :width="95">
                                        <template #default="{ row }">
                                            <el-tag v-if="Number.isFinite(Number(row.financial_prev_netprofit))" :type="Number(row.financial_prev_netprofit) >= 0 ? 'success' : 'danger'" size="small" effect="light">
                                                {{ Number(row.financial_prev_netprofit) >= 0 ? '>=0' : '<0' }}
                                            </el-tag>
                                            <span v-else>-</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="showFinancialColumns" prop="financial_prev_ebit" label="上一年EBIT" :width="95">
                                        <template #default="{ row }">
                                            <el-tag v-if="Number.isFinite(Number(row.financial_prev_ebit))" :type="Number(row.financial_prev_ebit) >= 0 ? 'success' : 'danger'" size="small" effect="light">
                                                {{ Number(row.financial_prev_ebit) >= 0 ? '>=0' : '<0' }}
                                            </el-tag>
                                            <span v-else>-</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="isPredictiveMode" prop="earnings_report_type" label="报告口径" :width="90">
                                        <template #default="{ row }">
                                            <el-tag round effect="light" type="primary" size="small">{{ row.earnings_report_type || '-' }}</el-tag>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="isPredictiveMode" prop="signal_score" label="信号分" :width="88">
                                        <template #default="{ row }">
                                            <span :style="{ color: getSignalScoreColor(row.signal_score) }">{{ formatScore(row.signal_score) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="isPredictiveMode" prop="action" label="操作建议" :width="90">
                                        <template #default="{ row }">
                                            <el-tag v-if="actionTagType(row.action)" round effect="light" :type="actionTagType(row.action)" size="small">{{ actionLabel(row.action) }}</el-tag>
                                            <span v-else>-</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="isPredictiveMode" prop="risk_level" label="风险级别" :width="92">
                                        <template #default="{ row }">
                                            <el-tag v-if="riskTagType(row.risk_level)" round effect="light" :type="riskTagType(row.risk_level)" size="small">{{ riskLabel(row.risk_level) }}</el-tag>
                                            <span v-else>-</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="isPredictiveMode" prop="target_price" label="目标价" :width="88">
                                        <template #default="{ row }">
                                            <span>{{ formatPrice(row.target_price) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="isPredictiveMode" prop="target_return_pct" label="目标收益率(%)" :width="110">
                                        <template #default="{ row }">
                                            <span :style="{ color: (row.target_return_pct || 0) >= 0 ? 'red' : 'green' }">{{ formatPercent(row.target_return_pct) }}</span>
                                        </template>
                                    </el-table-column>
                            </el-table>
                            </div>
                        </el-col>
                    </el-row>
                    <el-row :gutter="12" style="margin-top: 10px;">
                        <el-col :span="controlSpan">
                            <div ref="tableControlRef" class="result-table-controls">
                            <el-button type="primary" @click="fetchPrevPage" size="small" :disabled="isJobLoading">上一页</el-button>
                            <el-button type="primary" @click="fetchNextPage" size="small" :disabled="isJobLoading || !hasNextPage">下一页</el-button>
                            <el-button type="success" plain @click="exportPickingResultCsv" size="small" :loading="isExportingAllCsv" :disabled="isExportingAllCsv || totalFiltered === 0">导出CSV</el-button>
                            <el-button type="warning" plain @click="sortByUndervalue('desc')" size="small">低估分降序</el-button>
                            <el-button type="warning" plain @click="sortByUndervalue('asc')" size="small">低估分升序</el-button>
                            <span style="margin-left: 10px; color: #606266; font-size: 12px;">
                                命中总数: {{ totalFiltered }} | 当前范围: {{ currentRangeStart }}-{{ currentRangeEnd }}
                            </span>
                            </div>
                        </el-col>
                    </el-row>
            </el-card>
        </el-col>
    </el-row>

    <el-dialog
        v-model="detailDialogVisible"
        width="80%"
        top="5vh"
        destroy-on-close
    >
        <template #header>
            <div class="stock-title-actions">
                <div class="stock-title-left">
                    <el-text type="primary" tag="b">
                        <el-link
                            class="stock-name-link"
                            :href="resolveCompanyWebsiteUrl(selectedDetailRow?.website_url, selectedDetailRow?.website) || undefined"
                            target="_blank"
                            underline="never"
                        >{{ detailDialogTitle }}</el-link>
                    </el-text>
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
                        :checked="isObserved"
                        @change="toggleObserveStatus"
                        class="compact-toggle-tag compact-toggle-observe"
                    >
                        <span class="compact-toggle-label compact-observe-label">关注</span>
                    </el-check-tag>
                </div>
            </div>
        </template>
        <div style="margin-bottom: 10px; display: flex; align-items: center; gap: 8px;">
            <el-button size="small" @click="switchDetailStock(-1)" :disabled="!hasPrevStock">前一只</el-button>
            <el-button size="small" @click="switchDetailStock(1)" :disabled="!hasNextStock">后一只</el-button>
            <span style="color: #909399; font-size: 12px;">{{ detailPositionText }}</span>
        </div>
        <el-tabs v-model="overviewTab" class="overview-tabs">
            <el-tab-pane label="估值一览" name="valuation">
                <StockValuationQuickView :key="detailQuickViewKey" :embedded="true" />
            </el-tab-pane>
            <el-tab-pane label="技术趋势" name="trend" lazy>
                <div class="trend-tab-panel">
                    <StockChart ref="trendChartCompRef" :display-embed="true" :show-bottom-in-embed="true" />
                </div>
            </el-tab-pane>
            <el-tab-pane label="成本 / 财报" name="finance" lazy>
                <div class="finance-tab-panel">
                    <FinanceRelevant />
                </div>
            </el-tab-pane>
        </el-tabs>
        <template #footer>
            <div style="display: flex; justify-content: space-between; width: 100%;">
                <div>
                    <el-button @click="switchDetailStock(-1)" :disabled="!hasPrevStock">前一只</el-button>
                    <el-button @click="switchDetailStock(1)" :disabled="!hasNextStock">后一只</el-button>
                </div>
                <el-button type="primary" @click="detailDialogVisible = false">关闭</el-button>
            </div>
        </template>
    </el-dialog>
</template>

<script setup lang="ts">
import { ElCard, ElTable, ElTableColumn, ElMessage, ElRow, ElCol, ElButton, ElTag, ElTabs, ElTabPane, ElDialog, ElCheckTag, ElText, ElProgress } from "element-plus";
import { computed, ref, watch, onMounted, nextTick, onBeforeUnmount } from "vue";
import axios from "axios";
import { inject } from "vue";
import { useValuationStockPickingStore } from "../stores/valuationStockPickingStore";
import { useStockTradeStore } from "../stores/stockTradeStore";
import { useStockChartFilterStore } from "../stores/stockChartFilterStore";
import StockChart from "../components/StockChart.vue";
import StockValuationQuickView from "./StockValuationQuickView.vue";
import FinanceRelevant from "./FinanceRelevant.vue";
import RecentReportBadge from "./RecentReportBadge.vue";
import { resolveCompanyWebsiteUrl } from "../utils/companyWebsite";

const valuationStockPickingStore = useValuationStockPickingStore();
const stockTradeStore = useStockTradeStore();
const stockChartFilterStore = useStockChartFilterStore();

const controlSpan = ref(10);
const detailDialogVisible = ref(false);
const detailRowIndex = ref(-1);
const isHolding = ref(false);
const isInWatchlist = ref(false);
const isObserved = ref(false);
const QUICK_PREVIEW_SCAN_LIMIT = "500";

const fromIndex = ref(0);
const toIndex = ref(25);
const increment = ref(25);
const curFromIndex = ref(0);
const curToIndex = ref(25);
const totalFiltered = ref(0);
const currentRangeStart = ref(0);
const currentRangeEnd = ref(0);
const effectiveFinancialFilters = ref<Record<string, any>>({});
const overviewTab = ref("valuation");
const trendChartCompRef = ref<InstanceType<typeof StockChart> | null>(null);
const tableWrapperRef = ref<HTMLElement | null>(null);
const tableControlRef = ref<HTMLElement | null>(null);
const tableHeight = ref(460);
const isExportingAllCsv = ref(false);
const isJobLoading = ref(false);
const isFinancialLoading = ref(false);
const jobStatusText = ref("");
const financialStatusText = ref("");
const jobMessage = ref("");
const financialMessage = ref("");
const jobProgressPct = ref(0);
const financialProgressPct = ref(0);
const jobMatchedCount = ref(0);
const jobTotalCandidates = ref(0);
const activeJobId = ref("");
let jobPollTimer: number | null = null;

const baseURL = inject<string>("baseURL", "");
const pickingResult = ref<Array<Record<string, any>>>([]);
const isPredictiveMode = computed(() => valuationStockPickingStore.pickingMode === "MODE:PREDICTIVE");
const isFinancialMode = computed(() => valuationStockPickingStore.pickingMode === "MODE:FINANCIAL");
const isResultLoading = computed(() => isJobLoading.value || isFinancialLoading.value);
const resultStatusText = computed(() => isFinancialMode.value ? financialStatusText.value : jobStatusText.value);
const resultMessage = computed(() => isFinancialMode.value ? financialMessage.value : jobMessage.value);

const hasPrevStock = computed(() => detailRowIndex.value > 0);
const hasNextStock = computed(() => detailRowIndex.value >= 0 && detailRowIndex.value < pickingResult.value.length - 1);
const hasNextPage = computed(() => {
    const total = Number(totalFiltered.value || 0);
    if (total <= 0) {
        return false;
    }
    return Number(curToIndex.value || 0) < total;
});
const detailPositionText = computed(() => {
    if (detailRowIndex.value < 0 || pickingResult.value.length === 0) {
        return "";
    }
    return `${detailRowIndex.value + 1} / ${pickingResult.value.length}`;
});
const detailDialogTitle = computed(() => {
    if (detailRowIndex.value < 0 || detailRowIndex.value >= pickingResult.value.length) {
        return "个股详情";
    }
    const row = pickingResult.value[detailRowIndex.value] || {};
    return `${row.name || ""} | ${row.ts_code || ""}`.trim() || "个股详情";
});
const selectedDetailRow = computed(() => {
    if (detailRowIndex.value < 0 || detailRowIndex.value >= pickingResult.value.length) {
        return null;
    }
    return pickingResult.value[detailRowIndex.value] || null;
});
const detailQuickViewKey = computed(() => {
    if (detailRowIndex.value < 0 || detailRowIndex.value >= pickingResult.value.length) {
        return "detail-quick-view-empty";
    }
    const row = pickingResult.value[detailRowIndex.value] || {};
    return `detail-quick-view-${String(row.ts_code || "").trim().toUpperCase()}`;
});
const showFinancialStageHint = computed(() => {
    if (isPredictiveMode.value) {
        return false;
    }
    const filters = effectiveFinancialFilters.value || {};
    const applyFinancialFilters = Boolean(filters.apply_financial_filters);
    if (!applyFinancialFilters) {
        return false;
    }
    const hasNumericThreshold = (value: any) => {
        if (value === null || value === undefined || String(value).trim() === "") {
            return false;
        }
        const numeric = Number(value);
        return Number.isFinite(numeric);
    };
    const requirePrevNetprofit = Boolean(filters.require_positive_prev_netprofit);
    const requirePrevEbit = Boolean(filters.require_positive_prev_ebit);
    return hasNumericThreshold(filters.min_netprofit_yoy)
        || hasNumericThreshold(filters.min_ebit_yoy)
        || requirePrevNetprofit
        || requirePrevEbit;
});

const showFinancialColumns = computed(() => {
    const filters = effectiveFinancialFilters.value || {};
    if (Object.prototype.hasOwnProperty.call(filters, "apply_financial_filters")) {
        return Boolean(filters.apply_financial_filters);
    }
    return Boolean(valuationStockPickingStore.applyFinancialFilters);
});

function resolvePreferredValuationVariant(row: any) {
    const directVariant = String(row?.valuation_variant || "").trim();
    if (directVariant) {
        return directVariant;
    }
    const metaVariant = String(row?.result_meta?.valuation_variant || "").trim();
    if (metaVariant) {
        return metaVariant;
    }
    return "";
}

function buildApiUrl(path: string) {
    const base = String(baseURL || "").replace(/\/+$/, "");
    const normalizedPath = path.startsWith("/") ? path : `/${path}`;
    if (base.endsWith("/api") && normalizedPath.startsWith("/api/")) {
        return `${base}${normalizedPath.slice(4)}`;
    }
    return `${base}${normalizedPath}`;
}

function normalizeScopeForApi(scopeRaw: string): string {
    return String(scopeRaw || "")
        .split(",")
        .map((item) => item.trim())
        .filter((item) => !!item)
        .map((item) => {
            if (item === "0") return "00";
            if (item === "3") return "30";
            if (item === "688") return "68";
            return item;
        })
        .join(",");
}

function updateTableHeight() {
    const wrapper = tableWrapperRef.value;
    if (!wrapper) {
        return;
    }
    const controls = tableControlRef.value;
    const rect = wrapper.getBoundingClientRect();
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
    const controlsHeight = controls?.getBoundingClientRect().height || 0;
    const reservedBottomSpace = controlsHeight + 56;
    const nextHeight = Math.max(260, Math.floor(viewportHeight - rect.top - reservedBottomSpace));
    tableHeight.value = nextHeight;
}

function toCsvCell(value: unknown) {
    const text = String(value ?? "");
    const escaped = text.replace(/"/g, '""');
    return `"${escaped}"`;
}

function buildPickingSearchParams(from: number, to: number) {
    const valuationMethodVal = valuationStockPickingStore.valuationMethod.split(":")[1].toLowerCase();
    const valuationStatusVal = valuationStockPickingStore.valuationStatus.split(":")[1] !== "NONE" ? valuationStockPickingStore.valuationStatus.split(":")[1].toLowerCase() : "";
    const buyCandidateOnlyVal = valuationStockPickingStore.buyCandidateOnly.split(":")[1] === "ONLY" ? "1" : "";
    const valuationPickStrategyVal = valuationStockPickingStore.valuationPickStrategy.split(":")[1].toLowerCase();
    const minNetprofitYoyVal = String(valuationStockPickingStore.minNetprofitYoy || "").trim();
    const minEbitYoyVal = String(valuationStockPickingStore.minEbitYoy || "").trim();
    const requirePositivePrevNetprofitVal = valuationStockPickingStore.requirePositivePrevNetprofit ? "1" : "0";
    const requirePositivePrevEbitVal = valuationStockPickingStore.requirePositivePrevEbit ? "1" : "0";
    const applyFinancialFiltersVal = valuationStockPickingStore.applyFinancialFilters ? "1" : "0";
    const applyMoneyflowFiltersVal = valuationStockPickingStore.applyMoneyflowFilters ? "1" : "0";
    const moneyflowWindowVal = String(valuationStockPickingStore.moneyflowNetInflowDaysWindow || "10").trim();
    const priorityPolicyVal = String(valuationStockPickingStore.priorityPolicy || "score_desc").trim().toLowerCase();
    const pickingModeVal = valuationStockPickingStore.pickingMode.split(":")[1].toLowerCase();
    const earningsReportTypeVal = valuationStockPickingStore.earningsReportType.split(":")[1];
    const signalActionVal = valuationStockPickingStore.signalAction.split(":")[1];
    const riskLevelParam = String(valuationStockPickingStore.riskLevel || "")
        .split(",")
        .map((item) => item.trim().toUpperCase())
        .filter((item) => item === "LOW" || item === "MEDIUM" || item === "HIGH")
        .join(",");
    const featureDataSourceVal = valuationStockPickingStore.featureDataSource.split(":")[1];
    const sharedMinScoreVal = String(valuationStockPickingStore.minSignalScore || "").trim();
    const fiscalYearVal = String(valuationStockPickingStore.fiscalYear || "").trim();

    const search = new URLSearchParams();
    search.set("freq", valuationStockPickingStore.freq);
    if (/^\d{4}$/.test(fiscalYearVal)) search.set("valuation_fiscal_year", fiscalYearVal);
    search.set("from_index", String(from));
    search.set("to_index", String(to));
    search.set("quick_preview", "1");
    search.set("preview_scan_limit", QUICK_PREVIEW_SCAN_LIMIT);
    search.set("picking_mode", pickingModeVal);
    search.set("valuation_method", valuationMethodVal);
    if (valuationStatusVal) search.set("valuation_status", valuationStatusVal);
    search.set("valuation_band_pct", valuationStockPickingStore.valuationBandPct);
    search.set("valuation_pick_strategy", valuationPickStrategyVal);
    if (minNetprofitYoyVal) search.set("min_netprofit_yoy", minNetprofitYoyVal);
    if (minEbitYoyVal) search.set("min_ebit_yoy", minEbitYoyVal);
    search.set("apply_financial_filters", applyFinancialFiltersVal);
    search.set("apply_moneyflow_filters", applyMoneyflowFiltersVal);
    if (["5", "10", "15", "30", "60"].includes(moneyflowWindowVal)) {
        search.set("moneyflow_net_inflow_days_window", moneyflowWindowVal);
    }
    search.set("require_positive_prev_netprofit", requirePositivePrevNetprofitVal);
    search.set("require_positive_prev_ebit", requirePositivePrevEbitVal);
    if (priorityPolicyVal) search.set("priority_policy", priorityPolicyVal);
    if (buyCandidateOnlyVal) search.set("buy_candidate_only", buyCandidateOnlyVal);
    if (valuationStockPickingStore.swIndustry) search.set("sw_industry", valuationStockPickingStore.swIndustry);
    search.set("earnings_report_type", earningsReportTypeVal);
    if (riskLevelParam) search.set("risk_level", riskLevelParam);
    if (pickingModeVal === "predictive") {
        if (signalActionVal !== "ALL") search.set("signal_action", signalActionVal);
        if (sharedMinScoreVal) search.set("min_signal_score", sharedMinScoreVal);
        if (valuationStockPickingStore.minTargetReturnPct) search.set("min_target_return_pct", valuationStockPickingStore.minTargetReturnPct);
        if (featureDataSourceVal !== "ALL") search.set("feature_data_source", featureDataSourceVal);
    } else {
        if (sharedMinScoreVal) search.set("min_valuation_score", sharedMinScoreVal);
    }
    return search;
}

function buildPickingRequestUrl(from: number, to: number) {
    const scopePath = normalizeScopeForApi(valuationStockPickingStore.scopeParam);
    const search = buildPickingSearchParams(from, to);
    return `${buildApiUrl(`/stock-pick-valuation/${valuationStockPickingStore.tradeDate}/${scopePath}/`)}?${search.toString()}`;
}

function stopPickingJobPolling() {
    if (jobPollTimer !== null) {
        window.clearTimeout(jobPollTimer);
        jobPollTimer = null;
    }
}

function buildPickingJobPayload() {
    const search = buildPickingSearchParams(0, 25);
    const query: Record<string, string> = {};
    search.forEach((value, key) => {
        query[key] = value;
    });
    return {
        trade_date: valuationStockPickingStore.tradeDate,
        scope: normalizeScopeForApi(valuationStockPickingStore.scopeParam),
        query,
    };
}

function applyPickingJobState(payload: any) {
    const rows = Array.isArray(payload?.data) ? payload.data : [];
    const meta = payload?.meta || {};
    const valuationFilter = payload?.valuation_filter || {};
    pickingResult.value = rows;
    effectiveFinancialFilters.value = valuationFilter.effective_financial_filters || {};
    totalFiltered.value = Number(payload?.matched_count ?? meta.total_filtered ?? 0);
    jobMatchedCount.value = totalFiltered.value;
    jobTotalCandidates.value = Number(payload?.total_candidates ?? meta.total_candidates ?? 0);
    if (rows.length > 0) {
        currentRangeStart.value = 1;
        currentRangeEnd.value = rows.length;
        curFromIndex.value = 0;
        curToIndex.value = rows.length;
        fromIndex.value = rows.length;
        toIndex.value = rows.length + increment.value;
    } else {
        currentRangeStart.value = 0;
        currentRangeEnd.value = 0;
        curFromIndex.value = 0;
        curToIndex.value = 25;
        fromIndex.value = 0;
        toIndex.value = 25;
    }
    valuationStockPickingStore.setPickingResults(
        rows.map((item: any) => ({
            ts_code: item.ts_code,
            name: item.name,
            close_qfq: item.close_qfq,
            pct_change_qfq: item.pct_change_qfq,
        }))
    );
    if (payload?.status === "done") {
        valuationStockPickingStore.markResultDate(
            valuationStockPickingStore.tradeDate,
            totalFiltered.value > 0,
        );
    }
    nextTick(() => updateTableHeight());
}

async function pollPickingJob(jobId: string) {
    try {
        const res = await axios.get(buildApiUrl(`/stock-pick-valuation/jobs/${jobId}/`));
        const payload = res.data || {};
        if (activeJobId.value !== jobId) {
            return;
        }
        jobProgressPct.value = Number(payload.progress_pct || 0);
        jobMessage.value = String(payload.message || "");
        const status = String(payload.status || "");
        jobStatusText.value = status === "queued"
            ? "排队中"
            : status === "running"
                ? "计算中"
                : status === "done"
                    ? "已完成"
                    : status === "canceled"
                        ? "已取消"
                    : status === "failed"
                        ? "失败"
                        : "处理中";
        applyPickingJobState(payload);
        if (status === "done") {
            isJobLoading.value = false;
            stopPickingJobPolling();
            return;
        }
        if (status === "canceled") {
            isJobLoading.value = false;
            stopPickingJobPolling();
            return;
        }
        if (status === "failed") {
            isJobLoading.value = false;
            stopPickingJobPolling();
            ElMessage.error(jobMessage.value || "选股任务失败，请稍后重试");
            return;
        }
        const pollIntervalSeconds = Math.max(2, Number(payload.poll_interval_seconds || 3));
        jobPollTimer = window.setTimeout(() => {
            void pollPickingJob(jobId);
        }, pollIntervalSeconds * 1000);
    } catch (_error) {
        if (activeJobId.value === jobId) {
            isJobLoading.value = false;
            stopPickingJobPolling();
            ElMessage.error("获取选股任务进度失败，请稍后重试");
        }
    }
}

async function startPickingJob() {
    try {
        stopPickingJobPolling();
        activeJobId.value = "";
        jobStatusText.value = "提交中";
        jobMessage.value = "正在创建选股任务";
        jobProgressPct.value = 0;
        jobMatchedCount.value = 0;
        jobTotalCandidates.value = 0;
        if (valuationStockPickingStore.scopeParam === "SCOPE:NONE") {
            isJobLoading.value = false;
            pickingResult.value = [];
            totalFiltered.value = 0;
            valuationStockPickingStore.setPickingResults([]);
            return;
        }
        isJobLoading.value = true;
        pickingResult.value = [];
        totalFiltered.value = 0;
        effectiveFinancialFilters.value = {};
        const res = await axios.post(buildApiUrl("/stock-pick-valuation/jobs/"), buildPickingJobPayload());
        const payload = res.data || {};
        const jobId = String(payload.job_id || "").trim();
        if (!jobId) {
            throw new Error("missing job_id");
        }
        activeJobId.value = jobId;
        jobProgressPct.value = Number(payload.progress_pct || 0);
        jobMessage.value = String(payload.message || "");
        jobStatusText.value = String(payload.status || "queued") === "queued" ? "排队中" : "计算中";
        await pollPickingJob(jobId);
    } catch (_error) {
        isJobLoading.value = false;
        stopPickingJobPolling();
        ElMessage.error("提交选股任务失败，请稍后重试");
    }
}

async function exportPickingResultCsv() {
    if (isExportingAllCsv.value) {
        return;
    }
    if (valuationStockPickingStore.scopeParam === "SCOPE:NONE") {
        ElMessage.warning("暂无可导出的选股结果");
        return;
    }

    isExportingAllCsv.value = true;
    const exportRows: Array<Record<string, any>> = [];

    try {
        const chunkSize = 500;
        let cursor = 0;
        let expectedTotal = Math.max(0, Number(totalFiltered.value || 0));

        while (true) {
            const url = buildPickingRequestUrl(cursor, cursor + chunkSize);
            const res = await axios.get(url);
            const rows = Array.isArray(res.data?.data) ? res.data.data : [];
            exportRows.push(...rows);

            const responseTotal = Number(res.data?.meta?.total_filtered || 0);
            if (responseTotal > 0) {
                expectedTotal = responseTotal;
            }

            if (!rows.length) {
                break;
            }
            cursor += rows.length;
            if (rows.length < chunkSize) {
                break;
            }
            if (expectedTotal > 0 && cursor >= expectedTotal) {
                break;
            }
        }
    } catch (_error) {
        ElMessage.error("导出失败：全量结果拉取异常，请稍后重试");
        isExportingAllCsv.value = false;
        return;
    }

    if (!exportRows.length) {
        ElMessage.warning("暂无可导出的选股结果");
        isExportingAllCsv.value = false;
        return;
    }
    const headers = [
        "名称",
        "代码",
        "最高涨幅(%)",
        "最低涨幅(%)",
        "当前涨幅(%)",
        "SW行业",
        "估值法",
        "当前价格",
        "估值价",
        "快照更新时间",
        "财报发布日",
        "估值判断",
        "估值分数",
    ];

    const lines = [headers.map((cell) => toCsvCell(cell)).join(",")];
    for (const row of exportRows) {
        const line = [
            row.name || "",
            row.ts_code || "",
            formatPercent(row.signal_peak_return_pct),
            formatPercent(row.signal_trough_return_pct),
            formatPercent(row.signal_current_return_pct),
            row.sw_l3_name || row.industry_name || "",
            methodLabel(row.valuation_method),
            formatPrice(row.close_qfq),
            formatPrice(row.valuation_price),
            formatDateTime(row.valuation_snapshot_updated_at),
            formatDateOnly(row.valuation_profit_report_ann_date || row.financial_ann_date),
            row.valuation_status || "",
            formatScore(row.valuation_score ?? row.undervalue_score),
        ];
        lines.push(line.map((cell) => toCsvCell(cell)).join(","));
    }

    const csvContent = "\uFEFF" + lines.join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const fileDate = formatDateOnly(valuationStockPickingStore.tradeDate || new Date());
    const fileMode = isPredictiveMode.value ? "predictive" : "traditional";
    const fileName = `stock_picking_${fileMode}_${fileDate}.csv`;

    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    ElMessage.success(`CSV导出成功，共 ${exportRows.length} 条`);
    isExportingAllCsv.value = false;
}

function syncDetailStock(row: any) {
    stockTradeStore.setTsCode(row.ts_code);
    stockTradeStore.setName(row.name);
    stockTradeStore.setWebsite(resolveCompanyWebsiteUrl(row.website_url, row.website));
    stockTradeStore.setPreferredValuationVariant(resolvePreferredValuationVariant(row));
    stockTradeStore.setPreferredPredictiveReportType("");
    stockTradeStore.setPreferredPredictiveFinancialEndDate("");
}

function clearDetailStockStatus() {
    isHolding.value = false;
    isInWatchlist.value = false;
    isObserved.value = false;
}

function toCanonicalTsCode(code: string) {
    const normalized = String(code || "").trim().toUpperCase();
    if (!normalized) return "";
    if (normalized.includes(".")) return normalized;
    if (!/^\d{6}$/.test(normalized)) return normalized;
    if (normalized.startsWith("6") || normalized.startsWith("5") || normalized.startsWith("9")) return `${normalized}.SH`;
    if (normalized.startsWith("8") || normalized.startsWith("4")) return `${normalized}.BJ`;
    return `${normalized}.SZ`;
}

function buildTsCodeCandidates(code: string) {
    const normalized = String(code || "").trim().toUpperCase();
    const base = normalized.split(".")[0];
    if (normalized.includes(".")) {
        return normalized ? [normalized] : [];
    }
    const candidateSet = new Set<string>();
    if (normalized) candidateSet.add(normalized);
    if (base) candidateSet.add(base);
    const canonical = toCanonicalTsCode(normalized);
    if (canonical) candidateSet.add(canonical);
    // Keep candidate space tight to avoid unnecessary cross-market probe calls.
    return Array.from(candidateSet);
}

async function fetchDetailStockStatus(tsCode: string) {
    clearDetailStockStatus();
    if (!baseURL || !tsCode) {
        return;
    }
    try {
        const candidates = buildTsCodeCandidates(tsCode);
        let fallbackData: any = null;
        for (const candidate of candidates) {
            const res = await axios.get(`${baseURL}/watchlist/check/${candidate}/`);
            if (!res.data) {
                continue;
            }
            if (!fallbackData) {
                fallbackData = res.data;
            }
            if (res.data.hold_position || res.data.in_watchlist || res.data.observe_status) {
                isHolding.value = !!res.data.hold_position;
                isInWatchlist.value = !!res.data.in_watchlist;
                isObserved.value = !!res.data.observe_status;
                return;
            }
        }
        if (fallbackData) {
            isHolding.value = !!fallbackData.hold_position;
            isInWatchlist.value = !!fallbackData.in_watchlist;
            isObserved.value = !!fallbackData.observe_status;
        }
    } catch (_error) {
        clearDetailStockStatus();
    }
}

async function toggleWatchlistStatus(watchlist: boolean) {
    try {
        const tsCode = String(stockTradeStore.tsCode || "").trim();
        if (!baseURL || !tsCode) {
            return;
        }
        const res = watchlist
            ? await axios.post(`${baseURL}/watchlist/add/${tsCode}/`)
            : await axios.put(`${baseURL}/watchlist/delete/${tsCode}/`);
        if (res.status === 200) {
            isInWatchlist.value = !!res.data.in_watchlist;
            isHolding.value = !!res.data.hold_position;
            isObserved.value = !!res.data.observe_status;
            ElMessage.success(isInWatchlist.value ? '已加入自选股' : '已移除自选股');
        }
    } catch (error) {
        console.error('Failed to toggle watchlist status:', error);
        ElMessage.error('操作失败，请稍后重试');
    }
}

async function toggleHoldingStatus(hold: boolean) {
    try {
        const tsCode = String(stockTradeStore.tsCode || "").trim();
        if (!baseURL || !tsCode) {
            return;
        }
        const res = await axios({
            url: hold ? `${baseURL}/watchlist/hold/${tsCode}/` : `${baseURL}/watchlist/unhold/${tsCode}/`,
            method: hold ? 'post' : 'put',
        });
        if (res.status === 200) {
            isHolding.value = !!res.data.hold_position;
            isInWatchlist.value = !!res.data.in_watchlist;
            isObserved.value = !!res.data.observe_status;
            ElMessage.success(isHolding.value ? '已标记为持仓' : '已取消持仓标记');
        }
    } catch (error) {
        console.error('Failed to toggle holding status:', error);
        ElMessage.error('操作失败，请稍后重试');
    }
}

async function toggleObserveStatus(observe: boolean) {
    try {
        const tsCode = String(stockTradeStore.tsCode || "").trim();
        if (!baseURL || !tsCode) {
            return;
        }
        const res = await axios({
            url: observe ? `${baseURL}/watchlist/observe/${tsCode}/` : `${baseURL}/watchlist/unobserve/${tsCode}/`,
            method: observe ? 'post' : 'put',
        });
        if (res.status === 200) {
            isObserved.value = !!res.data.observe_status;
            isHolding.value = !!res.data.hold_position;
            isInWatchlist.value = !!res.data.in_watchlist;
            ElMessage.success(isObserved.value ? '已标记为关注' : '已取消关注');
        }
    } catch (error) {
        console.error('Failed to toggle observe status:', error);
        ElMessage.error('操作失败，请稍后重试');
    }
}

async function openDetailAt(index: number) {
    if (index < 0 || index >= pickingResult.value.length) {
        return;
    }
    detailRowIndex.value = index;
    syncDetailStock(pickingResult.value[index]);
    await fetchDetailStockStatus(String(pickingResult.value[index]?.ts_code || ""));
    detailDialogVisible.value = true;
}

const onRowDblClick = (row: any) => {
    const idx = pickingResult.value.indexOf(row);
    if (idx >= 0) {
        openDetailAt(idx);
        return;
    }
    const code = String(row?.ts_code || "").trim().toUpperCase();
    const fallbackIdx = pickingResult.value.findIndex((item) => String(item?.ts_code || "").trim().toUpperCase() === code);
    openDetailAt(fallbackIdx);
};

function switchDetailStock(offset: number) {
    if (detailRowIndex.value < 0) {
        return;
    }
    const nextIndex = detailRowIndex.value + offset;
    if (nextIndex < 0 || nextIndex >= pickingResult.value.length) {
        return;
    }
    void openDetailAt(nextIndex);
}

watch(
    () => overviewTab.value,
    (tab) => {
        if (tab !== "trend") {
            return;
        }
        nextTick(() => {
            trendChartCompRef.value?.refreshTrendLayout?.();
        });
    }
);

const onStockClick = (row: any) => {
    syncDetailStock(row);
};

function formatPrice(value: any) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "-";
    return numeric.toFixed(2);
}

function formatPercent(value: any) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "-";
    return numeric.toFixed(2);
}

function formatPercentWithSymbol(value: any) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "-";
    return `${numeric.toFixed(2)}%`;
}

function formatScore(value: any) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "-";
    return numeric.toFixed(0);
}

function formatDateTime(value: any) {
    const text = String(value || "").trim();
    if (!text) return "-";
    const parsed = new Date(text);
    if (Number.isNaN(parsed.getTime())) {
        return text;
    }
    const yyyy = parsed.getFullYear();
    const mm = String(parsed.getMonth() + 1).padStart(2, "0");
    const dd = String(parsed.getDate()).padStart(2, "0");
    const hh = String(parsed.getHours()).padStart(2, "0");
    const mi = String(parsed.getMinutes()).padStart(2, "0");
    const ss = String(parsed.getSeconds()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${hh}:${mi}:${ss}`;
}

function formatDateOnly(value: any) {
    const text = String(value || "").trim();
    if (!text) return "-";
    const parsed = new Date(text);
    if (Number.isNaN(parsed.getTime())) {
        return text.length >= 10 ? text.slice(0, 10) : text;
    }
    const yyyy = parsed.getFullYear();
    const mm = String(parsed.getMonth() + 1).padStart(2, "0");
    const dd = String(parsed.getDate()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd}`;
}

function resolveUndervalueScore(row: Record<string, any>) {
    const directValuationScore = Number(row?.valuation_score);
    if (Number.isFinite(directValuationScore)) {
        return directValuationScore;
    }
    const directUnderScore = Number(row?.undervalue_score);
    if (Number.isFinite(directUnderScore)) {
        return directUnderScore;
    }
    return null;
}

function sortByUndervalue(order: "asc" | "desc") {
    const direction = order === "asc" ? 1 : -1;
    pickingResult.value = [...pickingResult.value].sort((a, b) => {
        const scoreA = resolveUndervalueScore(a);
        const scoreB = resolveUndervalueScore(b);
        if (scoreA === null && scoreB === null) return String(a?.ts_code || "").localeCompare(String(b?.ts_code || ""));
        if (scoreA === null) return 1;
        if (scoreB === null) return -1;
        if (scoreA === scoreB) return String(a?.ts_code || "").localeCompare(String(b?.ts_code || ""));
        return (scoreA - scoreB) * direction;
    });
}

const valuationMethodLabelMap: Record<string, string> = {
    recommended: "行业推荐",
    market_style: "市场风格",
    scarcity_overlay: "稀缺性",
    pe: "PE",
    pb: "PB",
    ps: "PS",
    peg: "PEG",
    fcff_dcf: "FCFF",
    ddm: "DDM",
    market_cap: "市值法",
};

function methodLabel(method: any) {
    const key = String(method || "").trim().toLowerCase();
    return valuationMethodLabelMap[key] || String(method || "-");
}

function getUndervalueScoreColor(value: any) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "#909399";
    if (numeric >= 75) return "#cf1322";
    if (numeric >= 55) return "#d46b08";
    return "#606266";
}

function getSignalScoreColor(value: any) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "#909399";
    if (numeric >= 70) return "#cf1322";
    if (numeric >= 55) return "#d46b08";
    return "#606266";
}

function normalizeAction(action: any) {
    return String(action || "").trim().toUpperCase();
}

function actionTagType(action: any) {
    const normalized = normalizeAction(action);
    if (normalized === "BUY" || normalized === "B") return "danger";
    if (normalized === "SELL_PART") return "warning";
    if (normalized === "SELL" || normalized === "S") return "success";
    if (normalized === "HOLD" || normalized === "H") return "info";
    return undefined;
}

function actionLabel(action: any) {
    const normalized = normalizeAction(action);
    if (normalized === "BUY" || normalized === "B") return "买";
    if (normalized === "SELL" || normalized === "SELL_PART" || normalized === "S") return "卖";
    if (normalized === "HOLD" || normalized === "H") return "持";
    return "-";
}

function normalizeRisk(risk: any) {
    return String(risk || "").trim().toUpperCase();
}

function riskTagType(risk: any) {
    const normalized = normalizeRisk(risk);
    if (normalized === "LOW" || normalized === "L") return "danger";
    if (normalized === "MEDIUM" || normalized === "M") return "warning";
    if (normalized === "HIGH" || normalized === "H") return "success";
    return undefined;
}

function traditionalRiskTagType(risk: any) {
    const normalized = normalizeRisk(risk);
    if (normalized === "LOW" || normalized === "L") return "success";
    if (normalized === "MEDIUM" || normalized === "M") return "warning";
    if (normalized === "HIGH" || normalized === "H") return "danger";
    return undefined;
}

function riskLabel(risk: any) {
    const normalized = normalizeRisk(risk);
    if (normalized === "LOW" || normalized === "L") return "低";
    if (normalized === "MEDIUM" || normalized === "M") return "中";
    if (normalized === "HIGH" || normalized === "H") return "高";
    return "-";
}

async function fetchPickingResult() {
    try {
        if (valuationStockPickingStore.scopeParam === "SCOPE:NONE") {
            pickingResult.value = [];
            valuationStockPickingStore.setPickingResults([]);
            return;
        }

        const isFirstPageRequest = fromIndex.value === 0;
        if (isFinancialMode.value) {
            isFinancialLoading.value = true;
            financialStatusText.value = "提交中";
            financialMessage.value = "正在创建财务筛选请求";
            financialProgressPct.value = 10;
            jobMatchedCount.value = 0;
            jobTotalCandidates.value = 0;
            await nextTick();
            const search = new URLSearchParams({
                fiscal_year: valuationStockPickingStore.fiscalYear,
                report_type: valuationStockPickingStore.earningsReportType.split(":")[1],
                require_all_metrics: valuationStockPickingStore.requireAllFinancialMetrics ? "1" : "0",
            });
            if (valuationStockPickingStore.swIndustry) search.set("sw_industry", valuationStockPickingStore.swIndustry);
            const thresholdMap: Record<string, string> = {
                min_ebit_yoy_pct: valuationStockPickingStore.minEbitYoy,
                min_ebit_qoq_pct: valuationStockPickingStore.minEbitQoq,
                min_revenue_yoy_pct: valuationStockPickingStore.minRevenueYoy,
                min_revenue_qoq_pct: valuationStockPickingStore.minRevenueQoq,
                min_netprofit_yoy_pct: valuationStockPickingStore.minNetprofitYoy,
                min_netprofit_qoq_pct: valuationStockPickingStore.minNetprofitQoq,
                min_roe_pct: valuationStockPickingStore.minRoe,
                min_roe_dt_pct: valuationStockPickingStore.minRoeDt,
            };
            Object.entries(thresholdMap).forEach(([key, value]) => { if (String(value || "").trim()) search.set(key, value); });
            search.set("sort_by", valuationStockPickingStore.financialSortBy);
            search.set("sort_order", valuationStockPickingStore.financialSortOrder);
            const scopePath = normalizeScopeForApi(valuationStockPickingStore.scopeParam);
            try {
                financialStatusText.value = "计算中";
                financialMessage.value = "正在读取已发布财报并补充传统/预测估值结果";
                financialProgressPct.value = 55;
                const res = await axios.get(`${buildApiUrl(`/stock-pick-financial/${valuationStockPickingStore.tradeDate}/${scopePath}/`)}?${search}`);
                financialStatusText.value = "结果汇总中";
                financialMessage.value = "正在应用排序并整理结果";
                financialProgressPct.value = 90;
                await nextTick();
                pickingResult.value = Array.isArray(res.data?.data) ? res.data.data : [];
                totalFiltered.value = Number(res.data?.total || pickingResult.value.length);
                valuationStockPickingStore.setPickingResults(pickingResult.value as any);
                currentRangeStart.value = pickingResult.value.length ? 1 : 0;
                currentRangeEnd.value = pickingResult.value.length;
                jobMatchedCount.value = totalFiltered.value;
                jobTotalCandidates.value = Number(res.data?.meta?.total_candidates || 0);
                financialStatusText.value = "已完成";
                financialMessage.value = totalFiltered.value ? "结果已按当前条件生成" : "当前条件下没有匹配股票";
                financialProgressPct.value = 100;
                nextTick(() => updateTableHeight());
            } catch (error) {
                financialStatusText.value = "失败";
                financialMessage.value = "请求财务筛选结果失败，请稍后重试";
                ElMessage.error(financialMessage.value);
            } finally {
                isFinancialLoading.value = false;
            }
            return;
        }
        const url = buildPickingRequestUrl(fromIndex.value, toIndex.value);
        const requestFrom = fromIndex.value;
        const requestTo = toIndex.value;
        const res = await axios.get(url);

        if (res.data) {
            pickingResult.value = res.data.data || [];
            const responseMeta = (res.data || {}).meta || {};
            const responseValuationFilter = (res.data || {}).valuation_filter || {};
            effectiveFinancialFilters.value = responseValuationFilter.effective_financial_filters || {};
            totalFiltered.value = Number(responseMeta.total_filtered || 0);
            if (isFirstPageRequest) {
                valuationStockPickingStore.markResultDate(
                    valuationStockPickingStore.tradeDate,
                    totalFiltered.value > 0,
                );
            }
            if (pickingResult.value.length > 0) {
                currentRangeStart.value = requestFrom + 1;
                currentRangeEnd.value = requestFrom + pickingResult.value.length;
            } else {
                currentRangeStart.value = 0;
                currentRangeEnd.value = 0;
            }
            const selectedStrategy = valuationStockPickingStore.valuationPickStrategy.split(":")[1]?.toLowerCase?.() || "baseline";
            if (
                isFirstPageRequest
                && selectedStrategy !== "baseline"
                && Number(responseMeta.strategy_effective_stocks || 0) === 0
            ) {
                ElMessage.info("当前样本里每只股票仅有单候选估值，切换主值策略不会改变估值价格。");
            }
            const noResult = !Array.isArray(res.data.data) || res.data.data.length === 0;
            if (isFirstPageRequest && noResult && responseMeta.requested_trade_date_has_data === false) {
                const latestDate = responseMeta.latest_trade_date_for_freq;
                ElMessage.warning(
                    latestDate
                        ? `当前选择日期 ${valuationStockPickingStore.tradeDate} 无交易数据，最新可用交易日为 ${latestDate}`
                        : `当前选择日期 ${valuationStockPickingStore.tradeDate} 无交易数据，请切换交易日后重试`
                );
            }

            curFromIndex.value = requestFrom;
            curToIndex.value = requestTo;
            fromIndex.value = requestTo;
            toIndex.value = requestTo + increment.value;

            valuationStockPickingStore.setPickingResults(
                (res.data.data || []).map((item: any) => ({
                    ts_code: item.ts_code,
                    name: item.name,
                    close_qfq: item.close_qfq,
                    pct_change_qfq: item.pct_change_qfq,
                }))
            );
            nextTick(() => updateTableHeight());
        }
    } catch (error) {
        ElMessage.error("获取估值选股结果失败，请稍后重试");
    }
}

async function warmupPickingCache() {
    try {
        if (valuationStockPickingStore.scopeParam === "SCOPE:NONE") {
            return;
        }
        const url = buildPickingRequestUrl(0, 1);
        await axios.get(url);
    } catch (_error) {
        // Warmup is best-effort and should not affect user interaction.
    }
}

async function fetchPrevPage() {
    if (isJobLoading.value) {
        ElMessage.info("当前仍在生成结果，请等待任务完成后再翻页");
        return;
    }
    if (curFromIndex.value <= 0) return;
    fromIndex.value = curFromIndex.value - increment.value;
    toIndex.value = curToIndex.value - increment.value;
    await fetchPickingResult();
}

async function fetchNextPage() {
    if (isJobLoading.value) {
        ElMessage.info("当前仍在生成结果，请等待任务完成后再翻页");
        return;
    }
    if (!hasNextPage.value) {
        ElMessage.info("已经是最后一页");
        return;
    }
    await fetchPickingResult();
}

watch(
    [
        () => valuationStockPickingStore.tradeDate,
        () => valuationStockPickingStore.scopeParam,
        () => valuationStockPickingStore.freq,
        () => valuationStockPickingStore.pickingMode,
        () => valuationStockPickingStore.valuationMethod,
        () => valuationStockPickingStore.valuationStatus,
        () => valuationStockPickingStore.valuationBandPct,
        () => valuationStockPickingStore.valuationPickStrategy,
        () => valuationStockPickingStore.minNetprofitYoy,
        () => valuationStockPickingStore.minEbitYoy,
        () => valuationStockPickingStore.minEbitQoq,
        () => valuationStockPickingStore.minRevenueYoy,
        () => valuationStockPickingStore.minRevenueQoq,
        () => valuationStockPickingStore.minNetprofitQoq,
        () => valuationStockPickingStore.minRoe,
        () => valuationStockPickingStore.minRoeDt,
        () => valuationStockPickingStore.requireAllFinancialMetrics,
        () => valuationStockPickingStore.financialSortBy,
        () => valuationStockPickingStore.financialSortOrder,
        () => valuationStockPickingStore.applyFinancialFilters,
        () => valuationStockPickingStore.applyMoneyflowFilters,
        () => valuationStockPickingStore.moneyflowNetInflowDaysWindow,
        () => valuationStockPickingStore.requirePositivePrevNetprofit,
        () => valuationStockPickingStore.requirePositivePrevEbit,
        () => valuationStockPickingStore.priorityPolicy,
        () => valuationStockPickingStore.buyCandidateOnly,
        () => valuationStockPickingStore.swIndustry,
        () => valuationStockPickingStore.earningsReportType,
        () => valuationStockPickingStore.signalAction,
        () => valuationStockPickingStore.riskLevel,
        () => valuationStockPickingStore.minSignalScore,
        () => valuationStockPickingStore.minTargetReturnPct,
        () => valuationStockPickingStore.featureDataSource,
        () => valuationStockPickingStore.fiscalYear,
    ],
    () => {
        fromIndex.value = 0;
        toIndex.value = 25;
        currentRangeStart.value = 0;
        currentRangeEnd.value = 0;
        if (valuationStockPickingStore.pickingMode === "MODE:FINANCIAL") {
            void fetchPickingResult();
        } else {
            void startPickingJob();
        }
    },
    { immediate: true }
);

onMounted(() => {
    stockChartFilterStore.setTopBottomSwitch(false);
    updateTableHeight();
    window.addEventListener("resize", updateTableHeight);
});

onBeforeUnmount(() => {
    stopPickingJobPolling();
    window.removeEventListener("resize", updateTableHeight);
});
</script>

<style scoped>
.result-table-wrapper {
    width: 100%;
}

.result-table-controls {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
}

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

.stock-name-link {
    font-size: 14px;
    font-weight: bold;
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
</style>
