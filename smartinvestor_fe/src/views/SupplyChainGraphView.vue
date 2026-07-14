<template>
  <div class="scm-view-root">
    <section class="scm-top-nav">
      <div class="nav-left">
        <div class="logo">A</div>
        <div>
          <span class="brand">A股洞察</span>
          <span class="sub">读懂每一家公司</span>
        </div>
      </div>
      <div class="nav-right">
        <span class="nav-link">财务体检</span>
        <span class="nav-link">历史回溯</span>
        <span class="nav-link active">产业链拆解</span>
        <span class="nav-link">预警中心</span>
        <span class="nav-link">我的组合</span>
        <button class="btn-pro">升级 Pro</button>
        <div class="avatar">用</div>
      </div>
    </section>

    <section class="page-header">
      <div>
        <h2>供应链上下游图谱</h2>
        <p>参考 AStock_SCM 设计风格，提供公司级上下游关系可视化与证据面板。</p>
      </div>
      <div class="header-actions">
        <button class="btn ghost">导出图谱</button>
        <button class="btn primary" @click="fetchGraph">刷新关系</button>
      </div>
    </section>

    <section class="layout-grid">
      <aside class="panel card left-panel">
        <h3 class="card-title">筛选与候选</h3>
        <label class="field-label">目标公司</label>
        <div class="input-row">
          <el-autocomplete
            v-model="query.tsCode"
            :fetch-suggestions="querySearchAsync"
            placeholder="例如 300750.SZ 或 宁德时代"
            :trigger-on-focus="true"
            clearable
            @select="handleSelect"
          >
            <template #default="{ item }">
              <div>
                <div>
                  <span style="font-weight: bold; color: #409eff; font-size: 13px">{{ item.name }} {{ item.ts_code }}</span>
                </div>
                <div>
                  <span style="color: #999; font-size: 12px">上市日期: {{ item.listdate || '-' }}</span>
                </div>
              </div>
            </template>
          </el-autocomplete>
          <button class="btn" @click="fetchGraph">查询</button>
        </div>

        <label class="field-label">关系视角</label>
        <div class="seg">
          <button :class="{ active: query.focus === 'all' }" @click="query.focus = 'all'">全部</button>
          <button :class="{ active: query.focus === 'up' }" @click="query.focus = 'up'">上游</button>
          <button :class="{ active: query.focus === 'down' }" @click="query.focus = 'down'">下游</button>
        </div>

        <label class="field-label">行业筛选</label>
        <select v-model="query.industry" class="industry-select">
          <option value="all">全部行业</option>
          <option v-for="item in industryOptions" :key="item" :value="item">{{ item }}</option>
        </select>

        <label class="field-label">快捷开关</label>
        <label class="quick-switch">
          <input v-model="query.onlyDirectional" type="checkbox" />
          <span>仅看上游/下游公司</span>
        </label>

        <label class="field-label">解析标签</label>
        <div class="tag-list">
          <span v-for="tag in candidateTags" :key="tag" class="chip">{{ tag }}</span>
          <span v-if="!candidateTags.length" class="muted">暂无标签</span>
        </div>

        <h4 class="sub-title">关系候选</h4>
        <div class="candidate-list">
          <div v-for="row in filteredCandidates" :key="row.id" class="candidate-item">
            <div>
              <div class="candidate-name">{{ row.name }}</div>
              <div class="candidate-sub">{{ row.reason }}</div>
            </div>
            <span class="badge" :class="row.type">{{ row.typeText }}</span>
          </div>
          <div v-if="!filteredCandidates.length" class="muted">暂无候选关系</div>
        </div>
      </aside>

      <main class="canvas card">
        <div class="canvas-head">
          <h3>关系画布</h3>
          <span>
            当前中心：{{ centerCompany.name }}（{{ centerCompany.tsCode }}）
            <template v-if="centerCompany.industry"> · {{ centerCompany.industry }}</template>
          </span>
        </div>
        <div class="canvas-body">
          <div v-if="loading" class="overlay-msg">图谱计算中...</div>
          <div v-else-if="error" class="overlay-msg error">{{ error }}</div>

          <div class="node center" style="left: 420px; top: 230px">
            <div class="node-title">{{ centerCompany.name }}</div>
            <div class="node-meta">
              {{ centerCompany.tsCode }} · 中心公司
              <template v-if="centerCompany.industry"> · {{ centerCompany.industry }}</template>
            </div>
          </div>

          <div v-for="node in canvasNodes" :key="node.id" class="node" :class="node.type" :style="{ left: node.left, top: node.top }">
            <div class="node-title">
              {{ node.title }}
              <span class="node-direction" :class="node.type">{{ node.directionText }}</span>
            </div>
            <div class="node-meta">{{ node.meta }}</div>
          </div>
        </div>
      </main>

      <aside class="panel card">
        <h3 class="card-title">证据与置信度</h3>
        <div class="kv-row">
          <span>数据源</span>
          <strong>{{ sourceModesText }}</strong>
        </div>
        <div class="kv-row">
          <span>置信度门槛</span>
          <strong>{{ query.minConfidence }}</strong>
        </div>
        <div class="kv-row">
          <span>更新时间</span>
          <strong>{{ asofText }}</strong>
        </div>
        <div class="kv-row" v-if="mainbizStatusText">
          <span>MAINBIZ</span>
          <strong>{{ mainbizStatusText }}</strong>
        </div>

        <h4 class="sub-title">关系明细</h4>
        <div class="evidence-group-list" v-if="evidenceGroups.length">
          <div v-for="group in evidenceGroups" :key="group.source" class="evidence-group-card">
            <div class="evidence-group-title">
              <span>{{ group.label }}</span>
              <span class="evidence-group-count">{{ group.items.length }}</span>
            </div>
            <div class="evidence-list">
              <div v-for="ev in group.items" :key="ev.id" class="evidence-item">
                <div class="evidence-top">
                  <span>{{ ev.target }}</span>
                  <span class="confidence" :class="ev.level">{{ ev.levelText }}</span>
                </div>
                <div class="evidence-sub">{{ ev.source }} · {{ ev.hit }}</div>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="muted">暂无证据明细</div>
      </aside>
    </section>

    <footer class="scm-footer">
      <span>上下游拆解模块 · AStock_SCM 视觉规范</span>
      <span>Data as of {{ asofText }}</span>
    </footer>
  </div>
