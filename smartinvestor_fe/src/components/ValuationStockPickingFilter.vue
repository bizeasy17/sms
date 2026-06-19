<template>
    <el-card>
            <el-row :gutter="2" style="font-size: x-small; margin-bottom: 12px;color: gray;">
                <el-col :span="9">
                    <span style="display: flex; align-items: center;">
                        <span style="margin-right: 6px;">选股日期：</span>
                        <el-date-picker v-model="selectedDate" type="date" placeholder="选股日期" :size="'small'" style="margin-right: 6px;">
                            <template #default="cell">
                                <div class="pick-date-cell" :class="{ 'pick-date-cell--marked': hasResultMark(cell) }">
                                    <span>{{ cell.text }}</span>
                                    <span v-if="hasResultMark(cell)" class="pick-date-cell__dot"></span>
                                </div>
                            </template>
                        </el-date-picker>
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
                <el-col :span="24">
                    <span style="display: inline-block; vertical-align: middle;">快速策略：</span>
                    <el-button
                        size="small"
                        type="danger"
                        :plain="selectedQuickStrategy !== 'traditional'"
                        style="margin-left: 8px;"
                        @click="applyTraditionalQuickStrategy"
                    >
                        传统估值最优策略
                    </el-button>
                    <el-button
                        size="small"
                        type="success"
                        :plain="selectedQuickStrategy !== 'predictive'"
                        style="margin-left: 8px;"
                        @click="applyPredictiveQuickStrategy"
                    >
                        估值预测最优策略
                    </el-button>
                    <el-button
                        size="small"
                        type="info"
                        plain
                        style="margin-left: 8px;"
                        @click="quickConditionExpanded = !quickConditionExpanded"
                    >
                        {{ quickConditionExpanded ? "收起条件" : "展开条件" }}
                    </el-button>
                    <span style="margin-left: 8px; color: #909399;">一键应用最近回测表现最优的筛选参数。</span>
                </el-col>
            </el-row>

            <template v-if="quickConditionExpanded">
                <div class="filter-grid">
                    <div class="filter-item filter-item--u8 filter-item--order-1">
                        <span class="filter-label">口径：</span>
                        <el-radio-group v-model="selectedEarningsReportType" size="small" class="filter-control filter-radio-group">
                            <el-radio-button label="ERT:ALL">综合</el-radio-button>
                            <el-radio-button label="ERT:Q1">Q1</el-radio-button>
                            <el-radio-button label="ERT:H1">H1</el-radio-button>
                            <el-radio-button label="ERT:Q3">Q3</el-radio-button>
                            <el-radio-button label="ERT:FY">FY</el-radio-button>
                            <el-radio-button v-if="!isPredictiveMode" label="ERT:快">快报</el-radio-button>
                            <el-radio-button v-if="isPredictiveMode" label="ERT:FUSION">Fusion</el-radio-button>
                        </el-radio-group>
                    </div>

                    <div v-if="isPredictiveMode" class="filter-item">
                        <span class="filter-label">操作建议：</span>
                        <el-select v-model="selectedSignalAction" size="small" class="filter-control" placeholder="操作建议">
                            <el-option label="全部" value="SA:ALL" />
                            <el-option label="BUY" value="SA:BUY" />
                            <el-option label="HOLD" value="SA:HOLD" />
                            <el-option label="SELL_PART" value="SA:SELL_PART" />
                            <el-option label="SELL" value="SA:SELL" />
                        </el-select>
                    </div>

                    <div class="filter-item">
                        <span class="filter-label">风险级别：</span>
                        <el-select
                            v-model="selectedRiskLevel"
                            multiple
                            collapse-tags
                            collapse-tags-tooltip
                            clearable
                            size="small"
                            class="filter-control"
                            placeholder="全部"
                        >
                            <el-option label="LOW" value="LOW" />
                            <el-option label="MEDIUM" value="MEDIUM" />
                            <el-option label="HIGH" value="HIGH" />
                        </el-select>
                    </div>

                    <div class="filter-item">
                        <span class="filter-label">最低分数：</span>
                        <el-input-number
                            v-model="selectedMinSignalScore"
                            :min="0"
                            :max="100"
                            :step="1"
                            controls-position="right"
                            class="filter-control"
                        />
                    </div>

                    <div v-if="isPredictiveMode" class="filter-item">
                        <span class="filter-label">最低收益：</span>
                        <el-input v-model="selectedMinTargetReturnPct" size="small" placeholder="如 15" class="filter-control" clearable>
                            <template #append>%</template>
                        </el-input>
                    </div>

                    <div v-if="isPredictiveMode" class="filter-item">
                        <span class="filter-label">数据来源：</span>
                        <el-select v-model="selectedFeatureDataSource" size="small" class="filter-control" placeholder="来源">
                            <el-option label="全部" value="EDS:ALL" />
                            <el-option label="live" value="EDS:live_db" />
                            <el-option label="fallback" value="EDS:dataset_fallback" />
                            <el-option label="fusion" value="EDS:fusion" />
                        </el-select>
                    </div>

                    <div class="filter-item">
                        <span class="filter-label">优先策略：</span>
                        <el-select v-model="selectedPriorityPolicy" size="small" class="filter-control" placeholder="优先策略">
                            <el-option label="低估高分优先" value="score_desc" />
                            <el-option label="折价空间优先" value="deep_discount_first" />
                            <el-option label="组合目标折价优先" value="target_discount_first" />
                            <el-option label="高股价优先" value="high_price_first" />
                            <el-option label="低股价优先" value="low_price_first" />
                            <el-option label="低风险高分优先" value="low_risk_high_score" />
                        </el-select>
                    </div>

                    <div class="filter-item">
                        <span class="filter-label">买入候选：</span>
                        <el-radio-group v-model="selectedBuyCandidateOnly" size="small" class="filter-control filter-radio-group">
                            <el-radio-button label="BC:NONE">全部</el-radio-button>
                            <el-radio-button label="BC:ONLY">仅可买</el-radio-button>
                        </el-radio-group>
                    </div>

                    <div class="filter-item filter-item--span3">
                        <span class="filter-label">SW行业：</span>
                        <el-select
                            v-model="selectedSwIndustry"
                            size="small"
                            filterable
                            clearable
                            placeholder="不筛选"
                            class="filter-control"
                        >
                            <el-option
                                v-for="item in swIndustryOptions"
                                :key="item.industry_code"
                                :label="`${item.industry_code} | ${item.industry_name}`"
                                :value="item.industry_code"
                            />
                        </el-select>
                    </div>

                    <div class="filter-item">
                        <span class="filter-label">估值带宽：</span>
                        <el-input-number
                            v-model="selectedValuationBandNumber"
                            :min="0.01"
                            :max="0.5"
                            :step="0.01"
                            :precision="2"
                            controls-position="right"
                            class="filter-control"
                        />
                    </div>

                    <div class="filter-divider" aria-hidden="true"></div>

                    <div class="filter-item">
                        <span class="filter-label">净利YoY最小值：</span>
                        <el-input-number v-model="selectedMinNetprofitYoy" :min="-100" :max="300" :step="1" class="filter-control" :disabled="!selectedApplyFinancialFilters" />
                    </div>

                    <div class="filter-item">
                        <span class="filter-label">EBIT YoY最小值：</span>
                        <el-input-number v-model="selectedMinEbitYoy" :min="-100" :max="300" :step="1" class="filter-control" :disabled="!selectedApplyFinancialFilters" />
                    </div>

                    <div class="filter-item">
                        <span class="filter-label">上一年净利不为负：</span>
                        <el-switch v-model="selectedRequirePositivePrevNetprofit" class="filter-control filter-control--switch" :disabled="!selectedApplyFinancialFilters" />
                    </div>

                    <div class="filter-item">
                        <span class="filter-label">上一年EBIT不为负：</span>
                        <el-switch v-model="selectedRequirePositivePrevEbit" class="filter-control filter-control--switch" :disabled="!selectedApplyFinancialFilters" />
                    </div>

                    <div class="filter-item filter-item--full filter-item--hint">
                        <div class="filter-note-row">
                            <span class="filter-note-switch">
                                <span class="filter-note-switch__label">应用财务条件</span>
                                <el-switch v-model="selectedApplyFinancialFilters" />
                            </span>
                            <span class="filter-note">
                                说明：财务条件采用二阶段过滤。先按估值/风险筛出候选，再对候选应用净利YoY、EBITYoY和上一年净利/EBIT条件。
                            </span>
                        </div>
                    </div>

                    <div class="filter-divider" aria-hidden="true"></div>

                    <div class="filter-item">
                        <span class="filter-label">应用资金流入条件：</span>
                        <el-switch v-model="selectedApplyMoneyflowFilters" class="filter-control filter-control--switch" />
                    </div>

                    <div class="filter-item">
                        <span class="filter-label">净流入天数窗口：</span>
                        <el-select
                            v-model="selectedMoneyflowNetInflowDaysWindow"
                            size="small"
                            class="filter-control"
                            :disabled="!selectedApplyMoneyflowFilters"
                            placeholder="净流入窗口"
                        >
                            <el-option label="5日" value="5" />
                            <el-option label="10日" value="10" />
                            <el-option label="15日" value="15" />
                            <el-option label="30日" value="30" />
                            <el-option label="60日" value="60" />
                        </el-select>
                    </div>

                    <div class="filter-item filter-item--full filter-item--hint">
                        <span class="filter-note">
                            说明：开启后按“最近N日累计净流入 &gt; 0”执行二次过滤（口径B）。
                        </span>
                    </div>

                    <div class="filter-item filter-item--u8 filter-item--order-2">
                        <span class="filter-label">状态：</span>
                        <el-radio-group v-model="selectedValuationStatus" size="small" class="filter-control filter-radio-group">
                            <el-radio-button label="VS:NONE">不筛选</el-radio-button>
                            <el-radio-button label="VS:UNDER">低估</el-radio-button>
                            <el-radio-button label="VS:FAIR">正常</el-radio-button>
                            <el-radio-button label="VS:OVER">高估</el-radio-button>
                        </el-radio-group>
                    </div>

                    <div class="filter-item filter-item--u8 filter-item--order-3">
                        <span class="filter-label">范围：</span>
                        <el-radio-group v-model="selectedScope" size="small" class="filter-control filter-radio-group">
                            <el-radio-button label="SCOPE:NONE" value="SCOPE:NONE">请选择</el-radio-button>
                            <el-radio-button label="WATCHLIST" value="WATCHLIST">自</el-radio-button>
                            <el-radio-button label="60" value="60">沪</el-radio-button>
                            <el-radio-button label="00" value="00">深</el-radio-button>
                            <el-radio-button label="30" value="30">创</el-radio-button>
                            <el-radio-button label="68" value="68">科</el-radio-button>
                        </el-radio-group>
                    </div>
                </div>
            </template>

    </el-card>
