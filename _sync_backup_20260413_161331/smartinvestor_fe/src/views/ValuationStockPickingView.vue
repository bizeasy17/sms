<template>
  <DefaultLayout>
    <el-row :gutter="24">
      <el-col :span="20">
        <div class="grid-content ep-bg-purple">
          <el-row>
            <el-col :span="24">
              <ValuationStockPickingFilter />
            </el-col>
          </el-row>
          <el-row>
            <el-col :span="24">
              <ValuationStockPickingResult />
            </el-col>
          </el-row>
        </div>
      </el-col>
      <el-col :span="4">
        <el-row>
          <el-col :span="24">
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
import DefaultLayout from "../layouts/DefaultLayout.vue";
import { ElRow, ElCol } from "element-plus";
import FinanceRelevant from "../components/FinanceRelevant.vue";
import GainLossQuant from "../components/GainLossQuant.vue";
import ValuationStockPickingFilter from "../components/ValuationStockPickingFilter.vue";
import ValuationStockPickingResult from "../components/ValuationStockPickingResult.vue";
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
</style>
