<template>
    <div class="stock-chart-container">
        <el-row style="width: 100%;">
            <el-col :span="24">
                <slot name="top">
                    <!-- Adj Price Option -->
                    <!-- <el-affix :offset="75"> -->
                    <el-card shadow="always">
                        <el-row :gutter="20">
                            <el-col :span="8">
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <el-link
                                        :href="stockStore.website.startsWith('http') ? stockStore.website : 'https://' + stockStore.website"
                                        target="_blank" type="primary" style="font-size: 12px;">{{ stockStore.name + ' | ' +
                                        stockStore.tsCode }}
                                    </el-link>
                                    <el-check-tag
                                        v-if="displayEmbed"
                                        :checked="isInWatchlist"
                                        @change="toggleWatchlistStatus"
                                        type="danger"
                                    >
                                        <el-text size="small">自</el-text>
                                    </el-check-tag>
                                    <el-check-tag
                                        v-if="displayEmbed"
                                        :checked="isHolding"
                                        @change="toggleHoldingStatus"
                                        type="primary"
                                    >
                                        <el-text size="small">持</el-text>
                                    </el-check-tag>
                                </div>
                            </el-col>
                            <el-col :span="6">

                                <el-radio-group v-model="selectedPeriodEmbed" size="small" style="float: right;"
                                    v-if="displayEmbed">
                                    <el-radio-button label="30">30</el-radio-button>
                                    <el-radio-button label="60">60</el-radio-button>
                                    <el-radio-button label="200">1y</el-radio-button>
                                    <el-radio-button label="400">2y</el-radio-button>
                                </el-radio-group>

                            </el-col>
                            <el-col :span="4">

                                <el-radio-group v-model="selectedFreqEmbed" size="small" style="float: right;"
                                    v-if="displayEmbed">
                                    <el-radio-button label="D">日</el-radio-button>
                                    <el-radio-button label="W">周</el-radio-button>
                                    <el-radio-button label="M">月</el-radio-button>
                                </el-radio-group>

                            </el-col>
                            <el-col :span="6">
                                <el-radio-group v-model="adjPriceOption" size="small" style="float: right;">
                                    <el-radio-button label="qfq">前</el-radio-button>
                                    <el-radio-button label="hfq">后</el-radio-button>
                                    <el-radio-button label="bfq">不</el-radio-button>
                                </el-radio-group>
                            </el-col>
                        </el-row>
                        <el-row :gutter="16">
                            <el-col :span="16">
                                <v-chart ref="trendChartRef" :option="chartTrendOption" autoresize style="height:400px;" />
                            </el-col>
                            <el-col :span="8">
                                <div class="chip-metrics-row">
                                    <span>获胜率: {{ chipWinRateText }}</span>
                                    <span>筹码集中率: {{ chipConcentrationRateText }}</span>
                                    <span>当前价格: {{ chipCurrentPriceText }}</span>
                                </div>
                                <v-chart ref="chipChartRef" :option="chartChipOption" autoresize style="height:400px;" />
                            </el-col>
                        </el-row>
                    </el-card>
                    <!-- </el-affix> -->
                    <!-- Vol Option -->
                    <el-card shadow="always" style="margin-top: 16px;">
                        <el-row>
                            <el-col :span="24">
                                <el-radio-group v-model="volOption" size="small"
                                    style="margin-bottom: 12px; float: right;" @change="onVolOptionChange">
                                    <el-radio-button label="vol">量</el-radio-button>
                                    <el-radio-button label="amount">额</el-radio-button>
                                </el-radio-group>
                            </el-col>
                        </el-row>
                        <v-chart ref="volChartRef" :option="chartVolOption" autoresize style="height:200px;" />
                    </el-card>
                    <!-- Tech Option -->
                    <el-card shadow="always" style="margin-top: 16px;">
                        <el-row>
                            <el-col :span="24">
                                <el-radio-group v-model="techOption" size="small"
                                    style="margin-bottom: 12px; float: right;" @change="onTechOptionChange">
                                    <el-radio-button label="macd">MACD</el-radio-button>
                                    <el-radio-button label="kdj">KDJ</el-radio-button>
                                    <el-radio-button label="rsi">RSI</el-radio-button>
                                    <!-- <el-radio-button label="cci">CCI</el-radio-button> -->
                                </el-radio-group>
                            </el-col>
                        </el-row>
                        <v-chart ref="techChartRef" :option="chartTechOption" autoresize style="height:200px;" />
                    </el-card>
                </slot>
                <slot name="bottom">
                    <el-row :gutter="20" style="margin-top: 16px;">
                        <el-col :span="12">
                            <el-card shadow="always">
                                <v-chart ref="peChartRef" :option="chartPeOption" autoresize style="height:200px;" />
                            </el-card>
                        </el-col>
                        <el-col :span="12">
                            <el-card shadow="always">
                                <v-chart ref="peTTMChartRef" :option="chartPeTTMOption" autoresize
                                    style="height:200px;" />
                            </el-card>
                        </el-col>
                    </el-row>
                    <el-row :gutter="20" style="margin-top: 16px;">
                        <el-col :span="12">
                            <el-card shadow="always">
                                <v-chart ref="psChartRef" :option="chartPsOption" autoresize style="height:200px;" />
                            </el-card>
                        </el-col>
                        <el-col :span="12">
                            <el-card shadow="always">
                                <v-chart ref="psTTMChartRef" :option="chartPsTTMOption" autoresize
                                    style="height:200px;" />
                            </el-card>
                        </el-col>
                    </el-row>
                    <el-row :gutter="20" style="margin-top: 16px;">
                        <el-col :span="12">
                            <el-card shadow="always">
                                <v-chart ref="pbChartRef" :option="chartPbOption" autoresize style="height:200px;" />
                            </el-card>
                        </el-col>
                        <el-col :span="12">
                            <el-card shadow="always">
                                <v-chart ref="volRatioChartRef" :option="chartVolRatioOption" autoresize
                                    style="height:200px;" />
                            </el-card>
                        </el-col>
                    </el-row>
                    <el-row :gutter="20" style="margin-top: 16px;">
                        <el-col :span="12">
                            <el-card shadow="always">
                                <v-chart ref="turnoverChartRef" :option="chartTurnoverOption" autoresize
                                    style="height:200px;" />
                            </el-card>
                        </el-col>
                        <el-col :span="12">
                            <el-card shadow="always">
                                <v-chart ref="turnoverFChartRef" :option="chartTurnoverFOption" autoresize
                                    style="height:200px;" />
                            </el-card>
                        </el-col>
                    </el-row>
                </slot>
            </el-col>
        </el-row>
    </div>

