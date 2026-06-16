import { ref } from "vue";
import { defineStore } from "pinia";

export type ValuationStockPickingParams = {
    tradeDate: string;
    model: string;
    modelVersion?: string;
    period: string;
    freq: string;
    scopeParam: string;
    pickingMode: string;
    valuationMethod: string;
    valuationStatus: string;
    valuationBandPct: string;
    valuationPickStrategy: string;
    valuationVariant: string;
    riskVariantPolicy: string;
    minNetprofitYoy: string;
    minEbitYoy: string;
    requirePositivePrevNetprofit: boolean;
    requirePositivePrevEbit: boolean;
    applyFinancialFilters: boolean;
    applyMoneyflowFilters: boolean;
    moneyflowNetInflowDaysWindow: string;
    financialFilterMode: string;
    priorityPolicy: string;
    buyCandidateOnly: string;
    swIndustry: string;
    earningsReportType: string;
    signalAction: string;
    riskLevel: string;
    minSignalScore: string;
    minTargetReturnPct: string;
    featureDataSource: string;
    fiscalYear: string;
    netprofitGrowth: string;
    resultDateMarks: Record<string, boolean>;
    results: {
        ts_code: string;
        name: string;
        close_qfq: number;
        pct_change_qfq: number;
        sw_l3_code?: string;
        sw_l3_name?: string;
    }[];
};