</template>

<script setup lang="ts">
import axios from 'axios'
import { computed, inject, onMounted, reactive, ref } from 'vue'
import { ElAutocomplete } from 'element-plus'

type GraphNode = { id: string; type: string; label: string; meta?: Record<string, any> }
type GraphEdge = {
  source: string
  target: string
  relation: string
  confidence?: number
  evidence_source?: string
  evidence_text?: string
}

type CorporationSuggestion = {
  ts_code: string
  name: string
  listdate?: string
}

const query = reactive({
  tsCode: '300750.SZ',
  focus: 'all' as 'all' | 'up' | 'down',
  industry: 'all',
  onlyDirectional: false,
  minConfidence: 0.35,
})

const baseURL = inject<string>('baseURL') || 'http://127.0.0.1:5001/api'
const loading = ref(false)
const error = ref('')
const asofText = ref('-')
const sourceModes = ref<string[]>([])

const graphNodes = ref<GraphNode[]>([])
const graphEdges = ref<GraphEdge[]>([])

const centerCompany = reactive({
  name: '-',
  tsCode: query.tsCode,
  industry: '',
})

const sourceModesText = computed(() => {
  if (!sourceModes.value.length) return 'business_scope + bz_item + concept_detail'
  return sourceModes.value.join(' | ')
})

const mainbizStatusText = computed(() => {
  if (!sourceModes.value.length) return ''
  return sourceModes.value.includes('fina_mainbz_empty') ? '无本地行，实时拉取+业务文本补偿' : '可用'
})

const candidateTags = computed(() => {
  return graphNodes.value
    .filter((n) => n.type === 'tag')
    .slice(0, 20)
    .map((n) => n.label)
})

