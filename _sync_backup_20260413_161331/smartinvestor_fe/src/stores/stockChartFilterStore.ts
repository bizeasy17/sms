import { ref } from "vue";
import { defineStore } from "pinia";

export type StockChartFilterParams = {
    topBottomSwitch: boolean;
    model: string;
    period: string;
    freq: string;
};

export const useStockChartFilterStore = defineStore("stockChartFilter", () => {
    const topBottomSwitch = ref(false);
    const model = ref("xgb");
    const period = ref("60");
    const freq = ref("D");

    function setTopBottomSwitch(value: boolean) {
        topBottomSwitch.value = value;
    }

    function setModel(value: string) {
        model.value = value;
    }

    function setPeriod(value: string) {
        period.value = value;
    }

    function setFreq(value: string) {
        freq.value = value;
    }

    function setParams(params: Partial<StockChartFilterParams>) {
        if (params.topBottomSwitch !== undefined) topBottomSwitch.value = params.topBottomSwitch;
        if (params.model !== undefined) model.value = params.model;
        if (params.period !== undefined) period.value = params.period;
        if (params.freq !== undefined) freq.value = params.freq;
    }

    return {
        topBottomSwitch,
        model,
        period,
        freq,
        setTopBottomSwitch,
        setModel,
        setPeriod,
        setFreq,
        setParams,
    };
});