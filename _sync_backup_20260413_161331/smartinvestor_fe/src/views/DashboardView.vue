<template>
  <DefaultLayout>
    <el-row :gutter="24">
      <el-col :span="5">
        <Watchlist />
      </el-col>
      <el-col :span="15">
        <div class="grid-content ep-bg-purple">
          <el-row>
            <el-col :span="24">
              <StockChartFilter />
            </el-col>
          </el-row>
          <el-row>
            <el-col :span="24">
              <StockChart :display-embed="true" />
            </el-col>
          </el-row>
          <el-row>
            <el-col :span="24">
                <GainLossQuant />
            </el-col>
          </el-row>
        </div>
      </el-col>
      <el-col :span="4">
        <el-row>
          <el-col :span="24">
            <StocksRelevant />
          </el-col>
        </el-row>
        <el-row>
          <el-col :span="24">
            <TagRelevant />
          </el-col>
        </el-row>
      </el-col>
    </el-row>
  </DefaultLayout>
</template>

<script setup lang="ts">
import DefaultLayout from '../layouts/DefaultLayout.vue'
import StockChartFilter from '../components/StockChartFilter.vue'
import Watchlist from '../components/Watchlist.vue';
import StockChart from '../components/StockChart.vue';
import StocksRelevant from '../components/FinanceRelevant.vue';
import GainLossQuant from '../components/GainLossQuant.vue';
// Element Plus
import { ElRow, ElCol } from 'element-plus';
import TagRelevant from '../components/TagRelevant.vue';
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