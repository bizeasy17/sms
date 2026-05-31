<template>
  <div v-if="visible" class="recent-report-badge-wrap">
    <el-tag
      class="recent-report-badge"
      type="danger"
      effect="light"
      size="small"
      round
    >
      新
    </el-tag>
    <span v-if="labelText" class="recent-report-label">{{ labelText }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ElTag } from 'element-plus'

const props = defineProps<{
  visible?: boolean
  label?: string | null
}>()

const visible = computed(() => Boolean(props.visible))
const labelText = computed(() => {
  const text = String(props.label || '').trim().toUpperCase()
  if (text === 'EXP') {
    return '快'
  }
  return text || ''
})
</script>

<style scoped>
.recent-report-badge-wrap {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.recent-report-badge {
  margin-left: 6px;
  padding-left: 6px;
  padding-right: 6px;
  font-weight: 600;
  line-height: 1;
}

.recent-report-label {
  font-size: 11px;
  font-weight: 600;
  color: #c45656;
  line-height: 1;
}
</style>