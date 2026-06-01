<template>
  <DefaultLayout>
    <div class="schedule-jobs-page">
      <el-card shadow="never" class="intro-card">
        <template #header>
          <div class="card-header">
            <span>调度总览</span>
            <el-tag type="info" effect="plain">用于理解 UAT 定时任务与执行链路</el-tag>
          </div>
        </template>

        <div class="intro-grid">
          <div class="intro-item">
            <div class="label">根调度入口</div>
            <div class="value">daily / weekly / monthly / quarterly</div>
          </div>
          <div class="intro-item">
            <div class="label">根任务触发时间</div>
            <div class="value">默认 21:30（Windows Task Scheduler）</div>
          </div>
          <div class="intro-item">
            <div class="label">预测快照锚点</div>
            <div class="value">ANN（非 live）</div>
          </div>
          <div class="intro-item">
            <div class="label">低频全量补刷日</div>
            <div class="value">每月 1 日（monthday=1）</div>
          </div>
        </div>
      </el-card>

      <el-card shadow="never" class="table-card">
        <template #header>
          <div class="card-header">
            <span>根 Schedule 任务</span>
            <span class="muted">来自 setup_uat_root_schedule_tasks.ps1</span>
          </div>
        </template>

        <el-table :data="rootJobs" stripe border size="small">
          <el-table-column prop="jobName" label="任务名" min-width="210" />
          <el-table-column prop="frequency" label="频率" width="120" />
          <el-table-column prop="trigger" label="触发" min-width="180" />
          <el-table-column prop="entry" label="入口脚本" min-width="220" />
          <el-table-column prop="purpose" label="主要功能" min-width="320" show-overflow-tooltip />
        </el-table>
      </el-card>

      <el-card shadow="never" class="table-card">
        <template #header>
          <div class="card-header">
            <span>关键子任务链路（摘要）</span>
            <span class="muted">帮助理解每个根任务内部在做什么</span>
          </div>
        </template>

        <el-table :data="subJobs" stripe border size="small">
          <el-table-column prop="scope" label="所属链路" width="170" />
          <el-table-column prop="step" label="子任务" min-width="240" />
          <el-table-column prop="frequency" label="频率" width="120" />
          <el-table-column prop="detail" label="说明" min-width="420" show-overflow-tooltip />
        </el-table>
      </el-card>

      <el-card shadow="never" class="table-card">
        <template #header>
          <div class="card-header">
            <span>传统估值与市场信息</span>
            <span class="muted">运维视角：何时刷新、为何刷新、异常时看哪里</span>
          </div>
        </template>

        <div class="insight-list">
          <div class="insight-item">
            <div class="insight-title">何时刷新</div>
            <div class="insight-text">日常按披露增量刷新（disclosure-only）；每月 1 日执行一次全量兜底（all），由 UAT daily.bat 的 TRADITIONAL_CANDIDATE_POLICY 控制。</div>
          </div>
          <div class="insight-item">
            <div class="insight-title">为何这样设计</div>
            <div class="insight-text">传统估值已吸收价格、行业模板历史分布和财报/快报信息。保持模板层稳定，能避免频繁切换估值口径并提升可解释性。</div>
          </div>
          <div class="insight-item">
            <div class="insight-title">异常时先看哪里</div>
            <div class="insight-text">先看根调度是否触发（Schedule / daily.bat），再看 smartinvestor_be/earnings_refresh.bat 中 CANDIDATE_POLICY 与 REFRESH_POLICY 是否符合预期，最后核对日志时间点是否落在月度兜底窗口。</div>
          </div>
        </div>
      </el-card>
    </div>
  </DefaultLayout>
</template>

<script setup lang="ts">
import { ElCard, ElTable, ElTableColumn, ElTag } from 'element-plus'
import DefaultLayout from '../layouts/DefaultLayout.vue'

type RootJobRow = {
  jobName: string
  frequency: string
  trigger: string
  entry: string
  purpose: string
}

type SubJobRow = {
  scope: string
  step: string
  frequency: string
  detail: string
}

const rootJobs: RootJobRow[] = [
  {
    jobName: 'UAT Daily Pipeline',
    frequency: '每日',
    trigger: 'Task Scheduler: DAILY 21:30',
    entry: 'UAT/daily.bat',
    purpose: 'ETL 日更 + Earnings 周期窗口增量刷新 + 传统估值披露驱动预填（每月全量兜底） + 风险预填',
  },
  {
    jobName: 'UAT Weekly Pipeline',
    frequency: '每周',
    trigger: 'Task Scheduler: WEEKLY(FRI) 21:30',
    entry: 'UAT/weekly.bat',
    purpose: '周频重采样、周频拉数、基金持仓同步、估值到期任务与低估导出',
  },
  {
    jobName: 'UAT Monthly Pipeline',
    frequency: '每月',
    trigger: 'Task Scheduler: MONTHLY(day=1) 21:30',
    entry: 'UAT/monthly.bat',
    purpose: '月频 ETL 重采样与 BE 月度数据拉取',
  },
  {
    jobName: 'UAT Quarterly Pipeline',
    frequency: '每季度',
    trigger: 'Task Scheduler: MONTHLY(MO=3, day=1) 21:30',
    entry: 'UAT/quarterly.bat',
    purpose: 'Earnings 季度全链路、BE earnings backfill 与 annual outlook',
  },
]

const subJobs: SubJobRow[] = [
  {
    scope: 'Daily',
    step: 'daily_financial_periodic_refresh',
    frequency: '每日',
    detail: '按披露变化增量处理财务与特征，并刷新 signal snapshot（anchor=ANN）',
  },
  {
    scope: 'Daily',
    step: 'regime-trigger full refresh',
    frequency: '事件触发',
    detail: '市场风格切换时触发 full refresh（LATEST,FUSION，仍走 ANN 锚点）',
  },
  {
    scope: 'Daily',
    step: 'low-frequency full refresh',
    frequency: '每月一次',
    detail: 'LOW_FREQ_FULL_REFRESH_MONTHDAY=1，作为低频全量兜底补刷（不再每周 full refresh）',
  },
  {
    scope: 'Daily',
    step: 'traditional valuation prefill',
    frequency: '每日增量 + 每月全量',
    detail: 'daily.bat 默认 CANDIDATE_POLICY=disclosure-only，仅在每月兜底日切换为 all',
  },
  {
    scope: 'Weekly',
    step: 'weekly_undervalued_friday',
    frequency: '每周',
    detail: '导出传统/预测低估标的 CSV，便于周度筛选复盘',
  },
  {
    scope: 'Quarterly',
    step: 'quarterly_full_pipeline',
    frequency: '每季度',
    detail: '季度链路以 ETL + monthly_financial_maintenance 为主，signal 刷新已下沉到 daily 周期任务',
  },
]
</script>

<style scoped>
.schedule-jobs-page {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.intro-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
}

.intro-item {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px;
  background: #fafcff;
}

.intro-item .label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}

.intro-item .value {
  font-size: 14px;
  color: #303133;
  font-weight: 600;
}

.muted {
  color: #909399;
  font-size: 12px;
}

.insight-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.insight-item {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 12px;
  background: #fffdf7;
}

.insight-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 4px;
}

.insight-text {
  font-size: 13px;
  line-height: 1.6;
  color: #606266;
}
</style>
