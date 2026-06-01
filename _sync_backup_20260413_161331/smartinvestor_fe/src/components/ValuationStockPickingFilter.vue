<template>
    <el-affix :offset="75">
        <el-card>
            <el-row :gutter="2" style="font-size: x-small; margin-bottom: 12px;color: gray;">
                <el-col :span="9">
                    <span style="display: flex; align-items: center;">
                        <span style="margin-right: 6px;">选股日期：</span>
                        <el-date-picker v-model="selectedDate" type="date" placeholder="选股日期" :size="'small'" style="margin-right: 6px;" />
                    </span>
                </el-col>
                <el-col :span="7">
                    <span style="display: inline-block; vertical-align: middle;">周期：</span>
                    <el-radio-group v-model="selectedFreq" size="small" style="display: inline-block; vertical-align: middle; margin-left: 4px;">
                        <el-radio-button label="D">日</el-radio-button>
                        <el-radio-button label="W">周</el-radio-button>
                        <el-radio-button label="M">月</el-radio-button>
                    </el-radio-group>
                </el-col>
                <el-col :span="8">
                    <span style="display: inline-block; vertical-align: middle;">时长：</span>
                    <el-radio-group v-model="selectedPickingPeriod" size="small" style="display: inline-block; vertical-align: middle; margin-left: 4px;">
                        <el-radio-button label="30">30</el-radio-button>
                        <el-radio-button label="60">60</el-radio-button>
                        <el-radio-button label="200">200</el-radio-button>
                    </el-radio-group>
                </el-col>
            </el-row>

            <el-row :gutter="2" style="font-size: x-small; margin-bottom: 6px; color: gray;">
                <el-col :span="24">
                    <span style="display: inline-block; vertical-align: middle;">选股模式：</span>
                    <el-radio-group v-model="selectedPickingMode" size="small" style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="MODE:BASELINE">传统估值</el-radio-button>
                        <el-radio-button label="MODE:PREDICTIVE">预测估值</el-radio-button>
                    </el-radio-group>
                    <span style="margin-left: 8px; color: #909399;">传统估值支持 Q1/H1/Q3/FY/快报 口径筛选；预测估值额外支持 FUSION。</span>
                </el-col>
            </el-row>

            <el-row :gutter="2" style="font-size: x-small; margin-bottom: 6px; color: gray;">
                <el-col :span="isPredictiveMode ? 10 : 24">
                    <span style="display: inline-block; vertical-align: middle;">报告口径：</span>
                    <el-radio-group v-model="selectedEarningsReportType" size="small" style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="ERT:ALL">综合</el-radio-button>
                        <el-radio-button label="ERT:Q1">Q1</el-radio-button>
                        <el-radio-button label="ERT:H1">H1</el-radio-button>
                        <el-radio-button label="ERT:Q3">Q3</el-radio-button>
                        <el-radio-button label="ERT:FY">FY</el-radio-button>
                        <el-radio-button v-if="!isPredictiveMode" label="ERT:快">快报</el-radio-button>
                        <el-radio-button v-if="isPredictiveMode" label="ERT:FUSION">Fusion</el-radio-button>
                    </el-radio-group>
                </el-col>
                <el-col v-if="isPredictiveMode" :span="7">
                    <span style="display: inline-block; vertical-align: middle;">动作：</span>
                    <el-radio-group v-model="selectedSignalAction" size="small" style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="SA:ALL">全部</el-radio-button>
                        <el-radio-button label="SA:BUY">BUY</el-radio-button>
                        <el-radio-button label="SA:HOLD">HOLD</el-radio-button>
                        <el-radio-button label="SA:SELL_PART">SELL_PART</el-radio-button>
                        <el-radio-button label="SA:SELL">SELL</el-radio-button>
                    </el-radio-group>
                </el-col>
                <el-col v-if="isPredictiveMode" :span="7">
                    <span style="display: inline-block; vertical-align: middle;">风险：</span>
                    <el-radio-group v-model="selectedRiskLevel" size="small" style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="RL:ALL">全部</el-radio-button>
                        <el-radio-button label="RL:LOW">LOW</el-radio-button>
                        <el-radio-button label="RL:MEDIUM">MEDIUM</el-radio-button>
                        <el-radio-button label="RL:HIGH">HIGH</el-radio-button>
                    </el-radio-group>
                </el-col>
            </el-row>

            <el-row v-if="isPredictiveMode" :gutter="2" style="font-size: x-small; margin-bottom: 6px; color: gray;">
                <el-col :span="6">
                    <span style="display: inline-block; vertical-align: middle;">最低分数：</span>
                    <el-input v-model="selectedMinSignalScore" size="small" placeholder="如 60" style="width: 110px; margin-left: 8px;" clearable />
                </el-col>
                <el-col :span="6">
                    <span style="display: inline-block; vertical-align: middle;">最低收益率：</span>
                    <el-input v-model="selectedMinTargetReturnPct" size="small" placeholder="如 15" style="width: 110px; margin-left: 8px;" clearable />
                </el-col>
                <el-col :span="6">
                    <span style="display: inline-block; vertical-align: middle;">数据来源：</span>
                    <el-radio-group v-model="selectedFeatureDataSource" size="small" style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="EDS:ALL">全部</el-radio-button>
                        <el-radio-button label="EDS:live_db">live</el-radio-button>
                        <el-radio-button label="EDS:dataset_fallback">fallback</el-radio-button>
                        <el-radio-button label="EDS:fusion">fusion</el-radio-button>
                    </el-radio-group>
                </el-col>
                <el-col :span="6">
                    <span style="display: inline-block; vertical-align: middle;">财报年份：</span>
                    <el-input v-model="selectedFiscalYear" size="small" placeholder="如 2024" style="width: 110px; margin-left: 8px;" clearable />
                </el-col>
            </el-row>

            <el-row v-if="isPredictiveMode" :gutter="2" style="font-size: x-small; margin-bottom: 6px; color: gray;">
                <el-col :span="24">
                    <span style="display: inline-block; vertical-align: middle;">净利增速：</span>
                    <el-radio-group v-model="selectedNetprofitGrowth" size="small" style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="NPG:ALL">全部</el-radio-button>
                        <el-radio-button label="NPG:HIGH">高增长(>=20%)</el-radio-button>
                    </el-radio-group>
                </el-col>
            </el-row>

            <el-row :gutter="2" style="font-size: x-small; margin-bottom: 6px; color: gray;">
                <el-col :span="24">
                    <span style="display: inline-block; vertical-align: middle;">估值方法：</span>
                    <el-radio-group v-model="selectedValuationMethod" size="small" style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="VM:RECOMMENDED">行业推荐</el-radio-button>
                        <el-radio-button label="VM:PE">PE</el-radio-button>
                        <el-radio-button label="VM:PB">PB</el-radio-button>
                        <el-radio-button label="VM:PS">PS</el-radio-button>
                        <el-radio-button label="VM:PEG">PEG</el-radio-button>
                        <el-radio-button label="VM:FCFF_DCF">FCFF</el-radio-button>
                        <el-radio-button label="VM:DDM">DDM</el-radio-button>
                    </el-radio-group>
                    <span style="margin-left: 8px; color: #909399;">行业推荐: 按股票所属行业模板自动优先选择更合适的估值法</span>
                </el-col>
            </el-row>

            <el-row :gutter="2" style="font-size: x-small; margin-bottom: 6px; color: gray;">
                <el-col :span="9">
                    <span style="display: inline-block; vertical-align: middle;">估值状态：</span>
                    <el-radio-group v-model="selectedValuationStatus" size="small" style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="VS:NONE">不筛选</el-radio-button>
                        <el-radio-button label="VS:UNDER">低估</el-radio-button>
                        <el-radio-button label="VS:FAIR">正常</el-radio-button>
                        <el-radio-button label="VS:OVER">高估</el-radio-button>
                    </el-radio-group>
                </el-col>
                <el-col :span="7">
                    <span style="display: inline-block; vertical-align: middle;">偏离带：</span>
                    <el-radio-group v-model="selectedValuationBand" size="small" style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="0.1">10%</el-radio-button>
                        <el-radio-button label="0.15">15%</el-radio-button>
                        <el-radio-button label="0.2">20%</el-radio-button>
                    </el-radio-group>
                </el-col>
                <el-col :span="8">
                    <span style="display: inline-block; vertical-align: middle;">买入候选：</span>
                    <el-radio-group v-model="selectedBuyCandidateOnly" size="small" style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="BC:NONE">全部</el-radio-button>
                        <el-radio-button label="BC:ONLY">仅可买</el-radio-button>
                    </el-radio-group>
                </el-col>
            </el-row>

            <el-row :gutter="2" style="font-size: x-small; margin-bottom: 6px; color: gray;">
                <el-col :span="24">
                    <span style="display: inline-block; vertical-align: middle;">主值策略：</span>
                    <el-radio-group v-model="selectedValuationPickStrategy" size="small" style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="VPS:BASELINE">基准优先</el-radio-button>
                        <el-radio-button label="VPS:BEST_SCORE">最高匹配</el-radio-button>
                        <el-radio-button label="VPS:MEDIAN">中位数</el-radio-button>
                        <el-radio-button label="VPS:MIN">最保守</el-radio-button>
                        <el-radio-button label="VPS:MAX">最乐观</el-radio-button>
                        <el-radio-button label="VPS:FIRST">最新一条</el-radio-button>
                    </el-radio-group>
                </el-col>
            </el-row>

            <el-row :gutter="2" style="font-size: x-small; margin-bottom: 6px; color: gray;">
                <el-col :span="24">
                    <span style="display: inline-block; vertical-align: middle;">SW行业：</span>
                    <el-select
                        v-model="selectedSwIndustry"
                        size="small"
                        filterable
                        clearable
                        placeholder="不筛选"
                        style="width: 360px; margin-left: 8px;"
                    >
                        <el-option
                            v-for="item in swIndustryOptions"
                            :key="item.industry_code"
                            :label="`${item.industry_code} | ${item.industry_name}`"
                            :value="item.industry_code"
                        />
                    </el-select>
                </el-col>
            </el-row>


            <el-row :gutter="2" style="font-size: x-small;color: gray;">
                <el-col :span="24">
                    <span style="display: inline-block; vertical-align: middle;">选股范围：</span>
                    <el-radio-group v-model="selectedScope" size="small" style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="SCOPE:NONE">请选择</el-radio-button>
                        <el-radio-button label="WATCHLIST">自</el-radio-button>
                        <el-radio-button label="60">沪</el-radio-button>
                        <el-radio-button label="0">深</el-radio-button>
                        <el-radio-button label="3">创</el-radio-button>
                        <el-radio-button label="688">科</el-radio-button>
                    </el-radio-group>
                </el-col>
            </el-row>
        </el-card>
    </el-affix>
