<template>
  <el-card class="openclaw-assistant-card">
    <template #header>
      <div class="assistant-header">
        <span class="assistant-title">OpenClaw 投资助手</span>
        <el-switch
          v-model="forwardToFeishu"
          active-text="同步飞书"
          inactive-text="仅本地"
          size="small"
        />
      </div>
    </template>

    <div class="chat-window">
      <div v-if="messages.length === 0" class="placeholder">
        试试自然语言提问，例如：
        “600519.SH 现在估值高不高？”
      </div>
      <div v-for="item in messages" :key="item.id" class="chat-item" :class="item.role">
        <div class="chat-role">{{ item.role === 'user' ? '我' : '助手' }}</div>
        <div class="chat-content">{{ item.content }}</div>
      </div>
    </div>

    <el-input
      v-model="inputText"
      type="textarea"
      :rows="3"
      placeholder="输入问题，例如：这只股票现在适合分批买吗？"
      @keyup.enter.ctrl="submitQuestion"
    />

    <div class="assistant-actions">
      <el-button type="primary" :loading="loading" @click="submitQuestion">
        发送
      </el-button>
      <el-text type="info" size="small">Ctrl+Enter 快速发送</el-text>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import axios from 'axios'
import { inject, ref } from 'vue'
import { ElButton, ElCard, ElInput, ElMessage, ElSwitch, ElText } from 'element-plus'
import { useStockTradeStore } from '../stores/stockTradeStore'
import { useStockChartFilterStore } from '../stores/stockChartFilterStore'

type ChatMessage = {
  id: number
  role: 'user' | 'assistant'
  content: string
}

const baseURL = inject<string>('baseURL', '')
const stockTradeStore = useStockTradeStore()
const stockChartFilterStore = useStockChartFilterStore()

const inputText = ref('')
const loading = ref(false)
const forwardToFeishu = ref(false)
const messages = ref<ChatMessage[]>([])
let idCounter = 1

function appendMessage(role: 'user' | 'assistant', content: string) {
  messages.value.push({
    id: idCounter++,
    role,
    content,
  })
}

async function submitQuestion() {
  const message = inputText.value.trim()
  if (!message) {
    ElMessage.warning('请先输入问题')
    return
  }
  if (!baseURL) {
    ElMessage.error('baseURL 未配置')
    return
  }

  appendMessage('user', message)
  inputText.value = ''
  loading.value = true

  try {
    const res = await axios.post(`${baseURL}/openclaw/valuation/chat/`, {
      message,
      ts_code: stockTradeStore.tsCode,
      freq: stockChartFilterStore.freq || 'D',
      forward_to_feishu: forwardToFeishu.value,
    })

    const answer = String(res.data?.answer || '助手未返回内容')
    appendMessage('assistant', answer)

    if (forwardToFeishu.value && res.data?.feishu_error) {
      ElMessage.warning(`飞书转发失败: ${res.data.feishu_error}`)
    }
  } catch (error: any) {
    const errorText = String(error?.response?.data?.error || error?.message || '请求失败')
    appendMessage('assistant', `请求失败: ${errorText}`)
    ElMessage.error(errorText)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.openclaw-assistant-card {
  margin-top: 12px;
}

.assistant-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.assistant-title {
  font-weight: 600;
}

.chat-window {
  max-height: 240px;
  overflow-y: auto;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 10px;
  background: #fafafa;
}

.placeholder {
  color: #909399;
  font-size: 12px;
  line-height: 1.6;
}

.chat-item {
  margin-bottom: 10px;
}

.chat-item:last-child {
  margin-bottom: 0;
}

.chat-role {
  font-size: 12px;
  color: #909399;
  margin-bottom: 2px;
}

.chat-content {
  white-space: pre-wrap;
  line-height: 1.5;
  font-size: 13px;
  color: #303133;
}

.chat-item.user .chat-content {
  color: #1f2329;
}

.assistant-actions {
  margin-top: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
