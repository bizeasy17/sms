import { defineStore } from 'pinia';
import { ref } from 'vue';

export const useStockTradeStore = defineStore('tsCode', () => {
    const tsCode = ref<string>('000001.SH');
    const name = ref<string>('上证指数');
    const website = ref<string>('');
    const open = ref<number>(0);
    const close = ref<number>(0);
    const high = ref<number>(0);
    const low = ref<number>(0);
    const pctChg = ref<number>(0.00);
    const freq = ref<string>('D')

    function setTsCode(code: string) {
        tsCode.value = code;
    }

    function clearTsCode() {
        tsCode.value = '';
    }

    function setName(newName: string) {
        name.value = newName;
    }

    function clearName() {
        name.value = '';
    }

    function setWebsite(newWebsite: string) {
        website.value = newWebsite;
    }

    function setOpen(newOpen: number) {
        open.value = newOpen;
    }

    function setClose(newClose: number) {
        close.value = newClose;
    }

    function setHigh(newHigh: number) {
        high.value = newHigh;
    }

    function setLow(newLow: number) {
        low.value = newLow;
    }

    function setPctChg(newPctChg: number) {
        pctChg.value = newPctChg;
    }

    function setFreq(newFreq: string) {
        freq.value = newFreq;
    }

    return {
        tsCode,
        setTsCode,
        clearTsCode,
        name,
        setName,
        clearName,
        website,
        setWebsite,
        open,
        setOpen,
        close,
        setClose,
        high,
        setHigh,
        low,
        setLow,
        pctChg,
        setPctChg,
        freq,
        setFreq
    };
});