</template>

<script setup lang="ts">
import { computed, ref, watch, onMounted, inject } from "vue";
import axios from "axios";
import { ElRow, ElCol, ElCard, ElRadioGroup, ElRadioButton, ElDatePicker, ElSelect, ElOption, ElInput, ElInputNumber, ElButton, ElSwitch } from "element-plus";
import { useValuationStockPickingStore } from "../stores/valuationStockPickingStore";

const valuationStockPickingStore = useValuationStockPickingStore();
const baseURL = inject<string>("baseURL", "");

const selectedPickingPeriod = ref("60");
const selectedFreq = ref("D");
const selectedDate = ref(new Date());
const selectedScope = ref("SCOPE:NONE");
const selectedPickingMode = ref("MODE:BASELINE");
const selectedValuationMethod = ref("VM:RECOMMENDED");
const selectedValuationStatus = ref("VS:UNDER");
const selectedValuationBand = ref("0.1");
const selectedValuationBandNumber = computed<number>({
    get: () => {
        const value = Number(selectedValuationBand.value);
        if (!Number.isFinite(value)) return 0.1;
        return Math.min(0.5, Math.max(0.01, Number(value.toFixed(2))));
    },
    set: (value: number) => {
        if (!Number.isFinite(value)) {
            selectedValuationBand.value = "0.1";
            return;
        }
        const normalized = Math.min(0.5, Math.max(0.01, value));
        selectedValuationBand.value = String(Number(normalized.toFixed(2)));
    },
});
const selectedValuationPickStrategy = ref("VPS:BASELINE");
const selectedMinNetprofitYoy = ref<number | null>(null);
const selectedMinEbitYoy = ref<number | null>(null);
const selectedRequirePositivePrevNetprofit = ref(true);
const selectedRequirePositivePrevEbit = ref(true);
const selectedApplyFinancialFilters = ref(false);
const selectedApplyMoneyflowFilters = ref(false);
const selectedMoneyflowNetInflowDaysWindow = ref("10");
const selectedPriorityPolicy = ref("score_desc");
const selectedBuyCandidateOnly = ref("BC:ONLY");
const selectedSwIndustry = ref("");
const selectedEarningsReportType = ref("ERT:ALL");
const selectedSignalAction = ref("SA:ALL");
const selectedRiskLevel = ref<string[]>(["LOW", "MEDIUM"]);
const selectedMinSignalScore = ref<number | null>(85);
const selectedMinTargetReturnPct = ref("");
const selectedFeatureDataSource = ref("EDS:ALL");
const selectedQuickStrategy = ref("");
const quickConditionExpanded = ref(true);
const swIndustryOptions = ref<Array<{ industry_code: string; industry_name: string }>>([]);
const defaultQuickProfiles = {
    traditional: {
        earnings_report_type: "ERT:ALL",
        valuation_status: "VS:UNDER",
        min_signal_score: "85",
        signal_action: "SA:ALL",
        min_target_return_pct: "",
        feature_data_source: "EDS:ALL",
        valuation_method: "VM:RECOMMENDED",
        valuation_band_pct: "0.1",
        valuation_pick_strategy: "VPS:BASELINE",
        buy_candidate_only: "BC:ONLY",
        netprofit_growth: "NPG:HIGH",
        risk_level: ["LOW", "MEDIUM"],
        picking_mode: "MODE:BASELINE",
    },
    predictive: {
        earnings_report_type: "ERT:FUSION",
        valuation_status: "VS:UNDER",
        min_signal_score: "85",
        signal_action: "SA:BUY",
        min_target_return_pct: "",
        feature_data_source: "EDS:ALL",
        valuation_method: "VM:RECOMMENDED",
        valuation_band_pct: "0.1",
        valuation_pick_strategy: "VPS:BASELINE",
        buy_candidate_only: "BC:ONLY",
        netprofit_growth: "NPG:ALL",
        risk_level: ["LOW", "MEDIUM"],
        picking_mode: "MODE:PREDICTIVE",
    },
};
const quickProfileConfig = ref<any>(JSON.parse(JSON.stringify(defaultQuickProfiles)));
const isPredictiveMode = computed(() => selectedPickingMode.value === "MODE:PREDICTIVE");
const resultDateMarks = computed(() => valuationStockPickingStore.resultDateMarks);

