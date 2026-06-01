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
    const valuationMethod = ref("VM:PE");
    const valuationStatus = ref("VS:NONE");
    const valuationBandPct = ref("0.1");
    const valuationPickStrategy = ref("VPS:BASELINE");
    const buyCandidateOnly = ref("BC:NONE");
    const swIndustry = ref("");
    const earningsReportType = ref("ERT:ALL");
    const signalAction = ref("SA:ALL");
    const riskLevel = ref("RL:ALL");
    const minSignalScore = ref("");
    const minTargetReturnPct = ref("");
    const featureDataSource = ref("EDS:ALL");
    const fiscalYear = ref("");
    const netprofitGrowth = ref("NPG:ALL");
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
        setPickingResults,
    };
});
