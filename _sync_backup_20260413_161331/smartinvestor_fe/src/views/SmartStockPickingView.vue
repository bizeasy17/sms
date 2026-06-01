<template>
  <DefaultLayout>
    <el-row :gutter="24">
      <!-- <el-col :span="5">
        <StockPickSidebar />
      </el-col> -->
      <el-col :span="20">
        <div class="grid-content ep-bg-purple">
          <el-row>
            <el-col :span="24">
              <StockPickingFilter />
            </el-col>
          </el-row>
          <el-row>
            <el-col :span="24">
              <StockPickingResult />
            </el-col>
          </el-row>
          <el-row>
            <el-col :span="24">
            </el-col>
          </el-row>
        </div>
      </el-col>
      <el-col :span="4">
        <el-row>
          <el-col :span="24">
            <!-- <StocksRelevant /> -->
            <FinanceRelevant />
          </el-col>
        </el-row>
        <el-row>
          <el-col :span="24">
            <GainLossQuant />
          </el-col>
        </el-row>
      </el-col>
    </el-row>
  </DefaultLayout>
</template>

<script setup lang="ts">
import DefaultLayout from '../layouts/DefaultLayout.vue'
import StockPickingFilter from '../components/StockPickingFilter.vue'
// Element Plus
import { ElRow, ElCol } from 'element-plus';
import FinanceRelevant from '../components/FinanceRelevant.vue';
import GainLossQuant from '../components/GainLossQuant.vue';
import StockPickingResult from '../components/StockPickingResult.vue';
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