const candidates = computed(() => {
  const rows: Array<{ id: string; name: string; tsCode: string; industry: string; reason: string; type: 'up' | 'down' | 'peer'; typeText: string }> = []
  graphNodes.value
    .filter((n) => n.type === 'company_related')
    .forEach((n) => {
      const meta = (n.meta || {}) as any
      const type = (meta.direction || 'peer') as 'up' | 'down' | 'peer'
      const conceptHits = Array.isArray(meta.concept_hits) ? meta.concept_hits : []
      const hitKeywords = Array.isArray(meta.hit_keywords) ? meta.hit_keywords : []
      const reasonParts = []
      if (conceptHits.length) reasonParts.push(`概念: ${conceptHits.slice(0, 2).join(' / ')}`)
      if (hitKeywords.length) reasonParts.push(`关键词: ${hitKeywords.slice(0, 2).join(' / ')}`)
      rows.push({
        id: n.id,
        name: n.label,
        tsCode: String(meta.ts_code || ''),
        industry: String(meta.industry || ''),
        reason: reasonParts.join(' | ') || '概念映射推断',
        type,
        typeText: type === 'up' ? '上游' : type === 'down' ? '下游' : '同链',
      })
    })
  return rows.slice(0, 40)
})

const filteredCandidates = computed(() => {
  let rows = candidates.value
  if (query.focus !== 'all') {
    rows = rows.filter((item) => item.type === query.focus)
  }
  if (query.onlyDirectional) {
    rows = rows.filter((item) => item.type === 'up' || item.type === 'down')
  }
  if (query.industry !== 'all') {
    rows = rows.filter((item) => String(item.industry || '').trim() === query.industry)
  }
  return rows
})

const industryOptions = computed(() => {
  const set = new Set<string>()
  candidates.value.forEach((item) => {
    const name = String(item.industry || '').trim()
    if (name) set.add(name)
  })
  return Array.from(set).sort((a, b) => a.localeCompare(b, 'zh-CN'))
})

const displayCompanies = computed(() => {
  const up = filteredCandidates.value.filter((r) => r.type === 'up').slice(0, 3)
  const down = filteredCandidates.value.filter((r) => r.type === 'down').slice(0, 3)
  const peer = filteredCandidates.value.filter((r) => r.type === 'peer').slice(0, 2)
  return { up, down, peer }
})

const canvasNodes = computed(() => {
  const rows: Array<{
    id: string
    title: string
    meta: string
    type: 'up' | 'down' | 'peer'
    left: string
    top: string
    directionText: string
  }> = []
  const distributeX = (idx: number, total: number, minX = 90, maxX = 750) => {
    if (total <= 1) return `${(minX + maxX) / 2}px`
    const step = (maxX - minX) / (total - 1)
    return `${Math.round(minX + idx * step)}px`
  }

  // Layout rule: upstream at top band, peer at middle horizontal band, downstream at bottom band.
  displayCompanies.value.up.forEach((u, i) => {
    rows.push({
      id: `up-${u.id}`,
      title: u.name,
      meta: `${u.tsCode}${u.industry ? ` · ${u.industry}` : ''}`,
      type: 'up',
      left: distributeX(i, displayCompanies.value.up.length),
      top: '72px',
      directionText: '上游公司',
    })
  })
  displayCompanies.value.down.forEach((d, i) => {
    rows.push({
      id: `down-${d.id}`,
      title: d.name,
      meta: `${d.tsCode}${d.industry ? ` · ${d.industry}` : ''}`,
      type: 'down',
      left: distributeX(i, displayCompanies.value.down.length),
      top: '420px',
      directionText: '下游公司',
    })
  })
  displayCompanies.value.peer.forEach((p, i) => {
    rows.push({
      id: `peer-${p.id}`,
      title: p.name,
      meta: `${p.tsCode}${p.industry ? ` · ${p.industry}` : ''}`,
      type: 'peer',
      left: distributeX(i, displayCompanies.value.peer.length, 140, 700),
      top: '250px',
      directionText: '同链公司',
    })
  })
  return rows
})

const querySearchAsync = (queryString: string, cb: (arg: CorporationSuggestion[]) => void) => {
  const q = String(queryString || '').trim()
  if (!q) {
    cb([])
    return
  }
  axios
    .get(`${baseURL}/corporations/${encodeURIComponent(q)}/`)
    .then((res) => {
      const rows = Array.isArray(res?.data?.data) ? res.data.data : []
      cb(
        rows
          .filter((item: any) => item && item.ts_code && item.name)
          .map((item: any) => ({
            ts_code: String(item.ts_code),
            name: String(item.name),
            listdate: item.listdate ? String(item.listdate) : '',
          }))
      )
    })
    .catch(() => cb([]))
}

