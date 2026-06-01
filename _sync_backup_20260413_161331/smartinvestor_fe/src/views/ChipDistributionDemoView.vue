<template>
  <div class="chip-page">
    <el-card shadow="never" class="chip-panel">
      <template #header>
        <div class="panel-title">筹码分布示例（CYQ_CHIPS）</div>
      </template>

      <div class="controls">
        <el-select
          v-model="selectedTsCode"
          filterable
          remote
          reserve-keyword
          placeholder="输入股票代码或名称"
          :remote-method="searchStocks"
          :loading="stockLoading"
          style="width: 300px"
        >
          <el-option
            v-for="item in stockOptions"
            :key="item.ts_code"
            :label="`${item.name} ${item.ts_code}`"
            :value="item.ts_code"
          />
        </el-select>

        <el-date-picker
          v-model="selectedDate"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="选择日期"
          style="width: 180px"
        />

        <el-button type="primary" :loading="loading" @click="fetchChips">加载筹码</el-button>
      </div>

      <div class="summary" v-if="buckets.length">
        <span>当前价格指针: {{ effectivePriceText }}</span>
        <span>获胜率: <b class="win-rate">{{ (winRate * 100).toFixed(2) }}%</b></span>
        <span>样本点: {{ buckets.length }}</span>
      </div>

      <div class="chart-wrap" v-loading="loading">
        <v-chart ref="chartRef" class="chip-chart" :option="chartOption" autoresize />
      </div>

      <el-empty v-if="!loading && !buckets.length" description="当前条件无筹码数据" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import axios from 'axios'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, TitleComponent, AxisPointerComponent } from 'echarts/components'
import { ElMessage } from 'element-plus'

use([CanvasRenderer, BarChart, GridComponent, TooltipComponent, TitleComponent, AxisPointerComponent])

type ChipRow = {
  ts_code: string
  trade_date: string
  price: number
  percent: number
}

type StockOption = {
  ts_code: string
  name: string
}

const baseURL = inject('baseURL') as string
const selectedTsCode = ref('600000.SH')
const selectedDate = ref('')
const loading = ref(false)
const stockLoading = ref(false)
const chartRef = ref<any>(null)
const hoverPrice = ref<number | null>(null)

const stockOptions = ref<StockOption[]>([
  { ts_code: '600000.SH', name: '浦发银行' },
  { ts_code: '600519.SH', name: '贵州茅台' },
  { ts_code: '000001.SZ', name: '平安银行' },
])

const rows = ref<ChipRow[]>([])

const toYmd = (dateText: string) => dateText.split('-').join('')

const fetchLatestTradeDate = async () => {
  try {
    const resp = await axios.get(`${baseURL}/trading/latest-date/D/`)
    const latest = String(resp?.data?.latest_trade_date || '').trim()
    if (latest) {
      selectedDate.value = latest
      return latest
    }
  } catch {
    // noop, fallback below
  }
  const fallback = new Date().toISOString().slice(0, 10)
  selectedDate.value = fallback
  return fallback
}

const buckets = computed(() => {
  const map = new Map<number, number>()
  for (const row of rows.value) {
    const p = Number(row.price)
    const w = Number(row.percent)
    if (!Number.isFinite(p) || !Number.isFinite(w)) continue
    map.set(p, (map.get(p) || 0) + w)
  }
  return Array.from(map.entries())
    .map(([price, percent]) => ({ price, percent }))
    .sort((a, b) => a.price - b.price)
})

const totalPercent = computed(() => buckets.value.reduce((acc, x) => acc + x.percent, 0))

const weightedPrice = computed(() => {
  if (!buckets.value.length || totalPercent.value <= 0) return 0
  const weighted = buckets.value.reduce((acc, x) => acc + x.price * x.percent, 0)
  return weighted / totalPercent.value
})

const priceStep = computed(() => {
  if (buckets.value.length < 2) return 0.01
  let minDiff = Number.POSITIVE_INFINITY
  for (let i = 1; i < buckets.value.length; i += 1) {
    const diff = Number((buckets.value[i].price - buckets.value[i - 1].price).toFixed(6))
    if (diff > 0 && diff < minDiff) {
      minDiff = diff
    }
  }
  if (!Number.isFinite(minDiff)) return 0.01
  return Math.max(minDiff, 0.0001)
})

const paddedBuckets = computed(() => {
  if (!buckets.value.length) return [] as Array<{ price: number; percent: number; isReal: boolean }>
  const step = priceStep.value
  const padCount = Math.max(8, Math.ceil(buckets.value.length * 0.25))
  const minPrice = buckets.value[0].price
  const maxPrice = buckets.value[buckets.value.length - 1].price
  const minDisplayPrice = 0.01

  const result: Array<{ price: number; percent: number; isReal: boolean }> = []
  for (let i = padCount; i >= 1; i -= 1) {
    const paddedPrice = Number((minPrice - step * i).toFixed(4))
    if (paddedPrice < minDisplayPrice) {
      continue
    }
    result.push({
      price: paddedPrice,
      percent: 0,
      isReal: false,
    })
  }
  for (const item of buckets.value) {
    result.push({ price: item.price, percent: item.percent, isReal: true })
  }
  for (let i = 1; i <= padCount; i += 1) {
    result.push({
      price: Number((maxPrice + step * i).toFixed(4)),
      percent: 0,
      isReal: false,
    })
  }
  return result
})

const effectivePrice = computed(() => {
  if (hoverPrice.value !== null && Number.isFinite(hoverPrice.value)) return hoverPrice.value
  return weightedPrice.value
})

