<template>
  <DefaultLayout>
    <el-row :gutter="24">
      <el-col :span="5">
        <Watchlist />
      </el-col>
      <el-col :span="showRecentReportPanel ? 14 : 19">
        <div class="grid-content ep-bg-purple">
          <el-row>
            <el-col :span="24">
              <StockChartFilter
                :show-recent-report-panel="showRecentReportPanel"
                @toggle-recent-report-panel="toggleRecentReportPanel"
              />
            </el-col>
          </el-row>
        </div>
      </el-col>
      <el-col v-if="showRecentReportPanel" :span="5">
        <el-row>
          <el-col :span="24">
            <el-affix :offset="75">
              <RecentFinancialUpdatesTag />
            </el-affix>
          </el-col>
        </el-row>
      </el-col>
    </el-row>
  </DefaultLayout>
</template>

<script setup lang="ts">
import { inject, onMounted, ref } from 'vue'
import axios from 'axios'
import DefaultLayout from '../layouts/DefaultLayout.vue'
import StockChartFilter from '../components/StockChartFilter.vue'
import Watchlist from '../components/Watchlist.vue';
import { useStockTradeStore } from '../stores/stockTradeStore'
// Element Plus
import { ElRow, ElCol, ElAffix } from 'element-plus';
import RecentFinancialUpdatesTag from '../components/RecentFinancialUpdatesTag.vue';

const DEFAULT_TS_CODE = '000001.SZ'
const DEFAULT_STOCK_NAME = '平安银行'
const baseURL = inject<string>('baseURL', '')
const stockTradeStore = useStockTradeStore()
const showRecentReportPanel = ref(true)

async function initializeDashboardStock() {
  stockTradeStore.setName(DEFAULT_STOCK_NAME)
  stockTradeStore.setTsCode(DEFAULT_TS_CODE)
  if (!baseURL) {
    return
  }

  try {
    const response = await axios.get(`${baseURL}/watchlist/0/1/`, {
      params: { format: 'json', market: 'HO' },
    })
    const firstHolding = response?.data?.data?.[0]
    const firstHoldingTsCode = String(firstHolding?.ts_code || '').trim().toUpperCase()
    if (firstHoldingTsCode) {
      stockTradeStore.setName(String(firstHolding?.name || '').trim())
      stockTradeStore.setTsCode(firstHoldingTsCode)
    }
  } catch (error) {
    console.error('Failed to initialize dashboard stock from holdings:', error)
  }
}

function toggleRecentReportPanel() {
  showRecentReportPanel.value = !showRecentReportPanel.value
  if (typeof window !== 'undefined') {
    window.localStorage.setItem('dashboard_show_recent_report_panel', showRecentReportPanel.value ? '1' : '0')
  }
}

onMounted(() => {
  void initializeDashboardStock()
  if (typeof window === 'undefined') {
    return
  }
  const saved = String(window.localStorage.getItem('dashboard_show_recent_report_panel') || '').trim()
  if (saved === '0') {
    showRecentReportPanel.value = false
  }
})
</script>

<style>
.el-row {
  margin-bottom: 20px;
}

.el-row:last-child {
  margin-bottom: 0;
}

.el-col {
  border-radius: 4px;
}

.grid-content {
  border-radius: 4px;
  min-height: 36px;
}

/* 自定义 Element Plus demo 背景色 */
/* .ep-bg-purple-dark {
  background: #99a9bf;
}

.ep-bg-purple {
  background: #d3dce6;
}

.ep-bg-purple-light {
  background: #e5e9f2;
} */
</style>