</template>

<script setup>
import { onMounted, onBeforeUnmount, ref, computed, nextTick } from 'vue'
// Element Plus 组件
import { ElAffix, ElCard, ElRadioGroup, ElRadioButton, ElCol, ElRow, ElButton, ElLink, ElCheckTag, ElText, ElMessage } from 'element-plus'
// ECharts 相关 组件
import * as echarts from 'echarts'
import { use } from 'echarts/core'
import VChart from 'vue-echarts'
//导入Canvas渲染器
// import { CanvasRenderer } from 'echarts/renderers'
// import { TitleComponent } from 'echarts/components';
// import { TooltipComponent } from 'echarts/components'

// import the datastore
import { useStockTradeStore } from '../stores/stockTradeStore'
import { useStockChartFilterStore } from '../stores/stockChartFilterStore'

import axios from 'axios'
import { inject } from 'vue'

const baseURL = inject('baseURL')

const stockStore = useStockTradeStore();
const stockChartFilterStore = useStockChartFilterStore();
const isHolding = ref(false);
const isInWatchlist = ref(false);

function toCanonicalTsCode(code) {
    const normalized = String(code || '').trim().toUpperCase();
    if (!normalized) return '';
    if (normalized.includes('.')) return normalized;
    if (!/^\d{6}$/.test(normalized)) return normalized;
    if (normalized.startsWith('6') || normalized.startsWith('5') || normalized.startsWith('9')) return `${normalized}.SH`;
    if (normalized.startsWith('8') || normalized.startsWith('4')) return `${normalized}.BJ`;
    return `${normalized}.SZ`;
}

function buildTsCodeCandidates(code) {
    const normalized = String(code || '').trim().toUpperCase();
    const base = normalized.split('.')[0];
    const candidateSet = new Set();
    if (normalized) candidateSet.add(normalized);
    if (base) candidateSet.add(base);
    const canonical = toCanonicalTsCode(normalized);
    if (canonical) candidateSet.add(canonical);
    if (base && /^\d{6}$/.test(base)) {
        candidateSet.add(`${base}.SH`);
        candidateSet.add(`${base}.SZ`);
        candidateSet.add(`${base}.BJ`);
    }
    return Array.from(candidateSet);
}

async function fetchStockStatus(tsCode) {
    if (!baseURL || !tsCode) {
        return;
    }
    try {
        const candidates = buildTsCodeCandidates(tsCode);
        let fallbackData = null;
        for (const candidate of candidates) {
            const res = await axios.get(`${baseURL}/watchlist/check/${candidate}/`);
            if (!res.data) continue;
            if (!fallbackData) {
                fallbackData = res.data;
            }
            if (res.data.hold_position || res.data.in_watchlist) {
                isHolding.value = !!res.data.hold_position;
                isInWatchlist.value = !!res.data.in_watchlist;
                return;
            }
        }
        if (fallbackData) {
            isHolding.value = !!fallbackData.hold_position;
            isInWatchlist.value = !!fallbackData.in_watchlist;
        }
    } catch (error) {
        console.error('Failed to fetch stock status:', error);
    }
}

async function toggleWatchlistStatus(watchlist) {
    if (!baseURL || !stockStore.tsCode) {
        return;
    }
    try {
        let res;
        if (watchlist) {
            const url = `${baseURL}/watchlist/add/${stockStore.tsCode}/`;
            res = await axios.post(url);
        } else {
            const url = `${baseURL}/watchlist/delete/${stockStore.tsCode}/`;
            res = await axios.put(url);
        }
        if (res.status === 200) {
            isInWatchlist.value = !isInWatchlist.value;
            ElMessage.success(isInWatchlist.value ? '已加入自选股' : '已移除自选股');
        }
    } catch (error) {
        console.error('Failed to toggle watchlist status:', error);
        ElMessage.error('操作失败，请稍后重试');
    }
}

async function toggleHoldingStatus(hold) {
    if (!baseURL || !stockStore.tsCode) {
        return;
    }
    try {
        const url = hold
            ? `${baseURL}/watchlist/hold/${stockStore.tsCode}/`
            : `${baseURL}/watchlist/unhold/${stockStore.tsCode}/`;
        const method = hold ? 'post' : 'put';
        const res = await axios({ url, method });
        if (res.status === 200) {
            isHolding.value = hold;
            isInWatchlist.value = !!res.data.in_watchlist;
            ElMessage.success(isHolding.value ? '已标记为持仓' : '已取消持仓标记');
        }
    } catch (error) {
        console.error('Failed to toggle holding status:', error);
        ElMessage.error('操作失败，请稍后重试');
    }
}

// 注册渲染器
// use([TitleComponent])
// use([CanvasRenderer])
// use([TooltipComponent])

// 创建联动的 group id
const chartGroup = 'stockChartsGroup'
const trendChartRef = ref()
const chipChartRef = ref()
const volChartRef = ref()

const techChartRef = ref()
const peChartRef = ref()
const peTTMChartRef = ref()
const psChartRef = ref()
const psTTMChartRef = ref()
const pbChartRef = ref()
const turnoverChartRef = ref()
const turnoverFChartRef = ref()
const volRatioChartRef = ref()

const volOption = ref('vol')
const techOption = ref('macd')
const adjPriceOption = ref('qfq')

// 处理后的chart数据
const kdata = ref([])
const vol = ref([])
const amount = ref([])
const tradeDates = ref([])
const sl1 = ref([])
const sl2 = ref([])
const tp1 = ref([])
const tp2 = ref([])
const indicData = ref({})
const close = ref([])
const pctChg = ref([])
const chipBars = ref([])
const chipTradeDate = ref('')
const chipCurrentPrice = ref(null)
const chipWinRate = ref(0)
const chipConcentrationRate = ref(0)
const lastHoverIndex = ref(-1)
const chipCache = new Map()