const handleSelect = (item: Record<string, any>) => {
  query.tsCode = String(item.ts_code || '').trim().toUpperCase()
  void fetchGraph()
}

const evidences = computed(() => {
  return graphEdges.value.slice(0, 40).map((e, idx) => {
    const c = Number(e.confidence || 0)
    const level = c >= 0.75 ? 'high' : c >= 0.55 ? 'mid' : 'low'
    return {
      id: `e-${idx}`,
      target: `${e.relation}`,
      source: e.evidence_source || 'unknown',
      hit: e.evidence_text || '-',
      level,
      levelText: level === 'high' ? '高' : level === 'mid' ? '中' : '低',
    }
  })
})

function sourceGroupLabel(source: string) {
  const s = String(source || '').toLowerCase()
  if (s.includes('fina_mainbz')) return '主营构成 (fina_mainbz)'
  if (s.includes('business_scope') || s.includes('stock_company')) return '经营范围 (stock_company)'
  if (s.includes('concept_detail')) return '概念映射 (concept_detail)'
  if (s.includes('concept_catalog_fallback')) return '概念回退 (concept目录匹配)'
  if (s.includes('concept_rule_fallback')) return '概念回退 (规则匹配)'
  if (s.includes('chain')) return '产业链层级规则'
  return source || 'unknown'
}

const evidenceGroups = computed(() => {
  const grouped = new Map<string, Array<(typeof evidences.value)[number]>>()
  evidences.value.forEach((item) => {
    const key = String(item.source || 'unknown')
    if (!grouped.has(key)) grouped.set(key, [])
    grouped.get(key)!.push(item)
  })

  return Array.from(grouped.entries())
    .map(([source, items]) => ({
      source,
      label: sourceGroupLabel(source),
      items,
    }))
    .sort((a, b) => b.items.length - a.items.length)
})

async function fetchGraph() {
  const tsCode = String(query.tsCode || '').trim().toUpperCase()
  if (!tsCode) {
    error.value = '请输入 ts_code'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const res = await axios.get(`${baseURL}/supply-chain/graph/`, {
      params: {
        ts_code: tsCode,
        min_confidence: query.minConfidence,
        include_concepts: true,
        include_layers: true,
      },
      timeout: 30000,
    })
    const data = res?.data?.data || {}
    centerCompany.name = String(data?.center?.name || tsCode)
    centerCompany.tsCode = String(data?.center?.ts_code || tsCode)
    centerCompany.industry = String(data?.center?.industry || '')
    graphNodes.value = Array.isArray(data?.nodes) ? data.nodes : []
    graphEdges.value = Array.isArray(data?.edges) ? data.edges : []
    sourceModes.value = Array.isArray(data?.trace?.source_modes) ? data.trace.source_modes : []
    asofText.value = String(data?.trace?.asof || '-')
  } catch (e: any) {
    error.value = String(e?.response?.data?.error || e?.message || '图谱请求失败')
    graphNodes.value = []
    graphEdges.value = []
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchGraph()
})
</script>

<style scoped>
.scm-view-root {
  --bg: #f8fafc;
  --card: #ffffff;
  --text: #0f172a;
  --muted: #64748b;
  --muted2: #94a3b8;
  --border: #e2e8f0;
  --border2: #f1f5f9;
  --nav: #0f172a;
  --blue: #2563eb;
  --blue2: #1e40af;
  --blue-bg: #eff6ff;
  --green: #10b981;
  --amber: #f59e0b;
  --shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  --shadow2: 0 8px 24px rgba(15, 23, 42, 0.1);
  --r16: 16px;
  --r12: 12px;
  --r10: 10px;

  padding: 0;
  height: calc(100vh - 72px);
  background: var(--bg);
  display: flex;
  flex-direction: column;
  gap: 0;
  overflow: hidden;
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;

  width: 100%;
  margin: 0;
}

:global(.el-main) {
  padding: 0 !important;
  overflow-x: hidden;
}

.scm-top-nav {
  height: 60px;
  background: var(--nav);
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
  flex: 0 0 auto;
}

.nav-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--blue);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  color: #fff;
  font-size: 14px;
}

.brand {
  color: #fff;
  font-weight: 800;
  font-size: 18px;
}

.sub {
  color: #94a3b8;
  font-size: 12px;
  margin-left: 6px;
}

