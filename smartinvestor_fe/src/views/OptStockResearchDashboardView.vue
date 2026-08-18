<script setup lang="ts">
import { computed, inject, onMounted, ref } from 'vue';
import OptResearchDossier from '../modules/opt-stock-research/OptResearchDossier.vue';
import OptResearchRail from '../modules/opt-stock-research/OptResearchRail.vue';
import { researchCompanies, type ResearchCompany } from '../modules/opt-stock-research/researchData';

const selectedCompany = ref<ResearchCompany>(researchCompanies[0]);
const companies = ref<ResearchCompany[]>([]);
const searchText = ref('');
const drawerOpen = ref(false);
const observationLoading = ref(false);
const observationError = ref('');
const baseURL = inject<string>('baseURL', 'http://127.0.0.1:5001/api');
const filteredCompanies = computed(() => {
    const keyword = searchText.value.trim().toLowerCase();
    if (!keyword) return companies.value;
    return companies.value.filter((company) => `${company.name} ${company.code} ${company.industry}`.toLowerCase().includes(keyword));
});

async function loadObservationCompanies() {
    observationLoading.value = true;
    observationError.value = '';
    try {
        const response = await fetch(`${baseURL}/opt/v1/stock-observation/?limit=200`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        if (!Array.isArray(payload?.items)) throw new Error('Invalid stock observation payload');
        const mappedCompanies: ResearchCompany[] = payload.items.map((item: { ts_code?: string; name?: string; industry?: string; tags?: string[]; is_holding?: boolean }) => ({
            name: String(item.name || item.ts_code || ''),
            code: String(item.ts_code || ''),
            industry: String(item.industry || '行业待补充'),
            tags: Array.isArray(item.tags) ? item.tags.map(String) : [],
            isHolding: Boolean(item.is_holding),
            price: '—',
            change: '数据待接入',
            verdict: '观察中',
            thesis: '观察股票的详细研究数据尚未接入本优化模块。',
            position: '待评估',
        }));
        companies.value = mappedCompanies.sort((left, right) => Number(right.isHolding) - Number(left.isHolding));
        selectedCompany.value = companies.value[0] || researchCompanies[0];
    } catch {
        companies.value = [];
        observationError.value = '观察与持仓股票暂时不可用。';
    } finally {
        observationLoading.value = false;
    }
}

function selectCompany(company: ResearchCompany) {
    selectedCompany.value = company;
    drawerOpen.value = false;
}

onMounted(loadObservationCompanies);
</script>

<template>
    <div class="research-workspace">
        <header class="topbar">
            <button class="menu-toggle" :class="{ active: drawerOpen }" type="button" aria-label="打开股票列表" :aria-expanded="drawerOpen" @click="drawerOpen = !drawerOpen"><span/><span/><span/></button>
            <div class="brand"><span>J</span>Jiu Cai</div>
            <nav class="global-nav" aria-label="全局导航"><b>研究</b><span>发现</span><span>行业</span><span>组合</span></nav>
            <label class="search"><span>⌕</span><input v-model="searchText" aria-label="搜索公司、代码或主题" placeholder="搜索公司、代码或主题"></label>
            <div class="avatar" aria-label="当前用户" />
        </header>
        <div class="backdrop" :class="{ open: drawerOpen }" @click="drawerOpen = false" />
        <div class="workspace">
            <div :class="{ 'rail-wrapper': true, open: drawerOpen }"><OptResearchRail :companies="filteredCompanies" :selected-code="selectedCompany.code" :loading="observationLoading" :error-message="observationError" @select="selectCompany" /></div>
            <OptResearchDossier :company="selectedCompany" />
            <aside class="facts"><h3>研究事件</h3><article><time>08-15 · 财报更新</time><b>2026 年半年度报告已入库</b><p>核心利润表、现金流与指标快照已同步至估值模型。</p></article><article><time>08-12 · 模型信号</time><b>预测估值转为“高位”</b><p>H1 口径下，目标价与现价的风险收益比收窄。</p></article><article><time>08-08 · 技术趋势</time><b>价格站上 MA60</b><p>波动率走低，未出现加仓触发信号。</p></article><div class="risk"><h4>需要验证</h4><p>海外渠道修复节奏、H2 毛利率、应收账款周转变化。</p></div></aside>
        </div>
    </div>
</template>

<style scoped>
:global(html), :global(body), :global(#app) { margin: 0; min-height: 100%; padding: 0; }.research-workspace { background: #f7f9fc; color: #182536; font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif; min-height: 100vh; }.topbar { align-items: center; background: #fff; border-bottom: 1px solid #e3e9f1; box-sizing: border-box; display: flex; gap: 24px; height: 56px; left: 0; padding: 0 28px; position: fixed; top: 0; width: 100%; z-index: 31; }.brand { font: 700 18px Georgia, 'Noto Sans SC', serif; white-space: nowrap; }.brand span { background: #315bce; border-radius: 50%; color: #fff; display: inline-grid; font: 700 13px 'DM Mono', monospace; height: 23px; margin-right: 8px; place-items: center; width: 23px; }.global-nav { color: #7b899c; display: flex; gap: 22px; }.global-nav b { color: #182536; }.search { align-items: center; border: 1px solid #e1e7ef; border-radius: 5px; display: flex; gap: 7px; margin-left: auto; padding: 7px 10px; width: 260px; }.search input { border: 0; color: #243446; font: inherit; min-width: 0; outline: 0; width: 100%; }.avatar { background: linear-gradient(135deg, #ffc67d, #9b5f3e); border: 2px solid #e6ebf2; border-radius: 50%; height: 29px; width: 29px; }.workspace { display: grid; grid-template-columns: 238px minmax(600px, 1fr) 292px; min-height: calc(100vh - 56px); padding-top: 56px; }.rail-wrapper { bottom: 0; height: auto; left: 0; position: fixed; top: 56px; width: 238px; z-index: 20; }.rail-wrapper :deep(.research-rail) { height: 100%; }.workspace > :deep(.dossier) { grid-column: 2; }.facts { background: #fff; border-left: 1px solid #e3e9f1; grid-column: 3; grid-row: 1; min-height: calc(100vh - 56px); padding: 27px 22px; }.facts h3 { font-size: 15px; margin: 0 0 14px; }.facts article { border-bottom: 1px solid #e8edf3; padding: 14px 0; }.facts time { color: #8190a5; display: block; font-size: 11px; margin-bottom: 7px; }.facts b { font-size: 13px; }.facts p { color: #748398; font-size: 12px; line-height: 1.7; margin: 6px 0 0; }.risk { background: #fff7ea; border-left: 3px solid #d49a3c; margin-top: 20px; padding: 12px; }.risk h4 { font-size: 12px; margin: 0; }.menu-toggle, .backdrop { display: none; }
@media (max-width: 980px) { .workspace { grid-template-columns: 238px minmax(0, 1fr); }.facts { display: none; } }
@media (max-width: 700px) { .topbar { gap: 9px; height: 52px; padding: 0 16px; }.workspace { display: block; padding-top: 52px; }.global-nav { display: none; }.menu-toggle { background: transparent; border: 0; cursor: pointer; display: block; padding: 6px 4px; width: 30px; }.menu-toggle span { background: #243446; display: block; height: 2px; margin: 4px 0; transition: .2s; }.menu-toggle.active span:nth-child(1) { transform: translateY(6px) rotate(45deg); }.menu-toggle.active span:nth-child(2) { opacity: 0; }.menu-toggle.active span:nth-child(3) { transform: translateY(-6px) rotate(-45deg); }.search { flex: 1; margin-left: 0; width: auto; }.avatar { flex: 0 0 auto; }.rail-wrapper { height: auto; position: static; width: auto; }.rail-wrapper.open :deep(.research-rail) { transform: translateX(0); }.backdrop.open { background: rgb(23 37 54 / 26%); bottom: 0; display: block; left: 0; position: fixed; right: 0; top: 52px; z-index: 29; }.brand { font-size: 16px; } }
</style>