export const useValuationStockPickingStore = defineStore("valuationStockPicking", () => {
    const tradeDate = ref(new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10));
    const model = ref("xgb");
    const modelVersion = ref("1.2");
    const period = ref("60");
    const freq = ref("D");
    const scopeParam = ref("SCOPE:NONE");
    const pickingMode = ref("MODE:BASELINE");
    const valuationMethod = ref("VM:RECOMMENDED");
    const valuationStatus = ref("VS:UNDER");
    const valuationBandPct = ref("0.1");
    const valuationPickStrategy = ref("VPS:BASELINE");
    const valuationVariant = ref("");
    const riskVariantPolicy = ref("any");
    const minNetprofitYoy = ref("");
    const minEbitYoy = ref("");
    const requirePositivePrevNetprofit = ref(true);
    const requirePositivePrevEbit = ref(true);
    const applyFinancialFilters = ref(false);
    const applyMoneyflowFilters = ref(false);
    const moneyflowNetInflowDaysWindow = ref("10");
    const financialFilterMode = ref("all");
    const priorityPolicy = ref("score_desc");
    const buyCandidateOnly = ref("BC:ONLY");
    const swIndustry = ref("");
    const earningsReportType = ref("ERT:ALL");
    const signalAction = ref("SA:ALL");
    const riskLevel = ref("LOW,MEDIUM");
    const minSignalScore = ref("85");
    const minTargetReturnPct = ref("");
    const featureDataSource = ref("EDS:ALL");
    const fiscalYear = ref("");
    const netprofitGrowth = ref("NPG:ALL");
    const resultDateMarks = ref<Record<string, boolean>>({});
    const pickingResults = ref<ValuationStockPickingParams["results"]>([]);

    function setTradeDate(value: string) { tradeDate.value = value; }
    function setModel(value: string) { model.value = value; }
    function setModelVersion(value: string) { modelVersion.value = value; }
    function setPeriod(value: string) { period.value = value; }
    function setFreq(value: string) { freq.value = value; }
    function setScopeParam(value: string) { scopeParam.value = value; }
    function setPickingMode(value: string) { pickingMode.value = value; }
    function setValuationMethod(value: string) { valuationMethod.value = value; }
    function setValuationStatus(value: string) { valuationStatus.value = value; }
    function setValuationBandPct(value: string) { valuationBandPct.value = value; }
    function setValuationPickStrategy(value: string) { valuationPickStrategy.value = value; }
    function setValuationVariant(value: string) { valuationVariant.value = value; }
    function setRiskVariantPolicy(value: string) { riskVariantPolicy.value = value; }
    function setMinNetprofitYoy(value: string) { minNetprofitYoy.value = value; }
    function setMinEbitYoy(value: string) { minEbitYoy.value = value; }
    function setRequirePositivePrevNetprofit(value: boolean) { requirePositivePrevNetprofit.value = value; }
    function setRequirePositivePrevEbit(value: boolean) { requirePositivePrevEbit.value = value; }
    function setApplyFinancialFilters(value: boolean) { applyFinancialFilters.value = value; }
    function setApplyMoneyflowFilters(value: boolean) { applyMoneyflowFilters.value = value; }
    function setMoneyflowNetInflowDaysWindow(value: string) { moneyflowNetInflowDaysWindow.value = value; }
    function setFinancialFilterMode(value: string) { financialFilterMode.value = value; }
    function setPriorityPolicy(value: string) { priorityPolicy.value = value; }
    function setBuyCandidateOnly(value: string) { buyCandidateOnly.value = value; }
    function setSwIndustry(value: string) { swIndustry.value = value; }
    function setEarningsReportType(value: string) { earningsReportType.value = value; }
    function setSignalAction(value: string) { signalAction.value = value; }
    function setRiskLevel(value: string) { riskLevel.value = value; }
    function setMinSignalScore(value: string) { minSignalScore.value = value; }
    function setMinTargetReturnPct(value: string) { minTargetReturnPct.value = value; }
    function setFeatureDataSource(value: string) { featureDataSource.value = value; }
    function setFiscalYear(value: string) { fiscalYear.value = value; }
    function setNetprofitGrowth(value: string) { netprofitGrowth.value = value; }

    function markResultDate(date: string, hasResult: boolean) {
        const key = String(date || "").slice(0, 10);
        if (!key || !hasResult || resultDateMarks.value[key]) {
            return;
        }
        resultDateMarks.value = {
            ...resultDateMarks.value,
            [key]: true,
        };
    }

    function setPickingResults(value: ValuationStockPickingParams["results"] | undefined) {
        pickingResults.value = Array.isArray(value) ? value : [];
    }

    return {
        tradeDate,
        model,
        modelVersion,
        period,
        freq,
        scopeParam,
        pickingMode,
        valuationMethod,
        valuationStatus,
        valuationBandPct,
        valuationPickStrategy,
        valuationVariant,
        riskVariantPolicy,
        minNetprofitYoy,
        minEbitYoy,
        requirePositivePrevNetprofit,
        requirePositivePrevEbit,
        applyFinancialFilters,
        applyMoneyflowFilters,
        moneyflowNetInflowDaysWindow,
        financialFilterMode,
        priorityPolicy,
        buyCandidateOnly,
        swIndustry,
        earningsReportType,
        signalAction,
        riskLevel,
        minSignalScore,
        minTargetReturnPct,
        featureDataSource,
        fiscalYear,
        netprofitGrowth,
        resultDateMarks,
        pickingResults,
        setTradeDate,
        setModel,
        setModelVersion,
        setPeriod,
        setFreq,
        setScopeParam,
        setPickingMode,
        setValuationMethod,
        setValuationStatus,
        setValuationBandPct,
        setValuationPickStrategy,
        setValuationVariant,
        setRiskVariantPolicy,
        setMinNetprofitYoy,
        setMinEbitYoy,
        setRequirePositivePrevNetprofit,
        setRequirePositivePrevEbit,
        setApplyFinancialFilters,
        setApplyMoneyflowFilters,
        setMoneyflowNetInflowDaysWindow,
        setFinancialFilterMode,
        setPriorityPolicy,
        setBuyCandidateOnly,
        setSwIndustry,
        setEarningsReportType,
        setSignalAction,
        setRiskLevel,
        setMinSignalScore,
        setMinTargetReturnPct,
        setFeatureDataSource,
        setFiscalYear,
        setNetprofitGrowth,
        markResultDate,
        setPickingResults,
    };
});