function splitMultiValue(raw: unknown, fallback: string[] = []): string[] {
    if (Array.isArray(raw)) {
        return raw.map((item) => String(item).trim()).filter((item) => !!item);
    }
    if (typeof raw === "string") {
        const parsed = raw.split(",").map((item) => item.trim()).filter((item) => !!item);
        return parsed.length ? parsed : fallback;
    }
    return fallback;
}

function firstOfMulti(raw: unknown, fallback: string): string {
    const values = splitMultiValue(raw);
    return values.length ? values[0] : fallback;
}

function parseNumberOrNull(raw: unknown): number | null {
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
}

function parseBooleanFromQuery(raw: unknown, fallback: boolean): boolean {
    const normalized = String(raw ?? "").trim().toLowerCase();
    if (!normalized) return fallback;
    if (["1", "true", "yes", "y", "on"].includes(normalized)) return true;
    if (["0", "false", "no", "n", "off"].includes(normalized)) return false;
    return fallback;
}

function getCellDateKey(cell: any): string {
    if (!cell || cell.type !== "normal") {
        return "";
    }
    const dayjsObj = cell.dayjs;
    if (!dayjsObj || typeof dayjsObj.format !== "function") {
        return "";
    }
    return dayjsObj.format("YYYY-MM-DD");
}

