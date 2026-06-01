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
                    <el-button
                        size="small"
                        type="primary"
                        plain
                        style="margin-left: 8px;"
                        @click="openJobConfigDialog"
                    >
                        Job策略配置
                    </el-button>
                    <span style="margin-left: 8px; color: #909399;">一键应用最近回测表现最优的筛选参数。</span>
                </el-col>
            </el-row>

            <template v-if="quickConditionExpanded">
            <el-row :gutter="2" style="font-size: x-small; margin-bottom: 6px; color: gray;">
                <el-col :span="isPredictiveMode ? 8 : 12">
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
                <el-col v-if="isPredictiveMode" :span="8">
                    <span style="display: inline-block; vertical-align: middle;">操作建议：</span>
                    <el-select v-model="selectedSignalAction" size="small" style="width: 170px; margin-left: 8px;" placeholder="操作建议">
                        <el-option label="全部" value="SA:ALL" />
                        <el-option label="BUY" value="SA:BUY" />
                        <el-option label="HOLD" value="SA:HOLD" />
                        <el-option label="SELL_PART" value="SA:SELL_PART" />
                        <el-option label="SELL" value="SA:SELL" />
                    </el-select>
                </el-col>
                <el-col :span="isPredictiveMode ? 8 : 12">
                    <span style="display: inline-block; vertical-align: middle;">风险级别：</span>
                    <el-select
                        v-model="selectedRiskLevel"
                        multiple
                        collapse-tags
                        collapse-tags-tooltip
                        clearable
                        size="small"
                        :style="{ width: isPredictiveMode ? '220px' : '180px', marginLeft: '8px' }"
                        placeholder="全部"
                    >
                        <el-option label="LOW" value="LOW" />
                        <el-option label="MEDIUM" value="MEDIUM" />
                        <el-option label="HIGH" value="HIGH" />
                    </el-select>
                </el-col>
            </el-row>

            <el-row v-if="isPredictiveMode" :gutter="2" style="font-size: x-small; margin-bottom: 6px; color: gray;">
                <el-col :span="8">
                    <span style="display: inline-block; vertical-align: middle;">最低收益：</span>
                    <el-input v-model="selectedMinTargetReturnPct" size="small" placeholder="如 15" style="width: 130px; margin-left: 8px;" clearable>
                        <template #append>%</template>
                    </el-input>
                </el-col>
                <el-col :span="8">
                    <span style="display: inline-block; vertical-align: middle;">数据来源：</span>
                    <el-select v-model="selectedFeatureDataSource" size="small" style="width: 130px; margin-left: 8px;" placeholder="来源">
                        <el-option label="全部" value="EDS:ALL" />
                        <el-option label="live" value="EDS:live_db" />
                        <el-option label="fallback" value="EDS:dataset_fallback" />
                        <el-option label="fusion" value="EDS:fusion" />
                    </el-select>
                </el-col>
                <el-col :span="8">
                    <span style="display: inline-block; vertical-align: middle;">财报年份：</span>
                    <el-input v-model="selectedFiscalYear" size="small" placeholder="如 2024" style="width: 110px; margin-left: 8px;" clearable />
                </el-col>
            </el-row>

            <el-row :gutter="2" style="font-size: x-small; margin-bottom: 6px; color: gray;">
                <el-col :span="12">
                    <span style="display: inline-block; vertical-align: middle;">净利增速：</span>
                    <el-select v-model="selectedNetprofitGrowth" size="small" style="width: 180px; margin-left: 8px;" placeholder="净利增速">
                        <el-option label="全部" value="NPG:ALL" />
                        <el-option label="中增长(>10%)" value="NPG:MEDIUM" />
                        <el-option label="高增长(>=20%)" value="NPG:HIGH" />
                    </el-select>
                </el-col>
                <el-col :span="12">
                    <span style="display: inline-block; vertical-align: middle;">最低分数：</span>
                    <el-input v-model="selectedMinSignalScore" size="small" placeholder="如 60" style="width: 190px; margin-left: 8px;" clearable />
                </el-col>
            </el-row>

            <el-row :gutter="2" style="font-size: x-small; margin-bottom: 6px; color: gray;">
                <el-col :span="12">
                    <span style="display: inline-block; vertical-align: middle;">估值状态：</span>
                    <el-radio-group v-model="selectedValuationStatus" size="small" style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="VS:NONE">不筛选</el-radio-button>
                        <el-radio-button label="VS:UNDER">低估</el-radio-button>
                        <el-radio-button label="VS:FAIR">正常</el-radio-button>
                        <el-radio-button label="VS:OVER">高估</el-radio-button>
                    </el-radio-group>
                </el-col>
                <el-col :span="12">
                    <span style="display: inline-block; vertical-align: middle;">买入候选：</span>
                    <el-radio-group v-model="selectedBuyCandidateOnly" size="small" style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="BC:NONE">全部</el-radio-button>
                        <el-radio-button label="BC:ONLY">仅可买</el-radio-button>
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
            </template>

            <el-dialog v-model="jobConfigDialogVisible" title="周度Job选股策略配置" width="860px">
                <el-form label-width="190px" size="small">
                    <el-divider content-position="left">公共参数</el-divider>
                    <div style="margin: -4px 0 10px; color: #909399; font-size: 12px;">
                        下面按作用范围拆分：共享参数、传统估值专用参数、预测估值专用参数。
                    </div>

                    <el-divider content-position="left">共享参数（传统 + 预测）</el-divider>
                    <el-row :gutter="12">
                        <el-col :span="12">
                            <el-form-item label="范围(scope)">
                                <el-input v-model="jobConfigDraft.job.scope" placeholder="如 60,00,30,68" />
                            </el-form-item>
                        </el-col>
                        <el-col :span="12">
                            <el-form-item label="频率(freq)">
                                <el-select v-model="jobConfigDraft.job.freq" style="width: 100%;">
                                    <el-option label="D" value="D" />
                                    <el-option label="W" value="W" />
                                    <el-option label="M" value="M" />
                                </el-select>
                            </el-form-item>
                        </el-col>
                    </el-row>
                    <el-row :gutter="12">
                        <el-col :span="12">
                            <el-form-item label="估值带宽(valuation_band_pct)">
                                <el-input v-model="jobConfigDraft.job.valuation_band_pct" />
                            </el-form-item>
                        </el-col>
                        <el-col :span="12">
                            <el-form-item label="候选策略(pick_strategy)">
                                <el-select v-model="jobConfigDraft.job.pick_strategy" style="width: 100%;">
                                    <el-option label="adaptive" value="adaptive" />
                                    <el-option label="baseline" value="baseline" />
                                    <el-option label="best_score" value="best_score" />
                                    <el-option label="first" value="first" />
                                    <el-option label="min" value="min" />
                                    <el-option label="max" value="max" />
                                    <el-option label="median" value="median" />
                                </el-select>
                            </el-form-item>
                        </el-col>
                    </el-row>

                    <el-divider content-position="left">传统估值专用</el-divider>
                    <div style="margin: -4px 0 10px; color: #909399; font-size: 12px;">
                        当前周度传统筛选仅使用“仅可买”，风险级别和最小分数仅作展示。
                    </div>
                    <el-row :gutter="12">
                        <el-col :span="12">
                            <el-form-item label="仅可买(buy_candidate_only)">
                                <el-radio-group v-model="jobConfigDraft.job.buy_candidate_only" style="width: 100%;">
                                    <el-radio-button label="BC:NONE">全部</el-radio-button>
                                    <el-radio-button label="BC:ONLY">仅可买</el-radio-button>
                                </el-radio-group>
                            </el-form-item>
                        </el-col>
                        <el-col :span="12">
                            <el-form-item label="传统风险级别(只读，当前不参与筛选)">
                                <el-input :model-value="Array.isArray(jobConfigDraft.quick_profiles.traditional.risk_level) ? jobConfigDraft.quick_profiles.traditional.risk_level.join('/') : (jobConfigDraft.quick_profiles.traditional.risk_level || '-')" disabled />
                            </el-form-item>
                        </el-col>
                    </el-row>

                    <el-divider content-position="left">预测估值专用</el-divider>
                    <el-row :gutter="12">
                        <el-col :span="12">
                            <el-form-item label="预测最小收益(%)">
                                <el-input v-model="jobConfigDraft.job.min_target_return_pct" />
                            </el-form-item>
                        </el-col>
                        <el-col :span="12">
                            <el-form-item label="预测最小信号分">
                                <el-input v-model="jobConfigDraft.job.min_signal_score" />
                            </el-form-item>
                        </el-col>
                    </el-row>

                    <el-divider content-position="left">传统估值参数</el-divider>
                    <div style="margin: -4px 0 10px; color: #909399; font-size: 12px;">
                        该区块仅展示传统估值的固定参数，不在 Job 运行参数里调整。
                    </div>
                    <el-row :gutter="12">
                        <el-col :span="24">
                            <div style="padding: 12px 14px; border: 1px solid #ebeef5; border-radius: 8px; background: #fafafa; color: #303133; line-height: 1.8;">
                                <div>报告口径：{{ jobConfigDraft.quick_profiles.traditional.earnings_report_type }}</div>
                                <div>估值状态：{{ jobConfigDraft.quick_profiles.traditional.valuation_status }}</div>

                    <el-row :gutter="12">
                        <el-col :span="12">
                            <el-form-item label="风险级别">
                                <el-checkbox-group v-model="predictiveRiskLevelValues" class="inline-checkbox-group">
                                    <el-checkbox-button label="LOW">LOW</el-checkbox-button>
                                    <el-checkbox-button label="MEDIUM">MEDIUM</el-checkbox-button>
                                    <el-checkbox-button label="HIGH">HIGH</el-checkbox-button>
                                </el-checkbox-group>
                            </el-form-item>
                        </el-col>
                    </el-row>

                    <el-divider content-position="left">传统估值参数</el-divider>
                    <div style="margin: -4px 0 10px; color: #909399; font-size: 12px;">
                        该区块仅展示传统估值的固定参数，不在 Job 运行参数里调整。
                    </div>
                    <el-row :gutter="12">
                        <el-col :span="24">
                            <div style="padding: 12px 14px; border: 1px solid #ebeef5; border-radius: 8px; background: #fafafa; color: #303133; line-height: 1.8;">
                                <div>报告口径：{{ jobConfigDraft.quick_profiles.traditional.earnings_report_type }}</div>
                                <div>估值状态：{{ jobConfigDraft.quick_profiles.traditional.valuation_status }}</div>
                                <div>最小分数（仅展示）：{{ jobConfigDraft.quick_profiles.traditional.min_signal_score }}</div>
                                <div>风险级别：{{ Array.isArray(jobConfigDraft.quick_profiles.traditional.risk_level) ? jobConfigDraft.quick_profiles.traditional.risk_level.join("/") : jobConfigDraft.quick_profiles.traditional.risk_level }}</div>
                            </div>
                        </el-col>
                    </el-row>

                    <el-divider content-position="left">预测估值参数</el-divider>
                    <div style="margin: -4px 0 10px; color: #909399; font-size: 12px;">
                        该区块仅展示预测估值的固定参数，不在 Job 运行参数里调整。
                    </div>
                    <el-row :gutter="12">
                        <el-col :span="24">
                            <div style="padding: 12px 14px; border: 1px solid #ebeef5; border-radius: 8px; background: #fafafa; color: #303133; line-height: 1.8;">
                                <div>报告口径：{{ jobConfigDraft.quick_profiles.predictive.earnings_report_type }}</div>
                                <div>操作建议：{{ jobConfigDraft.quick_profiles.predictive.signal_action }}</div>
                                <div>最小分数：{{ jobConfigDraft.quick_profiles.predictive.min_signal_score }}</div>
                                <div>风险级别：{{ Array.isArray(jobConfigDraft.quick_profiles.predictive.risk_level) ? jobConfigDraft.quick_profiles.predictive.risk_level.join("/") : jobConfigDraft.quick_profiles.predictive.risk_level }}</div>
                                <div>最低收益：{{ jobConfigDraft.quick_profiles.predictive.min_target_return_pct || "-" }}</div>
                                <div>数据来源：{{ jobConfigDraft.quick_profiles.predictive.feature_data_source }}</div>
                                <div>财报年份：{{ jobConfigDraft.quick_profiles.predictive.fiscal_year || "-" }}</div>
                                <div>净利增速：{{ jobConfigDraft.quick_profiles.predictive.netprofit_growth }}</div>
                            </div>
                        </el-col>
                    </el-row>
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
const selectedRiskLevel = ref<string[]>([]);
const selectedMinSignalScore = ref("");
const selectedMinTargetReturnPct = ref("");
const selectedFeatureDataSource = ref("EDS:ALL");
const selectedFiscalYear = ref("");
const selectedNetprofitGrowth = ref("NPG:ALL");
const selectedQuickStrategy = ref("");
const quickConditionExpanded = ref(true);
const swIndustryOptions = ref<Array<{ industry_code: string; industry_name: string }>>([]);
const jobConfigDialogVisible = ref(false);
const jobConfigSaving = ref(false);
const defaultJobConfig = {
    job: {
        scope: "60,00,30,68",
        freq: "D",
        valuation_band_pct: "0.1",
        pick_strategy: "baseline",
        min_target_return_pct: "0",
        min_signal_score: "85",
        buy_candidate_only: "BC:ONLY",
    },
    quick_profiles: {
        traditional: {
            earnings_report_type: "ERT:ALL",
            valuation_status: "VS:UNDER",
            min_signal_score: "85",
            signal_action: "SA:ALL",
            min_target_return_pct: "",
            feature_data_source: "EDS:ALL",
            fiscal_year: "",
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
            fiscal_year: "",
            valuation_method: "VM:RECOMMENDED",
            valuation_band_pct: "0.1",
            valuation_pick_strategy: "VPS:BASELINE",
            buy_candidate_only: "BC:ONLY",
            netprofit_growth: "NPG:ALL",
            risk_level: ["LOW", "MEDIUM"],
            picking_mode: "MODE:PREDICTIVE",
        },
    },
};
const jobConfigDraft = ref<any>(JSON.parse(JSON.stringify(defaultJobConfig)));
const quickProfileConfig = ref<any>(JSON.parse(JSON.stringify(defaultJobConfig.quick_profiles)));
const isPredictiveMode = computed(() => selectedPickingMode.value === "MODE:PREDICTIVE");
const resultDateMarks = computed(() => valuationStockPickingStore.resultDateMarks);

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
    const profile = quickProfileConfig.value?.traditional || defaultJobConfig.quick_profiles.traditional;
    selectedPickingMode.value = profile.picking_mode || "MODE:BASELINE";
    selectedEarningsReportType.value = profile.earnings_report_type || "ERT:ALL";
    selectedRiskLevel.value = Array.isArray(profile.risk_level) ? profile.risk_level : ["LOW", "MEDIUM"];
    selectedNetprofitGrowth.value = profile.netprofit_growth || "NPG:HIGH";
    selectedMinSignalScore.value = String(profile.min_signal_score ?? "85");
    selectedSignalAction.value = profile.signal_action || "SA:ALL";
    selectedMinTargetReturnPct.value = String(profile.min_target_return_pct ?? "");
    selectedFeatureDataSource.value = profile.feature_data_source || "EDS:ALL";
    selectedFiscalYear.value = String(profile.fiscal_year ?? "");
    selectedValuationMethod.value = profile.valuation_method || "VM:RECOMMENDED";
    selectedValuationStatus.value = profile.valuation_status || "VS:UNDER";
    selectedValuationBand.value = String(profile.valuation_band_pct ?? "0.1");
    selectedValuationPickStrategy.value = profile.valuation_pick_strategy || "VPS:BASELINE";
    selectedBuyCandidateOnly.value = profile.buy_candidate_only || "BC:ONLY";
    selectedQuickStrategy.value = "traditional";
}

