import { ref } from "vue";
import { defineStore } from "pinia";

export type StockPickingParams = {
    tradeDate: string;
    model: string;
    modelVersion?: string;
    topBottom: string;
    period: string;
    freq: string;
    techParam: string;
    statParam: string;
    scopeParam: string;
    maParam: string;
    volumeChgParam: string;
    statPeriodParam: string;
    chgPctParam: string;
    costParam: string;
    results: {
        ts_code: string;
        name: string;
        close_qfq: number;
        pct_change_qfq: number;
    }[];
};

export const useStockPickingStore = defineStore("stockPicking", () => {
    const tradeDate = ref(new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10));
    const model = ref("xgb");
    const modelVersion = ref("1.2");
    const topBottom = ref("TB:NONE");
    const period = ref("60");
    const freq = ref("D");
    const techParam = ref("TECH:NONE");
    const statParam = ref("STAT:NONE");
    const scopeParam = ref("SCOPE:NONE");
    const maParam = ref("MA:NONE");
    const costParam = ref("COST:NONE");
    const volumeChgParam = ref("FEAT_DIFF:NONE");
    const statPeriodParam = ref("60");
    const chgPctParam = ref("CHG_PCT:NONE");
    const pickingResults = ref<StockPickingParams["results"]>([]);


    function setTradeDate(value: string) {
        tradeDate.value = value;
    }

    function setModel(value: string) {
        model.value = value;
    }

    function setModelVersion(value: string) {
        modelVersion.value = value;
    }
    function setTopBottom(value: string) {
        topBottom.value = value;
    }

    function setPeriod(value: string) {
        period.value = value;
    }

    function setFreq(value: string) {
        freq.value = value;
    }

    function setTechParam(value: string) {
        techParam.value = value;
    }

    function setStatParam(value: string) {
        statParam.value = value;
    }

    function setScopeParam(value: string) {
        scopeParam.value = value;
    }

    function setMaParam(value: string) {
        maParam.value = value;
    }

    function setCostParam(value: string) {
        costParam.value = value;
    }

    function setVolumeChgParam(value: string) {
        volumeChgParam.value = value;
    }

    function setStatPeriod(value: string) {
        statPeriodParam.value = value;
    }

    function setChgPctParam(value: string) {
        chgPctParam.value = value;
    }

    function setPickingResults(value: StockPickingParams["results"] | undefined) {
        pickingResults.value = Array.isArray(value) ? value : [];
    }

    function setParams(params: Partial<StockPickingParams>) {
        if (params.tradeDate !== undefined) tradeDate.value = params.tradeDate;
        if (params.model !== undefined) model.value = params.model;
        if (params.modelVersion !== undefined) modelVersion.value = params.modelVersion;
        if (params.period !== undefined) period.value = params.period;
        if (params.topBottom !== undefined) topBottom.value = params.topBottom;
        if (params.freq !== undefined) freq.value = params.freq;
        if (params.techParam !== undefined) techParam.value = params.techParam;
        if (params.statParam !== undefined) statParam.value = params.statParam;
        if (params.scopeParam !== undefined) scopeParam.value = params.scopeParam;
        if (params.maParam !== undefined) maParam.value = params.maParam;
        if (params.costParam !== undefined) costParam.value = params.costParam;
        if (params.volumeChgParam !== undefined) volumeChgParam.value = params.volumeChgParam;
        if (params.statPeriodParam !== undefined) statPeriodParam.value = params.statPeriodParam;
        if (params.chgPctParam !== undefined) chgPctParam.value = params.chgPctParam;
    }
    return {
        tradeDate,
        model,
        modelVersion,
        period,
        topBottom,
        freq,
        techParam,
        statParam,
        scopeParam,
        maParam,
        costParam,
        volumeChgParam,
        statPeriodParam,
        chgPctParam,
        pickingResults,
        setStatPeriod,
        setTradeDate,
        setModel,
        setModelVersion,
        setPeriod,
        setTopBottom,
        setFreq,
        setTechParam,
        setStatParam,
        setScopeParam,
        setMaParam,
        setCostParam,
        setVolumeChgParam,
        setPickingResults,    // 添加这个方法
        setChgPctParam,
        setParams,
    };
}); 