function hasResultMark(cell: any): boolean {
    const dateKey = getCellDateKey(cell);
    return Boolean(dateKey && resultDateMarks.value[dateKey]);
}

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

function applyTraditionalQuickStrategy() {
    const profile = quickProfileConfig.value?.traditional || defaultQuickProfiles.traditional;
    selectedPickingMode.value = profile.picking_mode || "MODE:BASELINE";
    selectedEarningsReportType.value = firstOfMulti(profile.earnings_report_type, "ERT:ALL");
    selectedRiskLevel.value = splitMultiValue(profile.risk_level, ["LOW", "MEDIUM"]);
    const score = Number(profile.min_signal_score ?? 85);
    selectedMinSignalScore.value = Number.isFinite(score) ? score : 85;
    selectedSignalAction.value = firstOfMulti(profile.signal_action, "SA:ALL");
    selectedMinTargetReturnPct.value = String(profile.min_target_return_pct ?? "");
    selectedFeatureDataSource.value = profile.feature_data_source || "EDS:ALL";
    selectedValuationMethod.value = profile.valuation_method || "VM:RECOMMENDED";
    selectedValuationStatus.value = firstOfMulti(profile.valuation_status, "VS:UNDER");
    selectedValuationBand.value = String(profile.valuation_band_pct ?? "0.1");
    selectedValuationPickStrategy.value = profile.valuation_pick_strategy || "VPS:BASELINE";
    selectedMinNetprofitYoy.value = profile.min_netprofit_yoy === null || profile.min_netprofit_yoy === undefined ? null : Number(profile.min_netprofit_yoy);
    selectedMinEbitYoy.value = profile.min_ebit_yoy === null || profile.min_ebit_yoy === undefined ? null : Number(profile.min_ebit_yoy);
    selectedRequirePositivePrevNetprofit.value = Boolean(profile.require_positive_prev_netprofit ?? true);
    selectedRequirePositivePrevEbit.value = Boolean(profile.require_positive_prev_ebit ?? true);
    selectedApplyFinancialFilters.value = Boolean(profile.apply_financial_filters ?? false);
    selectedApplyMoneyflowFilters.value = Boolean(profile.apply_moneyflow_filters ?? false);
    selectedMoneyflowNetInflowDaysWindow.value = String(profile.moneyflow_net_inflow_days_window ?? "10");
    selectedPriorityPolicy.value = String(profile.priority_policy ?? "score_desc");
    selectedBuyCandidateOnly.value = profile.buy_candidate_only || "BC:ONLY";
    selectedQuickStrategy.value = "traditional";
}