function applyPredictiveQuickStrategy() {
    const profile = quickProfileConfig.value?.predictive || defaultJobConfig.quick_profiles.predictive;
    selectedPickingMode.value = profile.picking_mode || "MODE:PREDICTIVE";
    selectedEarningsReportType.value = profile.earnings_report_type || "ERT:FUSION";
    selectedSignalAction.value = profile.signal_action || "SA:BUY";
    selectedRiskLevel.value = Array.isArray(profile.risk_level) ? profile.risk_level : ["LOW", "MEDIUM"];
    selectedMinSignalScore.value = String(profile.min_signal_score ?? "85");
    selectedMinTargetReturnPct.value = String(profile.min_target_return_pct ?? "");
    selectedFeatureDataSource.value = profile.feature_data_source || "EDS:ALL";
    selectedFiscalYear.value = String(profile.fiscal_year ?? "");
    selectedNetprofitGrowth.value = profile.netprofit_growth || "NPG:ALL";
    selectedValuationMethod.value = profile.valuation_method || "VM:RECOMMENDED";
    selectedValuationStatus.value = profile.valuation_status || "VS:UNDER";
    selectedValuationBand.value = String(profile.valuation_band_pct ?? "0.1");
    selectedValuationPickStrategy.value = profile.valuation_pick_strategy || "VPS:BASELINE";
    selectedBuyCandidateOnly.value = profile.buy_candidate_only || "BC:ONLY";
    selectedQuickStrategy.value = "predictive";
}

