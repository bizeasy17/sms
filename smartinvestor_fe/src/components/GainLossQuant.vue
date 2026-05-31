<template>
    <!-- Main content goes here -->
    <template v-for="stat in gainLossStat" :key="stat.top_or_bottom">
        <el-card style="margin-bottom: 16px;">
            <div slot="header" class="clearfix" style="border-bottom: 1px solid #ebeef5; padding-bottom: 2px;">
                <span style="font-weight: bold;font-size: 14px;">{{ stat.top_or_bottom === 'T' ? '顶' : '底' }} {{ ' ('+ period + '天一个周期)' }}</span>
            </div>

            <el-row v-for="(label, key) in {
                pct_gain_1p: '涨1',
                pct_gain_2p: '涨2',
                pct_gain_3p: '涨3',
                pct_gain_5p: '涨5',
                pct_loss_1p: '跌1',
                pct_loss_2p: '跌2',
                pct_loss_3p: '跌3',
                pct_loss_5p: '跌5'
            }" :key="key" style="margin-bottom: 2px;">
                <el-col :span="6">
                    <span style="font-weight: bold; font-size: small;">{{ label }}</span>
                </el-col>
                <el-col :span="18" style="text-align: right;">
                    <span
                        :style="{
                            fontWeight: 'normal',
                            fontSize: 'small',
                            color: key.startsWith('pct_gain') ? 'red' : key.startsWith('pct_loss') ? 'green' : ''
                        }"
                    >
                        {{ stat[key] + '%' }}
                    </span>
                </el-col>
            </el-row>
        </el-card>
    </template>
    <el-footer>
        <!-- Footer content -->
        <div style="text-align: right; width: 100%;">
            <el-text size="small">© {{ new Date().getFullYear() }} GHarvest</el-text>
        </div>
    </el-footer>
</template>

<script setup>
// Add your script logic here if needed
import { ElMain, ElFooter, ElText, ElCard, ElRow, ElCol } from 'element-plus'
import axios from 'axios'
import { inject, ref, watch, onMounted } from 'vue'
import { useStockTradeStore } from '../stores/stockTradeStore'

const baseURL = inject('baseURL')
const stockTradeStore = useStockTradeStore()
const period = ref(34)
const gainLossStat = ref([])

/**
 * Fetch gain/loss statistics for a stock.
 * @param {string} ts_code - Stock code.
 * @param {string} freq - Frequency (e.g., 'D').
 * @param {number} period - Period (e.g., 34).
 */
async function fetchGainLossStatistic(ts_code, freq, period) {
    const url = `${baseURL}/stocks/${ts_code}/gain-loss-statistic/${freq}/${period}/`
    const response = await axios.get(url)
    try {
        gainLossStat.value = response.data.data
    } catch (error) {
        console.error('Error fetching gain/loss statistic:', error)
    }
}

watch(
    () => [stockTradeStore.tsCode, stockTradeStore.freq],
    async ([newTsCode, newFreq]) => {
        if (stockTradeStore.freq === 'W') {
            period.value = 144
        } else if (stockTradeStore.freq === 'M') {
            period.value = 610
        }
        const data = await fetchGainLossStatistic(newTsCode, newFreq, period.value)
        console.log(data)
    }
)

onMounted(async () => {
    const data = await fetchGainLossStatistic(stockTradeStore.tsCode, stockTradeStore.freq, period)
    console.log(data)
})
</script>

<style scoped>
/* Add your component styles here */
</style>