<template>
    <div class="grid-content ep-bg-purple">
        <el-affix :offset="75">
            <el-card style="max-width: 480px">
                <template #header>
                    <el-row align="middle" justify="space-between">
                        <el-col :span="4">
                            <span style="font-size: 14px;">财务</span>
                        </el-col>
                        <el-col :span="20" style="text-align: right;">
                            <el-radio-group v-model="tushareApi" size="small" @change="handleFinButtonChange">
                                <el-radio-button label="CYQ_PERF">筹</el-radio-button>
                                <el-radio-button label="INDICATOR">销</el-radio-button>
                                <el-radio-button label="PROFIT_FORECAST">预</el-radio-button>
                                <el-radio-button label="HOLD">基</el-radio-button>
                            </el-radio-group>
                        </el-col>
                    </el-row>
                </template>
                <el-row :gutter="10" size="small"><el-col :span="24"><span style="font-size: medium;">{{
                    stockTradeStore.name + ' | ' +
                            stockTradeStore.tsCode }}</span></el-col></el-row>
                <el-scrollbar max-height="275px">

                    <el-row :gutter="10" size="small">
                        <el-col :span="24" v-for="(label, key) in keyNameMap" :key="key" style="margin-bottom: 2px;">

                            <el-row>
                                <el-col :span="14">
                                    <span style="font-weight: bold; font-size: small;">{{ label }}</span>
                                </el-col>
                                <el-col :span="10" style="text-align: right;">
                                    <span style="font-size: small;">
                                        {{ finData && finData[key] !== undefined ? finData[key] : '-' }}
                                    </span>
                                </el-col>
                            </el-row>
                        </el-col>
                    </el-row>
                </el-scrollbar>
                <template #footer></template>
            </el-card>
        </el-affix>
    </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
// element plus
import { ElAffix, ElCard, ElRadioGroup, ElRadioButton, ElRow, ElCol, ElScrollbar } from 'element-plus'
import { useStockTradeStore } from '../stores/stockTradeStore'

const tushareApi = ref('CYQ_PERF')

import axios from 'axios'
import { inject } from 'vue'
const baseURL = inject('baseURL')

const stockTradeStore = useStockTradeStore()
const tsCode = stockTradeStore.tsCode || '000001.SZ'
const finData = ref<any>(null)
const keyNameMap = ref<Record<string, string>>({})

interface IChipsData {
    ts_code: string
    trade_date: string
    his_low: number
    his_high: number
    cost_5pct: number
    cost_15pct: number
    cost_50pct: number
    cost_85pct: number
    cost_95pct: number
    weight_avg: number
    winner_rate: number
}

const chipsKeyNameMap: Record<string, string> = {
    // ts_code: '代码',
    trade_date: '交易日期',
    weight_avg: '加权均价',
    winner_rate: '收盘获利(%)',
    cost_95pct: '95%成本',
    cost_85pct: '85%成本',
    cost_50pct: '50%成本',
    cost_15pct: '15%成本',
    cost_5pct: '5%成本',
    his_high: '历史最高',
    his_low: '历史最低',
}

interface IFinIndicatorData {
    ts_code: string
    end_date: string
    eps: number
    total_revenue_ps: number
    revenue_ps: number
    undist_profit_ps: number
    gross_margin: number
    ar_turn: number
    ebit: number
    ebitda: number
    fcff: number
    interestdebt: number
    netprofit_margin: number
    grossprofit_margin: number
    roe: number
    roe_dt: number
    debt_to_assets: number
    ca_to_assets: number
    or_yoy: number
    q_op_qoq: number
    netprofit_yoy: number
    dt_netprofit_yoy: number
}

const fIndicatorKeyNameMap: Record<string, string> = {
    // ts_code: '代码',
    end_date: '报告期',
    eps: '收益(股)',
    total_revenue_ps: '营总收(股)',
    revenue_ps: '营收(股)',
    undist_profit_ps: '未分配利润(股)',
    gross_margin: '毛利(百万)',
    ar_turn: '应收周转率(%)',
    ebit: 'EBIT(百万)',
    ebitda: 'EBITDA(百万)',
    fcff: 'FCF(百万)',
    interestdebt: '带息债务(百万)',
    netprofit_margin: '净利率(%)',
    grossprofit_margin: '毛利率(%)',
    roe: 'ROE(%)',
    roe_dt: 'ROE(扣非,%)',
    debt_to_assets: '负债率(%)',
    ca_to_assets: '流资占比(%)',
    or_yoy: '营收同比(%)',
    q_op_qoq: '利润环比(%)',
    netprofit_yoy: '净利同比(%)',
    dt_netprofit_yoy: '扣非净利同比(%)',
}


function handleFinButtonChange(value: string | number | boolean | undefined) {
    tushareApi.value = String(value ?? 'CYQ_PERF')
    // You can add additional logic here if needed, such as fetching new data
    console.log('Finance button changed to:', value)
}

async function fetchFinanceData(tsCode: string, tushareApi = 'CYQ_PERF'): Promise<any | null> {
    try {
        const response = await axios.get(`${baseURL}/tushare/${tsCode}/${tushareApi}/`)
        if (tushareApi === 'INDICATOR') {
            console.log('Indicator Key Name Map:', fIndicatorKeyNameMap)
            return {
                data: response.data.data as IFinIndicatorData,
                keyNameMap: fIndicatorKeyNameMap
            }
        } else {
            console.log('Chips Key Name Map:', chipsKeyNameMap)
            return {
                data: response.data.data as IChipsData,
                keyNameMap: chipsKeyNameMap
            }
        }
    } catch (error) {
        console.error('Failed to fetch finance data:', error)
        return null
    }
}

// Watch for changes in tsCode and fetch finance data
import { watch } from 'vue'
watch([() => stockTradeStore.tsCode, () => tushareApi.value], ([newTsCode, newApi]) => {
    fetchFinanceData(newTsCode, newApi).then((data) => {
        if (data) {
            finData.value = data.data
            keyNameMap.value = data.keyNameMap || {}
            console.log('Finance data:', data)
        } else {
            console.log('No finance data available.')
        }
    })
})

// Initial fetch
onMounted(() => {
    fetchFinanceData(tsCode, tushareApi.value).then((data) => {
        if (data) {
            finData.value = data.data
            keyNameMap.value = data.keyNameMap || {}
            console.log('Finance data:', data)
        } else {
            console.log('No finance data available.')
        }
    })
})

</script>

<style scoped>
.stocks-relevant {
    padding: 1rem;
}
</style>