const chipWinRateText = computed(() => `${Number(chipWinRate.value || 0).toFixed(2)}%`)
const chipConcentrationRateText = computed(() => `${Number(chipConcentrationRate.value || 0).toFixed(2)}%`)
const chipCurrentPriceText = computed(() => {
    const v = Number(chipCurrentPrice.value)
    return Number.isFinite(v) ? v.toFixed(2) : '--'
})

// 获取股票数据
const selectedFreqEmbed = ref('D')
const selectedPeriodEmbed = ref('60')
const props = defineProps({
    displayEmbed: {
        type: Boolean,
        default: false
    }
})
const displayEmbed = computed(() => props.displayEmbed)

// 处理json数据的方法
function parseStockChartData(jsonData) {
    const k = []
    const v = []
    const a = []
    const c = []
    const p = []
    const sl_1 = []
    const sl_2 = []
    const tp_1 = []
    const tp_2 = []
    const dates = []
    const indic = {}

    for (const item of jsonData.data) {
        k.push([item.open, item.close, item.low, item.high])
        v.push(item.vol)
        a.push(item.amount)
        c.push(item.close)
        p.push(item.pct_chg)
        sl_1.push(item.sl1)
        sl_2.push(item.sl2)
        tp_1.push(item.tp1)
        tp_2.push(item.tp2)
        dates.push(item.trade_date)
        if (item.indicator) {
            // MACD: macd, macd_dif, macd_dea
            if ('macd' in item.indicator) {
                indic.macd = indic.macd || []
                indic.macd_dif = indic.macd_dif || []
                indic.macd_dea = indic.macd_dea || []
                indic.macd.push(item.indicator.macd.macd ?? null)
                indic.macd_dif.push(item.indicator.macd.macd_dif ?? null)
                indic.macd_dea.push(item.indicator.macd.macd_dea ?? null)
            }
            // KDJ: kdj_k, kdj_d, kdj_j
            if ('kdj' in item.indicator) {
                indic.kdj_k = indic.kdj_k || []
                indic.kdj_d = indic.kdj_d || []
                indic.kdj_j = indic.kdj_j || []
                indic.kdj_k.push(item.indicator.kdj.kdj_k ?? null)
                indic.kdj_d.push(item.indicator.kdj.kdj_d ?? null)
                indic.kdj_j.push(item.indicator.kdj.kdj_j ?? null)
            }
            // RSI: rsi
            if ('rsi' in item.indicator) {
                indic.rsi_6 = indic.rsi_6 || []
                indic.rsi_12 = indic.rsi_12 || []
                indic.rsi_24 = indic.rsi_24 || []
                indic.rsi_6.push(item.indicator.rsi.rsi_6 ?? null)
                indic.rsi_12.push(item.indicator.rsi.rsi_12 ?? null)
                indic.rsi_24.push(item.indicator.rsi.rsi_24 ?? null)
            }
            // CCI: cci
            if ('cci' in item.indicator) {
                indic.cci = indic.cci || []
                indic.cci.push(item.indicator.cci.cci ?? null)
            }
        }
    }

    kdata.value = k
    vol.value = v
    amount.value = a
    close.value = c
    pctChg.value = p
    sl1.value = sl_1
    sl2.value = sl_2
    tp1.value = tp_1
    tp2.value = tp_2
    tradeDates.value = dates
    indicData.value = indic
}

/**
 * Calculate moving average for a given data array and window size.
 * @param {number[]} data - Array of numbers (e.g., close prices).
 * @param {number} window - Window size for moving average.
 * @returns {number[]} - Array of moving average values (same length as data, with nulls for insufficient data).
 */
function calcMovingAvg(data, window) {
    if (!Array.isArray(data) || window <= 0) return []
    const result = []
    for (let i = 0; i < data.length; i++) {
        if (i < window - 1) {
            result.push(null)
        } else {
            const sum = data.slice(i - window + 1, i + 1).reduce((a, b) => a + b, 0)
            result.push(Number((sum / window).toFixed(4)))
        }
    }
    return result
}

// 配置三个图表的 option，并设置 group
const chartTrendOption = ref({
    title: {
        text: 'K线趋势',
        left: 'left',
        textStyle: {
            fontSize: 14
        }
    },
    tooltip: {
        trigger: 'axis',
        confine: true,
        padding: [4, 8],
        textStyle: {
            fontSize: 12
        },
        axisPointer: {
            type: 'cross'
        },
        formatter: function (params) {
            // params is an array of series data at the hovered point
            // Only show the candlestick (K线) info
            const kline = params.find(item => item.seriesType === 'candlestick')
            if (!kline) return ''
            // ECharts candlestick expects [open, close, low, high]
            // But sometimes data is [open, close, low, high], so destructure accordingly
            const [idx, open, close, low, high] = kline.data
            // If you see wrong values, log kline.data for debugging
            // console.log('kline.data', kline.data)
            let pctChange = ''
            if (kline.dataIndex > 0 && kline.seriesIndex === 0) {
                // Find previous close from the same series' data
                const seriesData = this && this.seriesData ? this.seriesData : null
                let prevClose = null
                if (seriesData && Array.isArray(seriesData[kline.dataIndex - 1])) {
                    prevClose = seriesData[kline.dataIndex - 1][1]
                } else if (Array.isArray(chartTrendOption.value.series[0].data[kline.dataIndex - 1])) {
                    prevClose = chartTrendOption.value.series[0].data[kline.dataIndex - 1][1]
                }
                if (typeof prevClose === 'number' && prevClose !== 0) {
                    pctChange = ((close - prevClose) / prevClose * 100).toFixed(2) + '%'
                }
            }
            return `
            <div>
                <strong>${kline.axisValue}</strong><br/>
                开盘: ${open}<br/>
                收盘: ${close}<br/>
                最低: ${low}<br/>
                最高: ${high}<br/>
                ${pctChange ? `涨跌幅: ${pctChange}` : ''}
            </div>
            `
        }
    },
    xAxis: {
        type: 'category',
        data: []
    },
    yAxis: {
        type: 'value',
        name: '价格',
        min: 'dataMin',
        max: 'dataMax',
        splitLine: { show: true, lineStyle: { type: 'dashed', color: '#f5f5f5' } }
    },
    legend: {
        show: true,
        left: 'center',
        // Exclude 'K线' from legend
        selector: false,
        data: [
            'MA6', 'MA10', 'MA25', 'MA43', 'MA60', 'MA120', 'MA200'
        ]
    },
    dataZoom: [
        {
            type: 'inside',
            start: 0,
            end: 100
        }
    ],
    series: [
        {
            name: 'K线',
            type: 'candlestick',
            data: []
        },
        {
            name: 'MA6',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 1,
                color: '#5470C6'
            },
            showSymbol: false
        }
        ,
        {
            name: 'MA10',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 1,
                color: '#91cc75'
            },
            showSymbol: false
        },
        {
            name: 'MA25',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 2,
                color: '#fac858'
            },
            showSymbol: false
        },
        {
            name: 'MA43',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 1,
                color: '#ee6666'
            },
            showSymbol: false
        },
        {
            name: 'MA60',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 1,
                color: '#73c0de'
            },
            showSymbol: false
        },
        {
            name: 'MA120',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 1,
                color: '#3ba272'
            },
            showSymbol: false
        },
        {
            name: 'MA200',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 2,
                color: '#fc8452'
            },
            showSymbol: false
        },
        {
            name: 'SL1',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 2,
                // color: '#fc8452'
            },
            showSymbol: false
        },
        {
            name: 'SL2',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 2,
                // color: '#fc8452'
            },
            showSymbol: false
        },
        {
            name: 'TP1',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 2,
                // color: '#fc8452'
            },
            showSymbol: false
        },
        {
            name: 'TP2',
            type: 'line',
            data: [],
            smooth: true,
            lineStyle: {
                width: 2,
                // color: '#fc8452'
            },
            showSymbol: false
        },
    ]
})

