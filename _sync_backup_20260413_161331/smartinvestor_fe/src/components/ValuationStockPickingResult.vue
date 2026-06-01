<template>
    <el-row :gutter="18">
        <el-col :span="tableResultSpan">
            <el-affix :offset="285">
                <el-card>
                    <el-row>
                        <el-col :span="24">
                            <el-table :data="pickingResult" style="width: 100%" size="small" height="400" @row-dblclick="onRowDblClick">
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
                                    <el-table-column prop="valuation_method" label="估值法" :width="90" />
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
                                    <el-table-column prop="undervalue_score" label="低估分" :width="88">
                                        <template #default="{ row }">
                                            <span :style="{ color: getUndervalueScoreColor(row.undervalue_score) }">{{ formatScore(row.undervalue_score) }}</span>
                                        </template>
                                    </el-table-column>
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
                                    <el-table-column v-if="isPredictiveMode" prop="action" label="动作" :width="90">
                                        <template #default="{ row }">
                                            <el-tag v-if="row.action === 'BUY'" round effect="light" type="danger" size="small">BUY</el-tag>
                                            <el-tag v-else-if="row.action === 'HOLD'" round effect="light" type="info" size="small">HOLD</el-tag>
                                            <el-tag v-else-if="row.action === 'SELL_PART'" round effect="light" type="warning" size="small">SELL_PART</el-tag>
                                            <el-tag v-else-if="row.action === 'SELL'" round effect="light" type="success" size="small">SELL</el-tag>
                                            <span v-else>-</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="isPredictiveMode" prop="risk_level" label="风险" :width="85">
                                        <template #default="{ row }">
                                            <el-tag v-if="row.risk_level === 'LOW'" round effect="light" type="danger" size="small">LOW</el-tag>
                                            <el-tag v-else-if="row.risk_level === 'MEDIUM'" round effect="light" type="warning" size="small">MEDIUM</el-tag>
                                            <el-tag v-else-if="row.risk_level === 'HIGH'" round effect="light" type="success" size="small">HIGH</el-tag>
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
                            <el-button type="primary" @click="fetchPrevPage" size="small">上一页</el-button>
                            <el-button type="primary" @click="fetchNextPage" size="small">下一页</el-button>
                            <el-button type="primary" @click="expandTableResult" size="small">展开</el-button>
                            <span style="margin-left: 10px; color: #606266; font-size: 12px;">
                                命中总数: {{ totalFiltered }} | 当前范围: {{ currentRangeStart }}-{{ currentRangeEnd }}
                            </span>
                        </el-col>
                    </el-row>
                </el-card>
            </el-affix>
        </el-col>
        <el-col :span="chartSpan">
            <StockChart :displayEmbed="true" />
        </el-col>
    </el-row>
</template>

<script setup lang="ts">
import { ElCard, ElTable, ElTableColumn, ElMessage, ElLink, ElRow, ElCol, ElButton, ElAffix, ElTag } from "element-plus";
import { computed, ref, watch, onMounted } from "vue";
import axios from "axios";
import { inject } from "vue";
import { useValuationStockPickingStore } from "../stores/valuationStockPickingStore";
import { useStockTradeStore } from "../stores/stockTradeStore";
import { useStockChartFilterStore } from "../stores/stockChartFilterStore";
import StockChart from "../components/StockChart.vue";
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

const baseURL = inject<string>("baseURL", "");
const pickingResult = ref<Array<Record<string, any>>>([]);
const isPredictiveMode = computed(() => valuationStockPickingStore.pickingMode === "MODE:PREDICTIVE");

const onRowDblClick = (row: any) => {
    stockTradeStore.setTsCode(row.ts_code);
    stockTradeStore.setName(row.name);
    stockTradeStore.setWebsite(row.website);
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

const onStockClick = (row: any) => {
    stockTradeStore.setTsCode(row.ts_code);
    stockTradeStore.setName(row.name);
    stockTradeStore.setWebsite(row.website);
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
        const riskLevelVal = valuationStockPickingStore.riskLevel.split(":")[1];
        const featureDataSourceVal = valuationStockPickingStore.featureDataSource.split(":")[1];
        const netprofitGrowthVal = valuationStockPickingStore.netprofitGrowth.split(":")[1];

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
        if (pickingModeVal === "predictive") {
            if (signalActionVal !== "ALL") search.set("signal_action", signalActionVal);
            if (riskLevelVal !== "ALL") search.set("risk_level", riskLevelVal);
            if (valuationStockPickingStore.minSignalScore) search.set("min_signal_score", valuationStockPickingStore.minSignalScore);
            if (valuationStockPickingStore.minTargetReturnPct) search.set("min_target_return_pct", valuationStockPickingStore.minTargetReturnPct);
            if (featureDataSourceVal !== "ALL") search.set("feature_data_source", featureDataSourceVal);
            if (valuationStockPickingStore.fiscalYear) search.set("fiscal_year", valuationStockPickingStore.fiscalYear);
            if (netprofitGrowthVal !== "ALL") search.set("netprofit_growth", netprofitGrowthVal);
        }

        const url = `${baseURL}/stock-pick-valuation/${valuationStockPickingStore.tradeDate}/${valuationStockPickingStore.scopeParam}/?${search.toString()}`;
        const requestFrom = fromIndex.value;
        const requestTo = toIndex.value;
        const res = await axios.get(url);

        if (res.data) {
            pickingResult.value = res.data.data || [];
            const responseMeta = (res.data || {}).meta || {};
            totalFiltered.value = Number(responseMeta.total_filtered || 0);
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

async function fetchPrevPage() {
    if (curFromIndex.value <= 0) return;
    fromIndex.value = curFromIndex.value - increment.value;
    toIndex.value = curToIndex.value - increment.value;
    await fetchPickingResult();
}

async function fetchNextPage() {
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
        fetchPickingResult();
    }
);

onMounted(() => {
    stockChartFilterStore.setTopBottomSwitch(true);
});
</script>

<style scoped></style>