.nav-right {
  display: flex;
  align-items: center;
  gap: 18px;
}

.nav-link {
  color: #cbd5e1;
  font-size: 13px;
  line-height: 1;
}

.nav-link.active {
  color: #fff;
  border-bottom: 2px solid var(--blue);
  padding-bottom: 2px;
}

.btn-pro {
  background: var(--blue);
  color: #fff;
  border: 0;
  padding: 7px 14px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  font-weight: 600;
}

.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: #475569;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 12px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
  padding: 22px 24px;
  border-radius: 0;
  background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
  color: #e2e8f0;
  flex: 0 0 auto;
}

.layout-grid {
  margin-left: 24px;
  margin-right: 24px;
}

.page-header h2 {
  margin: 0 0 6px 0;
  font-size: 22px;
  font-weight: 800;
  letter-spacing: 0.2px;
}

.page-header p {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: #a5b4fc;
}

.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.layout-grid {
  display: grid;
  grid-template-columns: 320px 1fr 340px;
  gap: 16px;
  flex: 1 1 auto;
  height: 100%;
  padding-bottom: 16px;
  box-sizing: border-box;
  min-height: 0;
  align-items: stretch;
  margin-top: 16px;
  margin-bottom: 16px;
}

.scm-footer {
  height: 36px;
  color: var(--muted);
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  padding: 0 24px;
  flex: 0 0 auto;
}

.card {
  background: var(--card);
  border: 1px solid var(--border2);
  border-radius: var(--r16);
  box-shadow: var(--shadow);
}

.panel {
  padding: 16px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
}

.left-panel {
  overflow-y: auto;
  overflow-x: hidden;
}

.card-title {
  margin: 0 0 12px 0;
  font-size: 14px;
  font-weight: 800;
}

.field-label,
.sub-title {
  display: block;
  margin: 10px 0 6px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
  flex-shrink: 0;
}

.input-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.input-row :deep(.el-autocomplete) {
  width: 100%;
  min-width: 0;
}

input[type='text'] {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: var(--r12);
  padding: 10px 12px;
  font-size: 13px;
}

input[type='text']:focus {
  outline: none;
  border-color: rgba(37, 99, 235, 0.45);
  box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.12);
}

.btn {
  border: 1px solid var(--border);
  border-radius: var(--r12);
  padding: 10px 12px;
  background: #fff;
  color: var(--text);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: box-shadow 0.18s ease, transform 0.18s ease, background-color 0.18s ease;
}

.btn:hover {
  box-shadow: var(--shadow2);
  transform: translateY(-1px);
}

.btn.primary {
  border-color: var(--blue);
  background: var(--blue);
  color: #fff;
}

.btn.primary:hover {
  background: #1d4ed8;
}

.btn.ghost {
  background: transparent;
  color: #e2e8f0;
  border-color: rgba(226, 232, 240, 0.35);
}

.seg {
  display: flex;
  border: 1px solid var(--border);
  border-radius: var(--r12);
  min-height: 36px;
  align-items: center;
  background: #fff;
  overflow: hidden;
}

.seg button {
  flex: 1;
  min-height: 36px;
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 0;
  background: transparent;
  padding: 0 8px;
  font-size: 12px;
  color: var(--muted);
  font-weight: 800;
  white-space: nowrap;
}

.seg button.active {
  background: var(--blue-bg);
  color: var(--blue2);
}

.industry-select {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: var(--r12);
  padding: 10px 12px;
  font-size: 13px;
  color: var(--text);
  background: #fff;
  outline: none;
}

.quick-switch {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text);
  margin-top: 2px;
}

.quick-switch input[type='checkbox'] {
  width: 14px;
  height: 14px;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 24px;
  max-height: 90px;
  flex-shrink: 0;
  overflow: auto;
  padding-right: 4px;
}

.chip {
  border: 1px solid #dbeafe;
  background: #eff6ff;
  color: #1e40af;
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 700;
}

.muted {
  color: var(--muted2);
  font-size: 12px;
}

.candidate-list,
.evidence-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 1 1 auto;
  min-height: 0;
  max-height: none;
  overflow: auto;
  padding-right: 4px;
}

.evidence-group-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: none;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}

.evidence-group-card {
  border: 1px solid var(--border);
  border-radius: var(--r12);
  padding: 9px;
}