const chartVolOption = ref({
    title: {
        text: '成交量',
        left: 'left',
        textStyle: {
            fontSize: 14
        }
    },
    tooltip: {
        trigger: 'axis',
        confine: true,
        padding: [4, 8],
        textStyle: {
            fontSize: 12
        }
    },
    xAxis: {
        type: 'category',
        data: []
    },
    yAxis: {
        type: 'value',
        splitLine: { show: true, lineStyle: { type: 'dashed', color: '#f5f5f5' } }

    },
    dataZoom: [
        {
            type: 'inside',
            start: 0,
            end: 100
        }
    ],
    series: [
        {
            name: '成交量',
            type: 'bar',
            data: [],
            smooth: true
        }
    ]
})

const chartTechOption = ref({
    title: {
        text: '技术指标',
        left: 'left',
        textStyle: {
            fontSize: 14
        }
    },
    tooltip: {
        trigger: 'axis',
        confine: true,
        padding: [4, 8],
        textStyle: {
            fontSize: 12
        }
    },
    legend: {
        show: true,
        left: 'center'
    },
    xAxis: {
        type: 'category',
        data: []
    },
    yAxis: {
        type: 'value',
        splitLine: { show: true, lineStyle: { type: 'dashed', color: '#f5f5f5' } }
    },
    dataZoom: [
        {
            type: 'inside',
            start: 0,
            end: 100
        }
    ],
})

const chartChipOption = ref({
    title: {
        text: '筹码分布',
        left: 'left',
        textStyle: { fontSize: 14 }
    },
    tooltip: {
        trigger: 'axis',
        confine: true,
        padding: [4, 8],
        textStyle: { fontSize: 12 },
        axisPointer: { type: 'shadow' },
        formatter: function (params) {
            const item = params && params[0]
            if (!item) return ''
            const idx = Number(item.dataIndex)
            const row = chipBars.value[idx]
            if (!row) return ''
            return `价格: ${Number(row.price).toFixed(2)}<br/>筹码占比: ${Number(row.percent || 0).toFixed(2)}%`
        }
    },
    xAxis: {
        type: 'value',
        name: 'percent',
        splitLine: { show: true, lineStyle: { type: 'dashed', color: '#f5f5f5' } }
    },
    yAxis: {
        type: 'category',
        name: 'price',
        inverse: false,
        splitLine: { show: false },
        data: []
    },
    series: [
        {
            name: '筹码',
            type: 'bar',
            barMaxWidth: 8,
            data: []
        }
    ]
})

function buildPaddedChipBuckets(sortedRows) {
    if (!Array.isArray(sortedRows) || !sortedRows.length) return []
    const minDisplayPrice = 0.01
    let minStep = Number.POSITIVE_INFINITY
    for (let i = 1; i < sortedRows.length; i++) {
        const diff = Number((sortedRows[i].price - sortedRows[i - 1].price).toFixed(6))
        if (diff > 0 && diff < minStep) minStep = diff
    }
    if (!Number.isFinite(minStep)) minStep = 0.01
    minStep = Math.max(minStep, 0.0001)

    const padCount = Math.max(8, Math.ceil(sortedRows.length * 0.25))
    const minPrice = sortedRows[0].price
    const maxPrice = sortedRows[sortedRows.length - 1].price
    const out = []
    for (let i = padCount; i >= 1; i--) {
        const p = Number((minPrice - minStep * i).toFixed(4))
        if (p < minDisplayPrice) continue
        out.push({ price: p, percent: 0, isReal: false })
    }
    for (const row of sortedRows) {
        out.push({ price: row.price, percent: row.percent, isReal: true })
    }
    for (let i = 1; i <= padCount; i++) {
        const p = Number((maxPrice + minStep * i).toFixed(4))
        out.push({ price: p, percent: 0, isReal: false })
    }
    return out
}