async function loadJobStrategyConfig() {
    if (!baseURL) {
        return;
    }
    try {
        const res = await axios.get(`${baseURL}/stock-pick-valuation/job-strategy-config/`);
        const data = res?.data?.data || {};
        const merged = {
            ...defaultJobConfig,
            ...data,
            job: {
                ...defaultJobConfig.job,
                ...(data.job || {}),
            },
            quick_profiles: {
                traditional: {
                    ...defaultJobConfig.quick_profiles.traditional,
                    ...(data?.quick_profiles?.traditional || {}),
                },
                predictive: {
                    ...defaultJobConfig.quick_profiles.predictive,
                    ...(data?.quick_profiles?.predictive || {}),
                },
            },
        };
        jobConfigDraft.value = JSON.parse(JSON.stringify(merged));
        quickProfileConfig.value = JSON.parse(JSON.stringify(merged.quick_profiles));
    } catch (_err) {
        jobConfigDraft.value = JSON.parse(JSON.stringify(defaultJobConfig));
        quickProfileConfig.value = JSON.parse(JSON.stringify(defaultJobConfig.quick_profiles));
    }
}

function openJobConfigDialog() {
    jobConfigDialogVisible.value = true;
}

async function saveJobStrategyConfig() {
    if (!baseURL) {
        return;
    }
    jobConfigSaving.value = true;
    try {
        const payload = JSON.parse(JSON.stringify(jobConfigDraft.value));
        const res = await axios.post(`${baseURL}/stock-pick-valuation/job-strategy-config/`, payload);
        const saved = res?.data?.data;
        if (saved?.quick_profiles) {
            quickProfileConfig.value = JSON.parse(JSON.stringify(saved.quick_profiles));
            jobConfigDraft.value = JSON.parse(JSON.stringify(saved));
        }
        jobConfigDialogVisible.value = false;
        ElMessage.success("Job策略配置已保存");
    } catch (_err) {
        ElMessage.error("保存失败，请稍后重试");
    } finally {
        jobConfigSaving.value = false;
    }
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
    return scope
        .replace(/(^|,)00(?=,|$)/g, "$10")
        .replace(/(^|,)30(?=,|$)/g, "$13")
        .replace(/(^|,)68(?=,|$)/g, "$1688");
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
        selectedMinSignalScore.value = String(minSignalScore);
    }

    const featureDataSource = params.get("feature_data_source");
    if (featureDataSource) {
        selectedFeatureDataSource.value = String(featureDataSource);
    }

    const netprofitGrowth = params.get("netprofit_growth");
    if (netprofitGrowth) {
        selectedNetprofitGrowth.value = String(netprofitGrowth);
    }
}

onMounted(async () => {
    await loadLatestTradeDate(selectedFreq.value);
    loadSwIndustryOptions();
    loadJobStrategyConfig();
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
        valuationStockPickingStore.setRiskLevel(selectedRiskLevel.value.join(","));
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
</style>