.evidence-group-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  font-weight: 700;
  margin-bottom: 6px;
  color: #334155;
}

.evidence-group-count {
  border: 1px solid #dbeafe;
  background: #eff6ff;
  color: #1d4ed8;
  border-radius: 999px;
  padding: 0 8px;
  font-size: 11px;
}

.candidate-item,
.evidence-item {
  border: 1px solid var(--border);
  border-radius: var(--r12);
  padding: 10px;
  background: #fff;
}

.candidate-name {
  font-size: 13px;
  font-weight: 900;
  line-height: 1.2;
}

.candidate-sub,
.evidence-sub {
  font-size: 11px;
  color: var(--muted);
  margin-top: 4px;
}

.badge {
  float: right;
  font-size: 10px;
  border-radius: 999px;
  border: 1px solid;
  padding: 2px 8px;
}

.badge.up {
  color: #059669;
  border-color: #a7f3d0;
  background: #ecfdf5;
}

.badge.down {
  color: #2563eb;
  border-color: #bfdbfe;
  background: #eff6ff;
}

.canvas {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
  height: 100%;
}

.canvas-head {
  padding: 13px 16px;
  border-bottom: 1px solid var(--border2);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.canvas-head h3 {
  margin: 0;
  font-size: 14px;
}

.canvas-head span {
  color: var(--muted);
  font-size: 12px;
}

.canvas-body {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  background: radial-gradient(circle at 1px 1px, rgba(148, 163, 184, 0.22) 1px, transparent 0) 0 0/18px 18px,
    #fff;
}

.overlay-msg {
  position: absolute;
  top: 10px;
  left: 10px;
  z-index: 2;
  background: rgba(15, 23, 42, 0.8);
  color: #e2e8f0;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 12px;
}

.overlay-msg.error {
  background: rgba(153, 27, 27, 0.9);
}

.node {
  position: absolute;
  min-width: 160px;
  border: 1px solid var(--border);
  border-radius: var(--r12);
  background: #fff;
  padding: 10px;
  box-shadow: var(--shadow);
}

.node.center {
  border-color: #bfdbfe;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.node.up {
  border-color: #a7f3d0;
}

.node.down {
  border-color: #bfdbfe;
}

.node-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 800;
}

.node-direction {
  border-radius: 999px;
  border: 1px solid;
  padding: 1px 7px;
  font-size: 10px;
  font-weight: 700;
  white-space: nowrap;
}

.node-direction.up {
  color: #059669;
  border-color: #a7f3d0;
  background: #ecfdf5;
}

.node-direction.down {
  color: #2563eb;
  border-color: #bfdbfe;
  background: #eff6ff;
}

.node-direction.peer {
  color: #475569;
  border-color: #cbd5e1;
  background: #f8fafc;
}

.node-meta {
  font-size: 11px;
  color: var(--muted);
  margin-top: 3px;
}

.kv-row {
  display: grid;
  grid-template-columns: 90px 1fr;
  gap: 8px;
  font-size: 12px;
  margin-bottom: 7px;
}

.kv-row span {
  color: var(--muted);
}

.evidence-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  font-weight: 700;
}

.confidence {
  border-radius: 999px;
  padding: 1px 7px;
  border: 1px solid;
  font-size: 10px;
}

.confidence.high {
  color: #059669;
  border-color: #a7f3d0;
  background: #ecfdf5;
}

.confidence.mid {
  color: #2563eb;
  border-color: #bfdbfe;
  background: #eff6ff;
}

.confidence.low {
  color: #b45309;
  border-color: #fcd34d;
  background: #fffbeb;
}

@media (max-width: 1360px) {
  .scm-view-root {
    height: auto;
    min-height: calc(100vh - 72px);
    overflow: visible;
    padding: 0;

    width: 100%;
    margin: 0;
  }

  .scm-top-nav {
    padding: 0 16px;
  }

  .nav-right {
    gap: 10px;
  }

  .nav-link {
    display: none;
  }

  .layout-grid {
    grid-template-columns: 1fr;
    flex: 0 0 auto;
    gap: 14px;
  }

  .layout-grid {
    margin-left: 16px;
    margin-right: 16px;
  }

  .scm-footer {
    padding: 0 16px;
  }

  .canvas-body {
    height: 520px;
    min-height: 520px;
  }
}
</style>