</template>

<script setup lang="ts">
import { computed, ref, watch, onMounted, inject } from "vue";
import axios from "axios";
import { ElRow, ElCol, ElCard, ElRadioGroup, ElRadioButton, ElAffix, ElDatePicker, ElSelect, ElOption, ElInput } from "element-plus";
import { useValuationStockPickingStore } from "../stores/valuationStockPickingStore";

const valuationStockPickingStore = useValuationStockPickingStore();
const baseURL = inject<string>("baseURL", "");

const selectedPickingPeriod = ref("60");
const selectedFreq = ref("D");
const selectedDate = ref(new Date());
const selectedScope = ref("SCOPE:NONE");
const selectedPickingMode = ref("MODE:BASELINE");
const selectedValuationMethod = ref("VM:RECOMMENDED");
const selectedValuationStatus = ref("VS:NONE");
const selectedValuationBand = ref("0.1");
const selectedValuationPickStrategy = ref("VPS:BASELINE");
const selectedBuyCandidateOnly = ref("BC:NONE");
const selectedSwIndustry = ref("");
const selectedEarningsReportType = ref("ERT:ALL");
const selectedSignalAction = ref("SA:ALL");
const selectedRiskLevel = ref("RL:ALL");
const selectedMinSignalScore = ref("");
const selectedMinTargetReturnPct = ref("");
const selectedFeatureDataSource = ref("EDS:ALL");
const selectedFiscalYear = ref("");
const selectedNetprofitGrowth = ref("NPG:ALL");
const swIndustryOptions = ref<Array<{ industry_code: string; industry_name: string }>>([]);
const isPredictiveMode = computed(() => selectedPickingMode.value === "MODE:PREDICTIVE");