function refreshChipChartOption() {
    const realBars = chipBars.value.filter(item => item && item.isReal)
    const totalPercent = realBars.reduce((sum, item) => sum + Number(item.percent || 0), 0)

    if (!realBars.length || totalPercent <= 0) {
        chipWinRate.value = 0
        chipConcentrationRate.value = 0
    } else {
        const currentPrice = Number(chipCurrentPrice.value)
        if (Number.isFinite(currentPrice)) {
            const winPercent = realBars
                .filter(item => Number(item.price) <= currentPrice)
                .reduce((sum, item) => sum + Number(item.percent || 0), 0)
            chipWinRate.value = (winPercent / totalPercent) * 100
        } else {
            chipWinRate.value = 0
        }

        const topCount = Math.max(1, Math.ceil(realBars.length * 0.1))
        const concentrationPercent = [...realBars]
            .sort((a, b) => Number(b.percent || 0) - Number(a.percent || 0))
            .slice(0, topCount)
            .reduce((sum, item) => sum + Number(item.percent || 0), 0)
        chipConcentrationRate.value = (concentrationPercent / totalPercent) * 100
    }

    chartChipOption.value.title.text = `筹码分布 ${chipTradeDate.value || ''}`.trim()
    chartChipOption.value.yAxis.data = chipBars.value.map(item => Number(item.price).toFixed(2))
    chartChipOption.value.series[0].data = chipBars.value.map(item => ({
        value: item.percent,
        itemStyle: {
            color: !item.isReal
                ? 'rgba(0,0,0,0)'
                : (chipCurrentPrice.value !== null && Number(item.price) <= Number(chipCurrentPrice.value)
                    ? '#d14a61'
                    : '#8f9399')
        }
    }))
}

function normalizeTradeDateKey(tradeDate) {
    return String(tradeDate || '').replace(/-/g, '').trim()
}

function getChipCacheKey(tsCode, tradeDate) {
    return `${tsCode}|${normalizeTradeDateKey(tradeDate)}`
}

function buildChipBucketsFromRows(rows) {
    const map = new Map()
    for (const item of rows || []) {
        const price = Number(item.price)
        const percent = Number(item.percent)
        if (!Number.isFinite(price) || !Number.isFinite(percent)) continue
        map.set(price, (map.get(price) || 0) + percent)
    }
    const sorted = Array.from(map.entries())
        .map(([price, percent]) => ({ price, percent }))
        .sort((a, b) => a.price - b.price)
    return buildPaddedChipBuckets(sorted)
}

async function fetchChipDistributionBatch(tsCode, tradeDateList) {
    if (!tsCode || !Array.isArray(tradeDateList) || tradeDateList.length === 0) return
    const normalizedDates = tradeDateList
        .map(normalizeTradeDateKey)
        .filter(Boolean)
    if (!normalizedDates.length) return

    const uniqueDates = Array.from(new Set(normalizedDates)).sort()
    const startDate = uniqueDates[0]
    const endDate = uniqueDates[uniqueDates.length - 1]

    const missingDates = uniqueDates.filter(dateKey => !chipCache.has(getChipCacheKey(tsCode, dateKey)))
    if (missingDates.length === 0) {
        return
    }

    const batchCacheKey = `${tsCode}|RANGE|${startDate}|${endDate}`
    if (chipCache.has(batchCacheKey) && missingDates.length === 0) {
        return
    }

    try {
        const url = `${baseURL}/tushare/${encodeURIComponent(tsCode)}/CYQ_CHIPS/`
        const resp = await axios.get(url, { params: { start_date: startDate, end_date: endDate } })
        const rows = Array.isArray(resp?.data?.data) ? resp.data.data : []

        const byDate = new Map()
        for (const row of rows) {
            const key = normalizeTradeDateKey(row.trade_date)
            if (!key) continue
            if (!byDate.has(key)) byDate.set(key, [])
            byDate.get(key).push(row)
        }

        for (const dateKey of uniqueDates) {
            const cacheKey = getChipCacheKey(tsCode, dateKey)
            if (chipCache.has(cacheKey)) continue
            const dayRows = byDate.get(dateKey) || []
            const padded = buildChipBucketsFromRows(dayRows)
            if (padded.length > 0) {
                chipCache.set(cacheKey, padded)
            }
        }

        chipCache.set(batchCacheKey, true)
    } catch (error) {
        // batch加载失败时回退到按日加载
    }
}

async function fetchChipDistribution(tsCode, tradeDate, currentPrice = null) {
    if (!tsCode || !tradeDate) return
    chipTradeDate.value = tradeDate
    chipCurrentPrice.value = currentPrice

    const cacheKey = getChipCacheKey(tsCode, tradeDate)
    if (chipCache.has(cacheKey)) {
        const cached = chipCache.get(cacheKey)
        if (Array.isArray(cached) && cached.length > 0) {
            chipBars.value = cached
            refreshChipChartOption()
            return
        }
    }

    const ymd = String(tradeDate).replace(/-/g, '')
    try {
        const url = `${baseURL}/tushare/${encodeURIComponent(tsCode)}/CYQ_CHIPS/`
        const resp = await axios.get(url, { params: { start_date: ymd, end_date: ymd } })
        const rows = Array.isArray(resp?.data?.data) ? resp.data.data : []
        chipBars.value = buildChipBucketsFromRows(rows)
        chipCache.set(cacheKey, chipBars.value)
        refreshChipChartOption()
    } catch (error) {
        chipBars.value = []
        refreshChipChartOption()
    }
}

function resolveKlineIndexFromPointer(event) {
    const info = event?.axesInfo?.find(x => x.axisDim === 'x')
    if (!info) return -1
    const raw = info.value
    const idx = Number(raw)
    if (Number.isInteger(idx) && idx >= 0 && idx < tradeDates.value.length) {
        return idx
    }
    const asText = String(raw ?? '')
    return tradeDates.value.findIndex(d => String(d) === asText)
}

function onTrendAxisPointer(event) {
    const idx = resolveKlineIndexFromPointer(event)
    if (idx < 0 || idx >= tradeDates.value.length) return

    if (idx === lastHoverIndex.value) {
        const latestClose = close.value[idx]
        if (chipCurrentPrice.value !== latestClose) {
            chipCurrentPrice.value = latestClose
            refreshChipChartOption()
        }
        return
    }

    lastHoverIndex.value = idx
    const tradeDate = tradeDates.value[idx]
    const currentClose = close.value[idx]
    fetchChipDistribution(stockStore.tsCode, tradeDate, currentClose)
}

function bindTrendHoverSync() {
    const chart = trendChartRef.value?.chart
    if (!chart) return
    chart.off('updateAxisPointer', onTrendAxisPointer)
    chart.on('updateAxisPointer', onTrendAxisPointer)
}