function applyPredictiveQuickStrategy() {
    const profile = quickProfileConfig.value?.predictive || defaultQuickProfiles.predictive;
    selectedPickingMode.value = profile.picking_mode || "MODE:PREDICTIVE";
    selectedEarningsReportType.value = firstOfMulti(profile.earnings_report_type, "ERT:FUSION");
    selectedSignalAction.value = firstOfMulti(profile.signal_action, "SA:BUY");
    selectedRiskLevel.value = splitMultiValue(profile.risk_level, ["LOW", "MEDIUM"]);
    const score = Number(profile.min_signal_score ?? 85);
    selectedMinSignalScore.value = Number.isFinite(score) ? score : 85;
    selectedMinTargetReturnPct.value = String(profile.min_target_return_pct ?? "");
    selectedFeatureDataSource.value = profile.feature_data_source || "EDS:ALL";
    selectedValuationMethod.value = profile.valuation_method || "VM:RECOMMENDED";
    selectedValuationStatus.value = profile.valuation_status || "VS:UNDER";
    selectedValuationBand.value = String(profile.valuation_band_pct ?? "0.1");
    selectedValuationPickStrategy.value = profile.valuation_pick_strategy || "VPS:BASELINE";
    selectedMinNetprofitYoy.value = profile.min_netprofit_yoy === null || profile.min_netprofit_yoy === undefined ? null : Number(profile.min_netprofit_yoy);
    selectedMinEbitYoy.value = profile.min_ebit_yoy === null || profile.min_ebit_yoy === undefined ? null : Number(profile.min_ebit_yoy);
    selectedRequirePositivePrevNetprofit.value = Boolean(profile.require_positive_prev_netprofit ?? true);
    selectedRequirePositivePrevEbit.value = Boolean(profile.require_positive_prev_ebit ?? true);
    selectedApplyFinancialFilters.value = Boolean(profile.apply_financial_filters ?? false);
    selectedApplyMoneyflowFilters.value = Boolean(profile.apply_moneyflow_filters ?? false);
    selectedMoneyflowNetInflowDaysWindow.value = String(profile.moneyflow_net_inflow_days_window ?? "10");
    selectedPriorityPolicy.value = String(profile.priority_policy ?? "score_desc");
    selectedBuyCandidateOnly.value = profile.buy_candidate_only || "BC:ONLY";
    selectedQuickStrategy.value = "predictive";
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

function normalizeScopeFromBacktest(rawScope: string): string {
    const scope = String(rawScope || "").trim().toUpperCase();
    if (!scope) {
        return "SCOPE:NONE";
    }
    if (scope === "WATCHLIST" || scope === "SCOPE:WATCHLIST") {
        return "WATCHLIST";
    }
    if (scope === "ALL") {
        return "60,0,3,688";
    }
    if (scope.startsWith("SCOPE:")) {
        return scope;
    }
    const mapped = scope
        .split(",")
        .map((item) => item.trim())
        .filter((item) => !!item)
        .map((item) => {
            if (item === "0") return "00";
            if (item === "3") return "30";
            if (item === "688") return "68";
            return item;
        });
    return mapped.join(",");
}

function parseRiskLevels(rawRiskLevel: string): string[] {
    const values = String(rawRiskLevel || "")
        .split(",")
        .map((item) => item.trim().toUpperCase())
        .filter((item) => item === "LOW" || item === "MEDIUM" || item === "HIGH");
    return Array.from(new Set(values));
}

function applyBacktestPrefillFromQuery() {
    const params = new URLSearchParams(window.location.search || "");
    if (params.get("source") !== "backtest_execute") {
        return;
    }

    const tradeDate = String(params.get("trade_date") || "").trim();
    if (/^\d{4}-\d{2}-\d{2}$/.test(tradeDate)) {
        selectedDate.value = parseDateFromApi(tradeDate);
    }

    const scope = params.get("scope");
    if (scope) {
        selectedScope.value = normalizeScopeFromBacktest(scope);
    }

    const pickingMode = params.get("picking_mode");
    if (pickingMode) {
        selectedPickingMode.value = String(pickingMode);
    }

    const valuationMethod = params.get("valuation_method");
    if (valuationMethod) {
        selectedValuationMethod.value = String(valuationMethod);
    }

    const valuationStatus = params.get("valuation_status");
    if (valuationStatus) {
        selectedValuationStatus.value = String(valuationStatus);
    }

    const valuationBand = params.get("valuation_band_pct");
    if (valuationBand) {
        selectedValuationBand.value = String(valuationBand);
    }

    const valuationPickStrategy = params.get("valuation_pick_strategy");
    if (valuationPickStrategy) {
        selectedValuationPickStrategy.value = String(valuationPickStrategy);
    }

    const minNetprofitYoy = params.get("min_netprofit_yoy");
    if (minNetprofitYoy !== null) {
        selectedMinNetprofitYoy.value = parseNumberOrNull(minNetprofitYoy);
    }

    const minEbitYoy = params.get("min_ebit_yoy");
    if (minEbitYoy !== null) {
        selectedMinEbitYoy.value = parseNumberOrNull(minEbitYoy);
    }

    const requirePositivePrevNetprofit = params.get("require_positive_prev_netprofit");
    if (requirePositivePrevNetprofit !== null) {
        selectedRequirePositivePrevNetprofit.value = parseBooleanFromQuery(requirePositivePrevNetprofit, true);
    }

    const requirePositivePrevEbit = params.get("require_positive_prev_ebit");
    if (requirePositivePrevEbit !== null) {
        selectedRequirePositivePrevEbit.value = parseBooleanFromQuery(requirePositivePrevEbit, true);
    }

    const applyFinancialFilters = params.get("apply_financial_filters");
    if (applyFinancialFilters !== null) {
        selectedApplyFinancialFilters.value = parseBooleanFromQuery(applyFinancialFilters, false);
    }

    const applyMoneyflowFilters = params.get("apply_moneyflow_filters");
    if (applyMoneyflowFilters !== null) {
        selectedApplyMoneyflowFilters.value = parseBooleanFromQuery(applyMoneyflowFilters, false);
    }

    const moneyflowWindow = params.get("moneyflow_net_inflow_days_window");
    if (moneyflowWindow) {
        const normalized = String(moneyflowWindow).trim();
        if (["5", "10", "15", "30", "60"].includes(normalized)) {
            selectedMoneyflowNetInflowDaysWindow.value = normalized;
        }
    }

    const priorityPolicy = params.get("priority_policy");
    if (priorityPolicy) {
        selectedPriorityPolicy.value = String(priorityPolicy);
    }

    const buyCandidateOnly = params.get("buy_candidate_only");
    if (buyCandidateOnly) {
        selectedBuyCandidateOnly.value = String(buyCandidateOnly);
    }

    const earningsReportType = params.get("earnings_report_type");
    if (earningsReportType) {
        selectedEarningsReportType.value = String(earningsReportType);
    }

    const signalAction = params.get("signal_action");
    if (signalAction) {
        selectedSignalAction.value = String(signalAction);
    }

    const riskLevel = params.get("risk_level");
    if (riskLevel !== null) {
        selectedRiskLevel.value = parseRiskLevels(riskLevel);
    }

    const minSignalScore = params.get("min_signal_score");
    if (minSignalScore !== null) {
        const parsed = Number(minSignalScore);
        selectedMinSignalScore.value = Number.isFinite(parsed) ? parsed : selectedMinSignalScore.value;
    }

    const featureDataSource = params.get("feature_data_source");
    if (featureDataSource) {
        selectedFeatureDataSource.value = String(featureDataSource);
    }

}

onMounted(async () => {
    await loadLatestTradeDate(selectedFreq.value);
    loadSwIndustryOptions();
    applyBacktestPrefillFromQuery();
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
        selectedMinNetprofitYoy,
        selectedMinEbitYoy,
        selectedRequirePositivePrevNetprofit,
        selectedRequirePositivePrevEbit,
        selectedApplyFinancialFilters,
        selectedApplyMoneyflowFilters,
        selectedMoneyflowNetInflowDaysWindow,
        selectedPriorityPolicy,
        selectedBuyCandidateOnly,
        selectedSwIndustry,
        selectedEarningsReportType,
        selectedSignalAction,
        selectedRiskLevel,
        selectedMinSignalScore,
        selectedMinTargetReturnPct,
        selectedFeatureDataSource,
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
        valuationStockPickingStore.setMinNetprofitYoy(selectedMinNetprofitYoy.value === null ? "" : String(selectedMinNetprofitYoy.value));
        valuationStockPickingStore.setMinEbitYoy(selectedMinEbitYoy.value === null ? "" : String(selectedMinEbitYoy.value));
        valuationStockPickingStore.setRequirePositivePrevNetprofit(selectedRequirePositivePrevNetprofit.value);
        valuationStockPickingStore.setRequirePositivePrevEbit(selectedRequirePositivePrevEbit.value);
        valuationStockPickingStore.setApplyFinancialFilters(selectedApplyFinancialFilters.value);
        valuationStockPickingStore.setApplyMoneyflowFilters(selectedApplyMoneyflowFilters.value);
        valuationStockPickingStore.setMoneyflowNetInflowDaysWindow(selectedMoneyflowNetInflowDaysWindow.value);
        valuationStockPickingStore.setPriorityPolicy(selectedPriorityPolicy.value);
        valuationStockPickingStore.setBuyCandidateOnly(selectedBuyCandidateOnly.value);
        valuationStockPickingStore.setSwIndustry(selectedSwIndustry.value);
        valuationStockPickingStore.setEarningsReportType(selectedEarningsReportType.value);
        valuationStockPickingStore.setSignalAction(selectedSignalAction.value);
        valuationStockPickingStore.setRiskLevel(selectedRiskLevel.value.join(","));
        valuationStockPickingStore.setMinSignalScore(
            selectedMinSignalScore.value === null ? "" : String(selectedMinSignalScore.value)
        );
        valuationStockPickingStore.setMinTargetReturnPct(selectedMinTargetReturnPct.value);
        valuationStockPickingStore.setFeatureDataSource(selectedFeatureDataSource.value);
    },
    { immediate: true }
);

defineOptions({
    name: "ValuationStockPickingFilter",
});
</script>

<style scoped>
.pick-date-cell {
    position: relative;
    width: 24px;
    height: 24px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 12px;
}

.pick-date-cell--marked {
    color: #c8161d;
    font-weight: 600;
}

.pick-date-cell__dot {
    position: absolute;
    right: -2px;
    top: -2px;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #c8161d;
}

.filter-grid {
    display: grid;
    grid-template-columns: repeat(24, minmax(0, 1fr));
    gap: 8px 12px;
    font-size: x-small;
    color: gray;
    margin-bottom: 6px;
}

.filter-item {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    min-height: 32px;
    gap: 8px;
    grid-column: span 6;
    order: 10;
}

.filter-label {
    width: 92px;
    min-width: 92px;
    text-align: left;
    color: gray;
}

.filter-control {
    flex: 1;
    min-width: 0;
}

.filter-control--switch {
    flex: 0 0 auto;
}

.filter-item--u8 {
    grid-column: span 8;
}

.filter-item--span3 {
    grid-column: span 12;
}

.filter-item--full {
    grid-column: 1 / -1;
}

.filter-item--hint {
    align-items: flex-start;
    min-height: 0;
}

.filter-note {
    color: #909399;
    line-height: 1.5;
}

.filter-note-row {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 12px;
}

.filter-note-switch {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    flex: 0 0 auto;
    color: #606266;
}

.filter-note-switch__label {
    white-space: nowrap;
}

.filter-item--order-1 {
    order: 1;
}

.filter-item--order-2 {
    order: 2;
}

.filter-item--order-3 {
    order: 3;
}

.filter-divider {
    grid-column: 1 / -1;
    border-top: 1px solid #e5e7eb;
    margin: 2px 0;
    min-height: 0;
    order: 10;
}

:deep(.filter-radio-group) {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
}

@media (max-width: 900px) {
    .filter-grid {
        grid-template-columns: repeat(12, minmax(0, 1fr));
    }

    .filter-item {
        grid-column: span 6;
    }

    .filter-item--u8 {
        grid-column: span 12;
    }

    .filter-item--span3 {
        grid-column: span 12;
    }
}

@media (max-width: 640px) {
    .filter-grid {
        grid-template-columns: 1fr;
    }

    .filter-item,
    .filter-item--u8,
    .filter-item--span3 {
        grid-column: span 1;
    }

    .filter-label {
        width: 84px;
        min-width: 84px;
    }

    .filter-note-row {
        align-items: flex-start;
        flex-direction: column;
    }
}
</style>
