<template>
    <el-row :gutter="18">
        <el-col :span="tableResultSpan">
            <el-card>
                    <el-row style="margin-bottom: 10px;">
                        <el-col :span="24" style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
                            <span style="font-size: 12px; color: #606266;">周度低估清单下载：</span>
                            <el-link
                                v-if="downloadLinks.traditional.available && downloadLinks.traditional.downloadUrl"
                                :href="downloadLinks.traditional.downloadUrl"
                                type="primary"
                                underline="hover"
                                target="_blank"
                            >
                                下载传统估值 CSV
                            </el-link>
                            <span v-else style="font-size: 12px; color: #909399;">传统估值 CSV 未生成</span>
                            <span v-if="downloadLinks.traditional.updatedAt" style="font-size: 12px; color: #909399;">
                                {{ downloadLinks.traditional.updatedAt }}
                            </span>

                            <el-link
                                v-if="downloadLinks.predictive.available && downloadLinks.predictive.downloadUrl"
                                :href="downloadLinks.predictive.downloadUrl"
                                type="success"
                                underline="hover"
                                target="_blank"
                            >
                                下载预测估值 CSV
                            </el-link>
                            <span v-else style="font-size: 12px; color: #909399;">预测估值 CSV 未生成</span>
                            <span v-if="downloadLinks.predictive.updatedAt" style="font-size: 12px; color: #909399;">
                                {{ downloadLinks.predictive.updatedAt }}
                            </span>
                        </el-col>
                    </el-row>
                    <el-row v-if="jobStatusText" style="margin-bottom: 10px;">
                        <el-col :span="24">
                            <div style="display:flex; flex-direction:column; gap:6px;">
                                <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap; font-size:12px; color:#606266;">
                                    <el-tag size="small" :type="isJobLoading ? 'warning' : 'success'" effect="light">{{ jobStatusText }}</el-tag>
                                    <span v-if="jobMessage">{{ jobMessage }}</span>
                                    <span v-if="jobMatchedCount > 0">已命中 {{ jobMatchedCount }} 条</span>
                                    <span v-if="jobTotalCandidates > 0">候选 {{ jobTotalCandidates }} 支</span>
                                </div>
                                <el-progress v-if="isJobLoading" :percentage="jobProgressPct" :stroke-width="12" />
                            </div>
                        </el-col>
                    </el-row>
                    <el-row>
                        <el-col :span="24">
                            <el-table v-loading="isJobLoading" :data="pickingResult" style="width: 100%" size="small" height="400" @row-dblclick="onRowDblClick">
                                    <el-table-column prop="ts_code" label="代码" fixed="left">
                                        <template #default="{ row }">
                                            <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                                                <el-link type="primary" @click.stop="onStockClick(row)" style="font-size:12px" underline="never">{{ row.name + ' | ' + row.ts_code }}</el-link>
                                                <RecentReportBadge :visible="row.recent_report_badge" />
                                            </div>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="signal_peak_return_pct" label="信号至今最高涨幅(%)" :width="138">
                                        <template #default="{ row }">
                                            <span :style="{ color: (row.signal_peak_return_pct || 0) >= 0 ? 'red' : 'green' }">{{ formatPercentWithSymbol(row.signal_peak_return_pct) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="signal_trough_return_pct" label="信号至今最低涨幅(%)" :width="138">
                                        <template #default="{ row }">
                                            <span :style="{ color: (row.signal_trough_return_pct || 0) >= 0 ? 'red' : 'green' }">{{ formatPercentWithSymbol(row.signal_trough_return_pct) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="signal_current_return_pct" label="信号至今当前涨幅(%)" :width="138">
                                        <template #default="{ row }">
                                            <span :style="{ color: (row.signal_current_return_pct || 0) >= 0 ? 'red' : 'green' }">{{ formatPercentWithSymbol(row.signal_current_return_pct) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="top_or_bottom" label="高/低位">
                                        <template #default="{ row }">
                                            <el-tag v-if="row.top_or_bottom === 'B'" round effect="light" type="danger" size="small">底</el-tag>
                                            <el-tag v-else-if="row.top_or_bottom === 'T'" round effect="light" type="success" size="small">顶</el-tag>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="close_qfq" label="收盘价" />
                                    <el-table-column prop="pct_change_qfq" label="涨跌幅(%)">
                                        <template #default="{ row }">
                                            <span :style="{ color: row.pct_change_qfq >= 0 ? 'red' : 'green' }">{{ row.pct_change_qfq }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="sw_l3_name" label="SW行业" :width="150">
                                        <template #default="{ row }">
                                            <span>{{ row.sw_l3_name || row.industry_name || '-' }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="valuation_method" label="估值法" :width="90">
                                        <template #default="{ row }">
                                            <span>{{ methodLabel(row.valuation_method) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="valuation_price" label="估值价" :width="90" />
                                    <el-table-column prop="valuation_candidate_count" label="候选数" :width="78">
                                        <template #default="{ row }">
                                            <span>{{ row.valuation_candidate_count ?? 0 }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="valuation_pick_strategy" label="主值策略" :width="95" />
                                    <el-table-column prop="valuation_recommendation_confidence" label="推荐置信度" :width="95">
                                        <template #default="{ row }">
                                            <span>{{ row.valuation_recommendation_confidence ?? '-' }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="valuation_method_recommended" label="推荐序列" :width="150">
                                        <template #default="{ row }">
                                            <span>{{ Array.isArray(row.valuation_method_recommended) ? row.valuation_method_recommended.slice(0, 3).join('/') : '-' }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="valuation_market_cap" label="估值市值(亿)" :width="120">
                                        <template #default="{ row }">
                                            <span>{{ formatValuationMarketCapYi(row.valuation_market_cap) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="valuation_gap_pct" label="偏离(%)" :width="90">
                                        <template #default="{ row }">
                                            <span :style="{ color: (row.valuation_gap_pct || 0) >= 0 ? 'red' : 'green' }">{{ row.valuation_gap_pct ?? '-' }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="valuation_status" label="估值判断" :width="90">
                                        <template #default="{ row }">
                                            <el-tag v-if="row.valuation_status === 'under'" round effect="light" type="danger" size="small">低估</el-tag>
                                            <el-tag v-else-if="row.valuation_status === 'over'" round effect="light" type="success" size="small">高估</el-tag>
                                            <el-tag v-else-if="row.valuation_status === 'fair'" round effect="light" type="info" size="small">正常</el-tag>
                                            <span v-else>-</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="buy_candidate" label="候选" :width="88">
                                        <template #default="{ row }">
                                            <el-tag v-if="row.buy_candidate" round effect="light" type="danger" size="small">可买</el-tag>
                                            <el-tag v-else round effect="light" type="info" size="small">观察</el-tag>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="valuation_score" label="估值分数" :width="88">
                                        <template #default="{ row }">
                                            <span :style="{ color: getUndervalueScoreColor(row.valuation_score ?? row.undervalue_score) }">{{ formatScore(row.valuation_score ?? row.undervalue_score) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="!isPredictiveMode" prop="valuation_risk_score" label="风险分" :width="88">
                                        <template #default="{ row }">
                                            <span :style="{ color: getRiskScoreColor(row.valuation_risk_score) }">{{ formatScore(row.valuation_risk_score) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="!isPredictiveMode" prop="valuation_risk_level" label="风险级别" :width="92">
                                        <template #default="{ row }">
                                            <el-tag v-if="traditionalRiskTagType(row.valuation_risk_level)" round effect="light" :type="traditionalRiskTagType(row.valuation_risk_level)" size="small">{{ riskLabel(row.valuation_risk_level) }}</el-tag>
                                            <span v-else>-</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="!isPredictiveMode" prop="financial_netprofit" label="净利润(亿)" :width="100">
                                        <template #default="{ row }">
                                            <span>{{ formatMoneyYi(row.financial_netprofit) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="!isPredictiveMode" prop="financial_netprofit_end_date" label="净利润财报期" :width="108" />
                                    <el-table-column prop="composite_valuation_price" label="组合估值价" :width="105">
                                        <template #default="{ row }">
                                            <span>{{ formatPrice(row.composite_valuation_price) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="conservative_valuation_price" label="保守估值价" :width="105">
                                        <template #default="{ row }">
                                            <span>{{ formatPrice(row.conservative_valuation_price) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="valuation_source" label="来源" :width="95">
                                        <template #default="{ row }">
                                            <el-tag v-if="row.valuation_source === 'snapshot_cache'" round effect="light" type="warning" size="small">缓存</el-tag>
                                            <el-tag v-else-if="row.valuation_source === 'live_compute'" round effect="light" type="primary" size="small">实时</el-tag>
                                            <el-tag v-else-if="row.valuation_source === 'error'" round effect="light" type="danger" size="small">失败</el-tag>
                                            <span v-else>-</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="valuation_profit_report_type" label="估值口径" :width="90">
                                        <template #default="{ row }">
                                            <el-tag v-if="row.valuation_profit_report_type" round effect="light" type="info" size="small">{{ row.valuation_profit_report_type }}</el-tag>
                                            <span v-else>-</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="valuation_profit_report_end_date" label="估值财报期" :width="105" />
                                    <el-table-column v-if="isPredictiveMode" prop="earnings_report_type" label="报告口径" :width="90">
                                        <template #default="{ row }">
                                            <el-tag round effect="light" type="primary" size="small">{{ row.earnings_report_type || '-' }}</el-tag>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="isPredictiveMode" prop="financial_fiscal_year" label="财年" :width="70" />
                                    <el-table-column v-if="isPredictiveMode" prop="financial_ann_date" label="公告日" :width="100" />
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
                                    <el-table-column v-if="isPredictiveMode" prop="pred_earnings_growth" label="净利增速(%)" :width="110">
                                        <template #default="{ row }">
                                            <span :style="{ color: (row.pred_earnings_growth || 0) >= 0.2 ? 'red' : '#606266' }">{{ formatPercent(row.pred_earnings_growth) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="isPredictiveMode" prop="feature_data_source" label="预测来源" :width="95">
                                        <template #default="{ row }">
                                            <span>{{ row.feature_data_source || '-' }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="isPredictiveMode" prop="predictive_pick_score" label="预测总分" :width="95">
                                        <template #default="{ row }">
                                            <span :style="{ color: getSignalScoreColor(row.predictive_pick_score) }">{{ formatPrice(row.predictive_pick_score) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="website" label="网站" :width="150">
                                        <template #default="{ row }">
                                            <el-link v-if="row.website" :href="row.website.startsWith('http') ? row.website : `https://${row.website}`" target="_blank" type="primary" style="font-size:12px" underline="hover">{{ row.website }}</el-link>
                                            <span v-else>-</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="main_business" label="主营业务" :width="350"/>
                                    <el-table-column prop="valuation_recommendation_reason" label="推荐依据" :width="260"/>
                            </el-table>
                        </el-col>
                    </el-row>
                    <el-row :gutter="12" style="margin-top: 10px;">
                        <el-col :span="controlSpan">
                            <el-button type="primary" @click="fetchPrevPage" size="small" :disabled="isJobLoading">上一页</el-button>
                            <el-button type="primary" @click="fetchNextPage" size="small" :disabled="isJobLoading || !hasNextPage">下一页</el-button>
                            <el-button type="warning" plain @click="sortByUndervalue('desc')" size="small">低估分降序</el-button>
                            <el-button type="warning" plain @click="sortByUndervalue('asc')" size="small">低估分升序</el-button>
                            <el-button type="primary" @click="expandTableResult" size="small">展开</el-button>
                            <span style="margin-left: 10px; color: #606266; font-size: 12px;">
                                命中总数: {{ totalFiltered }} | 当前范围: {{ currentRangeStart }}-{{ currentRangeEnd }}
                            </span>
                        </el-col>
                    </el-row>
            </el-card>
        </el-col>
        <el-col :span="chartSpan">
            <el-card>
                <el-tabs v-model="overviewTab" class="overview-tabs">
                    <el-tab-pane label="估值一览" name="valuation">
                        <StockValuationQuickView :embedded="true" />
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
            </el-card>
        </el-col>
    </el-row>
</template>

<script setup lang="ts">
import { ElCard, ElTable, ElTableColumn, ElMessage, ElLink, ElRow, ElCol, ElButton, ElTag, ElTabs, ElTabPane, ElProgress } from "element-plus";
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

const valuationStockPickingStore = useValuationStockPickingStore();
const stockTradeStore = useStockTradeStore();
const stockChartFilterStore = useStockChartFilterStore();

const tableResultSpan = ref(24);
const chartSpan = ref(0);
const controlSpan = ref(10);
const isResultTableElapsed = ref(false);

const fromIndex = ref(0);
const toIndex = ref(25);
const increment = ref(25);
const curFromIndex = ref(0);
const curToIndex = ref(25);
const totalFiltered = ref(0);
const currentRangeStart = ref(0);
const currentRangeEnd = ref(0);
const hasNextPage = computed(() => {
    const total = Number(totalFiltered.value || 0);
    if (total <= 0) {
        return false;
    }
    return Number(curToIndex.value || 0) < total;
});
const overviewTab = ref("valuation");
const trendChartCompRef = ref<InstanceType<typeof StockChart> | null>(null);

const baseURL = inject<string>("baseURL", "");
const pickingResult = ref<Array<Record<string, any>>>([]);
const isPredictiveMode = computed(() => valuationStockPickingStore.pickingMode === "MODE:PREDICTIVE");
const isJobLoading = ref(false);
const jobStatusText = ref("");
const jobMessage = ref("");
const jobProgressPct = ref(0);
const jobMatchedCount = ref(0);
const jobTotalCandidates = ref(0);
const activeJobId = ref("");
let jobPollTimer: number | null = null;
const downloadLinks = ref({
    traditional: {
        available: false,
        downloadUrl: "",
        updatedAt: "",
    },
    predictive: {
        available: false,
        downloadUrl: "",
        updatedAt: "",
    },
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

function stopPickingJobPolling() {
    if (jobPollTimer !== null) {
        window.clearTimeout(jobPollTimer);
        jobPollTimer = null;
    }
}

async function loadWeeklyDownloadLinks() {
    if (!baseURL) {
        return;
    }
    try {
        const res = await axios.get(buildApiUrl("/stock-pick-valuation/weekly-downloads/"));
        const data = res?.data?.data || {};
        downloadLinks.value = {
            traditional: {
                available: Boolean(data?.traditional?.available),
                downloadUrl: data?.traditional?.download_url ? buildApiUrl(data.traditional.download_url) : "",
                updatedAt: data?.traditional?.updated_at || "",
            },
            predictive: {
                available: Boolean(data?.predictive?.available),
                downloadUrl: data?.predictive?.download_url ? buildApiUrl(data.predictive.download_url) : "",
                updatedAt: data?.predictive?.updated_at || "",
            },
        };
    } catch (_error) {
        downloadLinks.value = {
            traditional: { available: false, downloadUrl: "", updatedAt: "" },
            predictive: { available: false, downloadUrl: "", updatedAt: "" },
        };
    }
}

const onRowDblClick = (row: any) => {
    stockTradeStore.setTsCode(row.ts_code);
    stockTradeStore.setName(row.name);
    stockTradeStore.setWebsite(row.website);
    stockTradeStore.setPreferredValuationVariant(resolvePreferredValuationVariant(row));
    if (!isResultTableElapsed.value) {
        tableResultSpan.value = 8;
        chartSpan.value = 16;
        controlSpan.value = 20;
        isResultTableElapsed.value = true;
    }
};

const expandTableResult = () => {
    isResultTableElapsed.value = false;
    tableResultSpan.value = 24;
    chartSpan.value = 0;
    controlSpan.value = 10;
};

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
    stockTradeStore.setTsCode(row.ts_code);
    stockTradeStore.setName(row.name);
    stockTradeStore.setWebsite(row.website);
    stockTradeStore.setPreferredValuationVariant(resolvePreferredValuationVariant(row));
};

function formatValuationMarketCapYi(value: any) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "-";
    return (numeric / 100000000).toFixed(2);
}

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

function formatMoneyYi(value: any) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "-";
    return (numeric / 100000000).toFixed(2);
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

function getRiskScoreColor(value: any) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "#909399";
    if (numeric >= 70) return "#cf1322";
    if (numeric >= 45) return "#d46b08";
    return "#389e0d";
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
    return "";
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
    return "";
}

function traditionalRiskTagType(risk: any) {
    const normalized = normalizeRisk(risk);
    if (normalized === "LOW" || normalized === "L") return "success";
    if (normalized === "MEDIUM" || normalized === "M") return "warning";
    if (normalized === "HIGH" || normalized === "H") return "danger";
    return "";
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
        const valuationMethodVal = valuationStockPickingStore.valuationMethod.split(":")[1].toLowerCase();
        const valuationStatusVal = valuationStockPickingStore.valuationStatus.split(":")[1] !== "NONE" ? valuationStockPickingStore.valuationStatus.split(":")[1].toLowerCase() : "";
        const buyCandidateOnlyVal = valuationStockPickingStore.buyCandidateOnly.split(":")[1] === "ONLY" ? "1" : "";
        const valuationPickStrategyVal = valuationStockPickingStore.valuationPickStrategy.split(":")[1].toLowerCase();
        const pickingModeVal = valuationStockPickingStore.pickingMode.split(":")[1].toLowerCase();
        const earningsReportTypeVal = valuationStockPickingStore.earningsReportType.split(":")[1];
        const signalActionVal = valuationStockPickingStore.signalAction.split(":")[1];
        const riskLevelParam = String(valuationStockPickingStore.riskLevel || "")
            .split(",")
            .map((item) => item.trim().toUpperCase())
            .filter((item) => item === "LOW" || item === "MEDIUM" || item === "HIGH")
            .join(",");
        const featureDataSourceVal = valuationStockPickingStore.featureDataSource.split(":")[1];
        const netprofitGrowthVal = valuationStockPickingStore.netprofitGrowth.split(":")[1];
        const sharedMinScoreVal = String(valuationStockPickingStore.minSignalScore || "").trim();

        const search = new URLSearchParams();
        search.set("freq", valuationStockPickingStore.freq);
        search.set("from_index", String(fromIndex.value));
        search.set("to_index", String(toIndex.value));
        search.set("picking_mode", pickingModeVal);
        search.set("valuation_method", valuationMethodVal);
        if (valuationStatusVal) search.set("valuation_status", valuationStatusVal);
        search.set("valuation_band_pct", valuationStockPickingStore.valuationBandPct);
        search.set("valuation_pick_strategy", valuationPickStrategyVal);
        if (buyCandidateOnlyVal) search.set("buy_candidate_only", buyCandidateOnlyVal);
        if (valuationStockPickingStore.swIndustry) search.set("sw_industry", valuationStockPickingStore.swIndustry);
        search.set("earnings_report_type", earningsReportTypeVal);
        if (riskLevelParam) search.set("risk_level", riskLevelParam);
        if (netprofitGrowthVal !== "ALL") search.set("netprofit_growth", netprofitGrowthVal);
        if (pickingModeVal === "predictive") {
            if (signalActionVal !== "ALL") search.set("signal_action", signalActionVal);
            if (sharedMinScoreVal) search.set("min_signal_score", sharedMinScoreVal);
            if (valuationStockPickingStore.minTargetReturnPct) search.set("min_target_return_pct", valuationStockPickingStore.minTargetReturnPct);
            if (featureDataSourceVal !== "ALL") search.set("feature_data_source", featureDataSourceVal);
            if (valuationStockPickingStore.fiscalYear) search.set("fiscal_year", valuationStockPickingStore.fiscalYear);
        } else {
            if (sharedMinScoreVal) search.set("min_valuation_score", sharedMinScoreVal);
        }

        const url = `${baseURL}/stock-pick-valuation/${valuationStockPickingStore.tradeDate}/${valuationStockPickingStore.scopeParam}/?${search.toString()}`;
        const requestFrom = fromIndex.value;
        const requestTo = toIndex.value;
        const res = await axios.get(url);

        if (res.data) {
            pickingResult.value = res.data.data || [];
            const responseMeta = (res.data || {}).meta || {};
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
        }
    } catch (error) {
        ElMessage.error("获取估值选股结果失败，请稍后重试");
    }
}

function buildPickingJobPayload() {
    const valuationMethodVal = valuationStockPickingStore.valuationMethod.split(":")[1].toLowerCase();
    const valuationStatusVal = valuationStockPickingStore.valuationStatus.split(":")[1] !== "NONE" ? valuationStockPickingStore.valuationStatus.split(":")[1].toLowerCase() : "";
    const buyCandidateOnlyVal = valuationStockPickingStore.buyCandidateOnly.split(":")[1] === "ONLY" ? "1" : "";
    const valuationPickStrategyVal = valuationStockPickingStore.valuationPickStrategy.split(":")[1].toLowerCase();
    const pickingModeVal = valuationStockPickingStore.pickingMode.split(":")[1].toLowerCase();
    const earningsReportTypeVal = valuationStockPickingStore.earningsReportType.split(":")[1];
    const signalActionVal = valuationStockPickingStore.signalAction.split(":")[1];
    const riskLevelParam = String(valuationStockPickingStore.riskLevel || "").split(",").map((item) => item.trim().toUpperCase()).filter((item) => item === "LOW" || item === "MEDIUM" || item === "HIGH").join(",");
    const featureDataSourceVal = valuationStockPickingStore.featureDataSource.split(":")[1];
    const netprofitGrowthVal = valuationStockPickingStore.netprofitGrowth.split(":")[1];
    const sharedMinScoreVal = String(valuationStockPickingStore.minSignalScore || "").trim();
    const query: Record<string, string> = {
        freq: valuationStockPickingStore.freq,
        from_index: "0",
        to_index: "25",
        picking_mode: pickingModeVal,
        valuation_method: valuationMethodVal,
        valuation_band_pct: valuationStockPickingStore.valuationBandPct,
        valuation_pick_strategy: valuationPickStrategyVal,
        earnings_report_type: earningsReportTypeVal,
    };
    if (valuationStatusVal) query.valuation_status = valuationStatusVal;
    if (buyCandidateOnlyVal) query.buy_candidate_only = buyCandidateOnlyVal;
    if (valuationStockPickingStore.swIndustry) query.sw_industry = valuationStockPickingStore.swIndustry;
    if (riskLevelParam) query.risk_level = riskLevelParam;
    if (netprofitGrowthVal !== "ALL") query.netprofit_growth = netprofitGrowthVal;
    if (pickingModeVal === "predictive") {
        if (signalActionVal !== "ALL") query.signal_action = signalActionVal;
        if (sharedMinScoreVal) query.min_signal_score = sharedMinScoreVal;
        if (valuationStockPickingStore.minTargetReturnPct) query.min_target_return_pct = valuationStockPickingStore.minTargetReturnPct;
        if (featureDataSourceVal !== "ALL") query.feature_data_source = featureDataSourceVal;
        if (valuationStockPickingStore.fiscalYear) query.fiscal_year = valuationStockPickingStore.fiscalYear;
    } else if (sharedMinScoreVal) {
        query.min_valuation_score = sharedMinScoreVal;
    }
    return {
        trade_date: valuationStockPickingStore.tradeDate,
        scope: valuationStockPickingStore.scopeParam,
        query,
    };
}

function applyPickingJobState(payload: any) {
    const rows = Array.isArray(payload?.data) ? payload.data : [];
    pickingResult.value = rows;
    totalFiltered.value = Number(payload?.matched_count ?? payload?.meta?.total_filtered ?? 0);
    jobMatchedCount.value = totalFiltered.value;
    jobTotalCandidates.value = Number(payload?.total_candidates ?? payload?.meta?.total_candidates ?? 0);
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
    }
    valuationStockPickingStore.setPickingResults(
        rows.map((item: any) => ({ ts_code: item.ts_code, name: item.name, close_qfq: item.close_qfq, pct_change_qfq: item.pct_change_qfq }))
    );
}

async function pollPickingJob(jobId: string) {
    try {
        const res = await axios.get(buildApiUrl(`/stock-pick-valuation/jobs/${jobId}/`));
        const payload = res.data || {};
        if (activeJobId.value !== jobId) return;
        jobProgressPct.value = Number(payload.progress_pct || 0);
        jobMessage.value = String(payload.message || "");
        const status = String(payload.status || "");
        jobStatusText.value = status === "queued" ? "排队中" : status === "running" ? "计算中" : status === "done" ? "已完成" : status === "failed" ? "失败" : "处理中";
        applyPickingJobState(payload);
        if (status === "done") {
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
        jobPollTimer = window.setTimeout(() => { void pollPickingJob(jobId); }, pollIntervalSeconds * 1000);
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
        const res = await axios.post(buildApiUrl("/stock-pick-valuation/jobs/"), buildPickingJobPayload());
        const payload = res.data || {};
        const jobId = String(payload.job_id || "").trim();
        if (!jobId) throw new Error("missing job_id");
        activeJobId.value = jobId;
        jobStatusText.value = String(payload.status || "queued") === "queued" ? "排队中" : "计算中";
        jobMessage.value = String(payload.message || "");
        await pollPickingJob(jobId);
    } catch (_error) {
        isJobLoading.value = false;
        stopPickingJobPolling();
        ElMessage.error("提交选股任务失败，请稍后重试");
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
        () => valuationStockPickingStore.buyCandidateOnly,
        () => valuationStockPickingStore.swIndustry,
        () => valuationStockPickingStore.earningsReportType,
        () => valuationStockPickingStore.signalAction,
        () => valuationStockPickingStore.riskLevel,
        () => valuationStockPickingStore.minSignalScore,
        () => valuationStockPickingStore.minTargetReturnPct,
        () => valuationStockPickingStore.featureDataSource,
        () => valuationStockPickingStore.fiscalYear,
        () => valuationStockPickingStore.netprofitGrowth,
    ],
    () => {
        fromIndex.value = 0;
        toIndex.value = 25;
        currentRangeStart.value = 0;
        currentRangeEnd.value = 0;
        void startPickingJob();
    }
);

onMounted(() => {
    stockChartFilterStore.setTopBottomSwitch(false);
    loadWeeklyDownloadLinks();
});

onBeforeUnmount(() => {
    stopPickingJobPolling();
});
</script>

<style scoped></style>