// 配置8个基本面图表的 option，并设置 group
function createFundamentalChartOption(title) {
    return ref({
        title: {
            text: title,
            left: 'left',
            textStyle: { fontSize: 14 }
        },
        tooltip: {
            trigger: 'axis',
            confine: true,
            padding: [4, 8],
            textStyle: {
                fontSize: 12
            }
        },
        legend: { show: false, left: 'center' },
        xAxis: { type: 'category', data: [] },
        yAxis: {
            type: 'value',
            min: 'dataMin',
            max: 'dataMax',
            splitLine: { show: true, lineStyle: { type: 'dashed', color: '#f5f5f5' } }
        },
        dataZoom: [
            {
                type: 'inside',
                start: 0,
                end: 100
            }
        ],
    })
}

const chartPeOption = createFundamentalChartOption('市盈率')
const chartPeTTMOption = createFundamentalChartOption('市盈率(TTM)')
const chartPsOption = createFundamentalChartOption('市销率')
const chartPsTTMOption = createFundamentalChartOption('市销率(TTM)')
const chartPbOption = createFundamentalChartOption('市净率')
const chartVolRatioOption = createFundamentalChartOption('量比')
const chartTurnoverOption = createFundamentalChartOption('换手率')
const chartTurnoverFOption = createFundamentalChartOption('换手率(自由流通)')


async function fetchTradingHistory(stockCode = '000001.SZ', freq = 'D', adj = 'qfq', count = 60) {
    try {
        const url = `${baseURL}/stocks/${stockCode}/trading-history/${freq}/${adj}/${count}/`
        const response = await axios.get(url)
        const jsonData = response.data
        parseStockChartData(jsonData)

        // Assign parsed data to chart options
        chartTrendOption.value.xAxis.data = tradeDates.value
        chartTrendOption.value.series[0].data = kdata.value
        // Add quantile lines for close price to trend chart
        // Calculate and assign moving averages
        const maPeriods = [6, 10, 25, 43, 60, 120, 200]
        const maSeries = maPeriods.map(period => ({
            name: `MA${period}`,
            type: 'line',
            data: calcMovingAvg(close.value, period),
            smooth: true,
            lineStyle: chartTrendOption.value.series.find(s => s.name === `MA${period}`)?.lineStyle || { width: 1 },
            showSymbol: false
        }))
        // Rebuild the series array to avoid duplicate quantile lines
        chartTrendOption.value.series = [
            {
                name: 'K线',
                type: 'candlestick',
                data: kdata.value
            },
            ...maSeries,
            {
                name: '收盘价 90%分位',
                type: 'line',
                data: quantile(close.value, 0.9),
                smooth: true,
                showSymbol: false,
                lineStyle: { color: 'red', width: 1 }
            },
            {
                name: '收盘价中位数',
                type: 'line',
                data: quantile(close.value, 0.5),
                smooth: true,
                showSymbol: false,
                lineStyle: { color: 'blue', width: 1 }
            },
            {
                name: '收盘价 10%分位',
                type: 'line',
                data: quantile(close.value, 0.1),
                smooth: true,
                showSymbol: false,
                lineStyle: { color: 'green', width: 1 }
            },
            {
                name: 'SL1',
                data: sl1.value,
            },
            {
                name: 'SL2',
                data: sl2.value,
            },
            {
                name: 'TP1',
                data: tp1.value,
            },
            {
                name: 'TP2',
                data: tp2.value,
            }
        ]

        // If you have MA lines in jsonData, update them here as well
        chartVolOption.value.xAxis.data = tradeDates.value
        // Add quantile lines for volume chart
        chartVolOption.value.series = [
            {
                name: '成交量',
                type: 'bar',
                data: vol.value,
                smooth: true
            },
            {
                name: '成交量 90%分位',
                type: 'line',
                data: quantile(vol.value, 0.9),
                smooth: true,
                showSymbol: false,
                lineStyle: { color: 'red', width: 1 }
            },
            {
                name: '成交量 10%分位',
                type: 'line',
                data: quantile(vol.value, 0.1),
                smooth: true,
                showSymbol: false,
                lineStyle: { color: 'green', width: 1 }
            }
        ]

        // For technical indicator (e.g., MACD, KDJ, RSI, CCI)
        chartTechOption.value.xAxis.data = tradeDates.value
        const tech = techOption.value
        const techMap = {
            macd: [
                { name: 'MACD', key: 'macd' },
                { name: 'DIF', key: 'macd_dif' },
                { name: 'DEA', key: 'macd_dea' }
            ],
            kdj: [
                { name: 'K', key: 'kdj_k' },
                { name: 'D', key: 'kdj_d' },
                { name: 'J', key: 'kdj_j' }
            ],
            rsi: [
                { name: 'RSI', key: 'rsi' }
            ],
            cci: [
                { name: 'CCI', key: 'cci' }
            ]
        }

        const series = (techMap[tech] || [])
            .filter(item => indicData.value[item.key])
            .map(item => ({
                name: item.name,
                type: item.name === 'MACD' ? 'bar' : 'line',
                data: indicData.value[item.key],
                smooth: item.name === 'MACD' ? false : true,
                showSymbol: false
            }))

        chartTechOption.value.series = series

        // Get the last item of kdata array
        const lastKData = kdata.value.length > 0 ? kdata.value[kdata.value.length - 1] : null;

        // update stock trade store
        if (lastKData) {
            stockStore.setOpen(lastKData[0]);
            stockStore.setClose(lastKData[1]);
            stockStore.setLow(lastKData[2]);
            stockStore.setHigh(lastKData[3]);
        }
        stockStore.setPctChg(pctChg.value.length > 0 ? pctChg.value[pctChg.value.length - 1] : null);

        if (tradeDates.value.length > 0) {
            await fetchChipDistributionBatch(stockCode, tradeDates.value)
            const idx = tradeDates.value.length - 1
            lastHoverIndex.value = idx
            await fetchChipDistribution(stockCode, tradeDates.value[idx], close.value[idx])
        }
    } catch (error) {
        console.error('Failed to fetch trading history:', error)
    }
}

const fundamentalData = ref([])

import { quantile } from './helper'