const winRate = computed(() => {
  if (!buckets.value.length || totalPercent.value <= 0) return 0
  const win = buckets.value
    .filter((x) => x.price <= effectivePrice.value)
    .reduce((acc, x) => acc + x.percent, 0)
  return Math.max(0, Math.min(1, win / totalPercent.value))
})

const effectivePriceText = computed(() => (effectivePrice.value ? effectivePrice.value.toFixed(2) : '--'))

const chartOption = computed(() => ({
  title: {
    text: `${selectedTsCode.value} ${selectedDate.value} 筹码分布`,
    left: 'center',
    textStyle: { fontSize: 14, fontWeight: 600 },
  },
  grid: { top: 56, right: 24, bottom: 28, left: 80 },
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'cross' },
    formatter: (params: any[]) => {
      const item = (params || [])[0]
      if (!item) return ''
      const idx = Number(item.dataIndex)
      const p = Number.isInteger(idx) && idx >= 0 && idx < paddedBuckets.value.length
        ? Number(paddedBuckets.value[idx].price)
        : Number(item.axisValue)
      if (!Number.isFinite(p) || totalPercent.value <= 0) return ''
      const win = buckets.value
        .filter((x) => x.price <= p)
        .reduce((acc, x) => acc + x.percent, 0)
      const ratio = Math.max(0, Math.min(1, win / totalPercent.value))
      const percent = Number.isInteger(idx) && idx >= 0 && idx < paddedBuckets.value.length
        ? paddedBuckets.value[idx].percent
        : Number(item.value || 0)
      return `价格: ${p.toFixed(2)}<br/>筹码占比: ${Number(percent || 0).toFixed(2)}<br/>获胜率: ${(ratio * 100).toFixed(2)}%`
    },
  },
  xAxis: {
    type: 'value',
    name: 'percent',
    splitLine: { show: true },
  },
  yAxis: {
    type: 'category',
    name: 'price',
    inverse: false,
    splitLine: { show: false },
    data: paddedBuckets.value.map((x) => x.price.toFixed(2)),
  },
  series: [
    {
      type: 'bar',
      barMaxWidth: 8,
      data: paddedBuckets.value.map((x) => ({
        value: x.percent,
        itemStyle: {
          color: !x.isReal ? 'rgba(0,0,0,0)' : (x.price <= effectivePrice.value ? '#d34a4a' : '#7f8c8d'),
        },
      })),
    },
  ],
}))

const searchStocks = async (query: string) => {
  if (!query) return
  stockLoading.value = true
  try {
    const resp = await axios.get(`${baseURL}/corporations/${encodeURIComponent(query)}/`)
    const list = (resp?.data?.data || []) as Array<{ ts_code: string; name: string }>
    stockOptions.value = list.map((x) => ({ ts_code: x.ts_code, name: x.name }))
  } catch {
    stockOptions.value = []
  } finally {
    stockLoading.value = false
  }
}

const fetchChips = async (allowRetry = true) => {
  if (!selectedTsCode.value || !selectedDate.value) {
    ElMessage.warning('请先选择股票和日期')
    return
  }
  loading.value = true
  hoverPrice.value = null
  try {
    const ymd = toYmd(selectedDate.value)
    const url = `${baseURL}/tushare/${encodeURIComponent(selectedTsCode.value)}/CYQ_CHIPS/`
    const resp = await axios.get(url, { params: { start_date: ymd, end_date: ymd } })
    rows.value = (resp?.data?.data || []) as ChipRow[]
    await nextTick()
    bindChartEvents()
  } catch (err: any) {
    const status = Number(err?.response?.status || 0)
    if (allowRetry && status === 404) {
      const latest = await fetchLatestTradeDate()
      if (latest && latest !== selectedDate.value) {
        selectedDate.value = latest
      }
      loading.value = false
      return fetchChips(false)
    }
    rows.value = []
    ElMessage.error(err?.response?.data?.error || '加载筹码失败')
  } finally {
    loading.value = false
  }
}

const onAxisPointer = (event: any) => {
  const info = event?.axesInfo?.find((x: any) => x.axisDim === 'y')
  if (!info) return
  const raw = info.value
  const idx = Number(raw)
  if (Number.isInteger(idx) && idx >= 0 && idx < paddedBuckets.value.length) {
    hoverPrice.value = Number(paddedBuckets.value[idx].price)
    return
  }
  const maybePrice = Number(raw)
  if (Number.isFinite(maybePrice)) {
    hoverPrice.value = maybePrice
  }
}

const onGlobalOut = () => {
  hoverPrice.value = null
}

const bindChartEvents = () => {
  const chart = chartRef.value?.chart
  if (!chart) return
  chart.off('updateAxisPointer', onAxisPointer)
  chart.on('updateAxisPointer', onAxisPointer)
  chart.getZr().off('globalout', onGlobalOut)
  chart.getZr().on('globalout', onGlobalOut)
}

onMounted(async () => {
  if (!selectedDate.value) {
    await fetchLatestTradeDate()
  }
  fetchChips()
})

onBeforeUnmount(() => {
  const chart = chartRef.value?.chart
  if (!chart) return
  chart.off('updateAxisPointer', onAxisPointer)
  chart.getZr().off('globalout', onGlobalOut)
})
</script>

<style scoped>
.chip-page {
  padding: 16px;
}

.chip-panel {
  border-radius: 8px;
}

.panel-title {
  font-size: 16px;
  font-weight: 600;
}

.controls {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.summary {
  display: flex;
  gap: 20px;
  margin-bottom: 10px;
  color: #444;
  font-size: 13px;
}

.win-rate {
  color: #d34a4a;
}

.chart-wrap {
  height: 560px;
}

.chip-chart {
  width: 100%;
  height: 100%;
}
</style>