function formatDateForApi(input: Date | string | null | undefined): string {
    if (!input) {
        return "";
    }
    if (input instanceof Date) {
        return new Date(input.getTime() - input.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    }
    return String(input).slice(0, 10);
}

function parseDateFromApi(dateText: string): Date {
    const parts = dateText.split("-").map((item) => Number(item));
    if (parts.length === 3 && parts.every((item) => Number.isFinite(item))) {
        return new Date(parts[0], parts[1] - 1, parts[2]);
    }
    return new Date();
}

async function loadLatestTradeDate(freqValue: string) {
    if (!baseURL) {
        return;
    }
    const freqCode = String(freqValue || "D").toUpperCase();
    const res = await axios.get(`${baseURL}/trading/latest-date/${freqCode}/`);
    const latest = res?.data?.latest_trade_date;
    if (!latest) {
        return;
    }
    const dateObj = parseDateFromApi(latest);
    selectedDate.value = dateObj;
    valuationStockPickingStore.setTradeDate(formatDateForApi(dateObj));
}

async function loadSwIndustryOptions() {
    if (!baseURL) {
        return;
    }
    try {
        const res = await axios.get(`${baseURL}/stock-pick-valuation/sw-industries/`, {
            params: { level: "L3" },
        });
        const options = Array.isArray(res?.data?.data) ? res.data.data : [];
        swIndustryOptions.value = options
            .filter((item: any) => item && item.industry_code)
            .map((item: any) => ({
                industry_code: String(item.industry_code),
                industry_name: String(item.industry_name || ""),
            }));
    } catch (_error) {
        swIndustryOptions.value = [];
    }
}

watch(selectedFreq, (newFreq) => {
    loadLatestTradeDate(newFreq);
});

watch(isPredictiveMode, (enabled) => {
    if (enabled && selectedEarningsReportType.value === "ERT:快") {
        selectedEarningsReportType.value = "ERT:ALL";
    }
});

onMounted(() => {
    loadLatestTradeDate(selectedFreq.value);
    loadSwIndustryOptions();
});

watch(
    [
        selectedPickingPeriod,
        selectedFreq,
        selectedDate,
        selectedScope,
        selectedPickingMode,
        selectedValuationMethod,
        selectedValuationStatus,
        selectedValuationBand,
        selectedValuationPickStrategy,
        selectedBuyCandidateOnly,
        selectedSwIndustry,
        selectedEarningsReportType,
        selectedSignalAction,
        selectedRiskLevel,
        selectedMinSignalScore,
        selectedMinTargetReturnPct,
        selectedFeatureDataSource,
        selectedFiscalYear,
        selectedNetprofitGrowth,
    ],
    () => {
        valuationStockPickingStore.setTradeDate(formatDateForApi(selectedDate.value));
        valuationStockPickingStore.setPeriod(selectedPickingPeriod.value);
        valuationStockPickingStore.setFreq(selectedFreq.value);
        valuationStockPickingStore.setScopeParam(selectedScope.value);
        valuationStockPickingStore.setPickingMode(selectedPickingMode.value);
        valuationStockPickingStore.setValuationMethod(selectedValuationMethod.value);
        valuationStockPickingStore.setValuationStatus(selectedValuationStatus.value);
        valuationStockPickingStore.setValuationBandPct(selectedValuationBand.value);
        valuationStockPickingStore.setValuationPickStrategy(selectedValuationPickStrategy.value);
        valuationStockPickingStore.setBuyCandidateOnly(selectedBuyCandidateOnly.value);
        valuationStockPickingStore.setSwIndustry(selectedSwIndustry.value);
        valuationStockPickingStore.setEarningsReportType(selectedEarningsReportType.value);
        valuationStockPickingStore.setSignalAction(selectedSignalAction.value);
        valuationStockPickingStore.setRiskLevel(selectedRiskLevel.value);
        valuationStockPickingStore.setMinSignalScore(selectedMinSignalScore.value);
        valuationStockPickingStore.setMinTargetReturnPct(selectedMinTargetReturnPct.value);
        valuationStockPickingStore.setFeatureDataSource(selectedFeatureDataSource.value);
        valuationStockPickingStore.setFiscalYear(selectedFiscalYear.value);
        valuationStockPickingStore.setNetprofitGrowth(selectedNetprofitGrowth.value);
    }
);

defineOptions({
    name: "ValuationStockPickingFilter",
});
</script>

<style scoped></style>