async function fetchFundamentalHistory(tsCode = stockStore.tsCode, freq = stockChartFilterStore.freq, count = stockChartFilterStore.period) {
    try {
        const url = `${baseURL}/stocks/${tsCode}/fundamental-history/${freq}/${count}/`
        const response = await axios.get(url)
        // The response data is in response.data.data
        fundamentalData.value = response.data.data

        // Assume response.data.data is an array of objects with fields: trade_date, pe, pe_ttm, ps, ps_ttm, pb, volume_ratio, turnover_rate, turnover_rate_f
        const dates = fundamentalData.value.map(item => item.trade_date)


        // Helper to set chart option for a metric
        function setChartOption(optionRef, arr, name) {
            optionRef.value.xAxis.data = dates
            optionRef.value.series = [
                { name, type: 'line', data: arr, smooth: true, showSymbol: false, },
                {
                    name: `${name} 90%分位`, type: 'line', data: quantile(arr, 0.9), smooth: true, showSymbol: false, lineStyle: { color: 'red', width: 1 },
                },
                {
                    name: `${name} 10%分位`, type: 'line', data: quantile(arr, 0.1), smooth: true, showSymbol: false, lineStyle: { color: 'green', width: 1 },
                }
            ]
        }

        setChartOption(chartPeOption, fundamentalData.value.map(i => i.pe), 'PE')
        setChartOption(chartPeTTMOption, fundamentalData.value.map(i => i.pe_ttm), 'PE(TTM)')
        setChartOption(chartPsOption, fundamentalData.value.map(i => i.ps), 'PS')
        setChartOption(chartPsTTMOption, fundamentalData.value.map(i => i.ps_ttm), 'PS(TTM)')
        setChartOption(chartPbOption, fundamentalData.value.map(i => i.pb), 'PB')
        setChartOption(chartVolRatioOption, fundamentalData.value.map(i => i.volume_ratio), '量比')
        setChartOption(chartTurnoverOption, fundamentalData.value.map(i => i.turnover_rate), '换手率')
        setChartOption(chartTurnoverFOption, fundamentalData.value.map(i => i.turnover_rate_f), '换手率(自由流通)')
    } catch (error) {
        console.error('Failed to fetch fundamental history:', error)
    }
}

// 在+k线图上渲染顶和低
// 获取顶底数据并在K线图上渲染
async function renderTopsBottomsOnTrendChart(tsCode = stockStore.tsCode, model = stockChartFilterStore.model,
    freq = stockChartFilterStore.freq, count = stockChartFilterStore.period, topBottomSwitch = stockChartFilterStore.topBottomSwitch, version = '1.2') {
    try {
        // 假设后端接口返回格式为 [{trade_date: '20240101', type: 'T'}, ...]
        if (!topBottomSwitch) {
            // 如果开关关闭，清除markPoint
            if (chartTrendOption.value.series[0].markPoint) {
                chartTrendOption.value.series[0].markPoint.data = []
            }
            return
        }
        const url = `${baseURL}/stocks/${tsCode}/prediction/${model.toUpperCase()}/STDOPT/${count}/${freq}/${version}/`
        const response = await axios.get(url)
        const tbData = response.data // [{trade_date, type}]
        // tbData is an array of objects with { ts_code, trade_date, top_or_bottom }
        if (!Array.isArray(tbData.data) || tbData.data.length === 0) return

        // tradeDates.value: ['20240101', ...] or ['2025-08-29', ...]
        // Normalize trade_date format if needed
        const markPoints = tbData.data
            .map(tb => {
                // Try to match trade_date directly
                let idx = tradeDates.value.findIndex(d => d === tb.trade_date)
                // If not found, try removing dashes for comparison
                if (idx === -1) {
                    const normalizedDate = tb.trade_date.replace(/-/g, '')
                    idx = tradeDates.value.findIndex(d => d.replace(/-/g, '') === normalizedDate)
                }
                if (idx === -1) return null
                const k = kdata.value[idx]
                if (!k) return null
                // top_or_bottom: 'T' for top, 'B' for bottom
                return {
                    name: tb.top_or_bottom,
                    value: tb.top_or_bottom,
                    xAxis: idx,
                    yAxis: tb.top_or_bottom === 'T' ? k[3] : k[2], // high for T, low for B
                    symbol: 'pin',
                    symbolSize: 20,
                    symbolRotate: tb.top_or_bottom === 'B' ? 180 : 0,
                    itemStyle: {
                        color: tb.top_or_bottom === 'T' ? '#4caf50' : '#d14a61'
                    },
                    label: {
                        show: true,
                        formatter: tb.top_or_bottom,
                        color: '#fff',
                        fontWeight: 'bold'
                    }
                }
            })
            .filter(Boolean)

        // 更新K线series的markPoint
        if (!chartTrendOption.value.series[0].markPoint) {
            chartTrendOption.value.series[0].markPoint = { data: [] }
        }
        chartTrendOption.value.series[0].markPoint.data = markPoints
    } catch (error) {
        console.error('Failed to fetch tops/bottoms:', error)
    }
}

// 更新股票k线图顶和底标记
const renderTopBottomSymbol = (tradeChartData, entryPoints) => {
    //添加series
    // mixChartOption.series.slice(7,1);
    var ohlcDateLabel = tradeChartData.categoryData;
    var ohlc = tradeChartData.values;
    var markData = [];

    entryPoints.forEach(entryPoint => {
        if (entryPoint[0] != null) {
            var indexTradeDate = ohlcDateLabel.indexOf(entryPoint[2]);
            if (entryPoint[1] == "B") {
                markData.push(
                    {
                        coord: [entryPoint[2], ohlc[indexTradeDate][2]],
                        value: "B",
                        symbol: "pin",
                        symbolSize: 20,
                        symbolRotate: 180,
                        symbolOffset: [0, 5],
                        itemStyle: {
                            //设置标记点的样式
                            normal: { color: "red" },
                        },
                    }
                );
            }
            if (entryPoint[1] == "T") {
                markData.push(
                    {
                        coord: [entryPoint[2], ohlc[indexTradeDate][3]],
                        value: "S",
                        symbol: "pin",
                        symbolSize: 20,
                        // symbolRotate: 180,
                        itemStyle: {
                            //设置标记点的样式
                            normal: { color: "green" },
                        },
                    }
                );
            }
        }
    });

    var tradeOption =
    {
        series: [
            {
                id: 'CLOSE',
                markPoint: {
                    data: markData,
                }
            }
        ]
    };
}

// 在fetchTradingHistory后调用
watch(
    () => ({ topBtmSwitch: stockChartFilterStore.topBottomSwitch }),
    () => {
        renderTopsBottomsOnTrendChart()
    }
)

// 事件处理
// 处理周期，时常，顶底和模型切换导致stock chart的变化
// 处理成交量和成交额的切换
function onVolOptionChange() {
    // Update the chartVolOption based on volOption
    // If 'amount', use vol.value; if 'vol', use amount (if available in your data)
    // Here, assuming 'vol' is volume and 'amount' is not available, so just use vol.value for both
    // If you have 'amount' in your data, adjust accordingly

    if (volOption.value === 'vol') {
        chartVolOption.value.series[0].data = vol.value
        chartVolOption.value.series[0].name = '成交量'
    } else if (volOption.value === 'amount') {
        // If you have amount data, use it here. Otherwise, just use vol.value as a placeholder.
        chartVolOption.value.series[0].data = amount.value
        chartVolOption.value.series[0].name = '成交额'
    }
}

// 处理技术指标切换
function onTechOptionChange() {
    const techMap = {
        macd: [
            { name: 'MACD', key: 'macd' },
            { name: 'DIF', key: 'macd_dif' },
            { name: 'DEA', key: 'macd_dea' }
        ],
        kdj: [
            { name: 'K', key: 'kdj_k' },
            { name: 'D', key: 'kdj_d' },
            { name: 'J', key: 'kdj_j' }
        ],
        rsi: [
            { name: 'RSI', key: 'rsi_6' },
            { name: 'RSI12', key: 'rsi_12' },
            { name: 'RSI24', key: 'rsi_24' }
        ],
        cci: [
            { name: 'CCI', key: 'cci' }
        ]
    }

    const series = (techMap[techOption.value] || [])
        .filter(item => indicData.value[item.key])
        .map(item => ({
            name: item.name,
            type: 'line',
            data: indicData.value[item.key],
            smooth: true,
            showSymbol: false
        }))

    // Directly assign new series array to avoid leftover data
    chartTechOption.value.series = []
    chartTechOption.value.series = series
}
// 处理adj变化事件
// function onAdjPriceOptionChange() {
//     fetchTradingHistory(stockStore.tsCode, stockChartFilterStore.freq, adjPriceOption.value, stockChartFilterStore.period)
// }

// Watch volOption and update chart when changed
import { watch } from 'vue'
import { sl } from 'element-plus/es/locales.mjs'
// watch(adjPriceOption, onAdjPriceOptionChange)
// watch(volOption, onVolOptionChange, { immediate: true })
// watch(techOption, onTechOptionChange, { immediate: true })
watch(
    () => ({
        ts_code: stockStore.tsCode,
        freq: stockChartFilterStore.freq,
        period: stockChartFilterStore.period,
        adj: adjPriceOption.value
    }),
    (newVal) => {
        fetchStockStatus(newVal.ts_code)
        fetchTradingHistory(newVal.ts_code, newVal.freq, newVal.adj, newVal.period)
        fetchFundamentalHistory(newVal.ts_code, newVal.freq, newVal.period)
        renderTopsBottomsOnTrendChart(newVal.ts_code, stockChartFilterStore.model, newVal.freq, newVal.period, stockChartFilterStore.topBottomSwitch)
    }
)


watch([selectedFreqEmbed, selectedPeriodEmbed], ([newFreq, newPeriod]) => {
    stockChartFilterStore.setFreq(newFreq)
    stockChartFilterStore.setPeriod(newPeriod)

    fetchTradingHistory(
        stockStore.tsCode,
        newFreq,
        adjPriceOption.value,
        newPeriod
    )
    fetchFundamentalHistory(
        stockStore.tsCode,
        newFreq,
        newPeriod
    )
    renderTopsBottomsOnTrendChart(
        stockStore.tsCode,
        stockChartFilterStore.model,
        newFreq,
        newPeriod,
        stockChartFilterStore.topBottomSwitch
    )
})



// Call the function and set up chart group on mount
onMounted(() => {
    fetchStockStatus(stockStore.tsCode)
    fetchTradingHistory(
        stockStore.tsCode,
        stockChartFilterStore.freq,
        adjPriceOption.value,
        stockChartFilterStore.period
    )
    fetchFundamentalHistory(
        stockStore.tsCode,
        stockChartFilterStore.freq
    )
    renderTopsBottomsOnTrendChart(
        stockStore.tsCode,
        stockChartFilterStore.model,
        stockChartFilterStore.freq,
        stockChartFilterStore.period,
        stockChartFilterStore.topBottomSwitch
    )

        // 绑定 group 到每个 v-chart
        ;[trendChartRef, volChartRef, techChartRef].forEach(refItem => {
            if (refItem.value && refItem.value.chart) {
                refItem.value.chart.group = chartGroup
            }
        })
    echarts.connect(chartGroup)
        // 绑定 group 到每个 v-chart
        ;[
            techChartRef,
            peChartRef,
            peTTMChartRef,
            psChartRef,
            psTTMChartRef,
            pbChartRef,
            turnoverChartRef,
            turnoverFChartRef,
            volRatioChartRef
        ].forEach(refItem => {
            if (refItem.value && refItem.value.chart) {
                refItem.value.chart.group = chartGroup
            }
        })
    echarts.connect(chartGroup)

    nextTick(() => {
        bindTrendHoverSync()
    })
})

onBeforeUnmount(() => {
    const chart = trendChartRef.value?.chart
    if (!chart) return
    chart.off('updateAxisPointer', onTrendAxisPointer)
})

</script>

<style scoped>
.stock-chart-container {
    width: 100%;
    /* height: 800px; */
    display: flex;
    justify-content: center;
    align-items: center;
}

.echart-placeholder {
    width: 100%;
    height: 100%;
    background: #f5f5f5;
    /* border: 1px dashed #ccc; */
}

.chip-metrics-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    margin: 0 4px 8px;
    font-size: 12px;
    color: #606266;
}
</style>
