<script setup lang="ts">
import type { ResearchCompany } from './researchData';

defineProps<{
    companies: ResearchCompany[];
    selectedCode: string;
    loading: boolean;
    errorMessage: string;
}>();

const emit = defineEmits<{
    select: [company: ResearchCompany];
}>();
</script>

<template>
    <aside class="research-rail">
        <p class="rail-title">我的覆盖 · {{ companies.length }}</p>
        <p v-if="loading" class="rail-message">正在加载观察与持仓股票...</p>
        <p v-else-if="errorMessage" class="rail-message rail-message-error">{{ errorMessage }}</p>
        <p v-else-if="companies.length === 0" class="rail-message">暂无观察或持仓股票。</p>
        <button
            v-for="company in companies"
            :key="company.code"
            class="company"
            :class="{ selected: company.code === selectedCode }"
            type="button"
            @click="emit('select', company)"
        >
            <span class="company-title"><span class="company-name">{{ company.name }}</span><span class="company-tags"><span v-for="tag in company.tags" :key="tag" class="company-tag" :class="{ 'company-tag-holding': tag === '持' }">{{ tag }}</span></span></span>
            <span class="company-code">{{ company.code }} · {{ company.industry }}</span>
            <span v-if="company.status" class="company-meta">
                <span class="pill" :class="company.statusTone">{{ company.status }}</span>
            </span>
        </button>
        <p class="rail-foot">范围：当前用户的启用观察股或持仓股。</p>
    </aside>
</template>

<style scoped>
.research-rail { background: #fff; border-right: 1px solid #e3e9f1; padding: 22px 14px; overflow-y: auto; }
.rail-title { color: #8190a5; font-size: 11px; letter-spacing: .12em; margin: 0 10px 12px; }
.company { background: transparent; border: 0; border-radius: 5px; color: #182536; cursor: pointer; display: block; font: inherit; margin-bottom: 4px; padding: 12px 11px; text-align: left; width: 100%; }
.company:hover { background: #f6f8fb; }.company.selected { background: #edf3ff; border-left: 3px solid #315bce; padding-left: 8px; }
.company-title, .company-name, .company-code, .company-meta { display: block; }.company-title { align-items: center; display: flex; gap: 6px; min-width: 0; }.company-name { font-size: 13px; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.company-tags { display: inline-flex; flex: 0 0 auto; gap: 3px; }.company-tag { background: #edf3ff; border: 1px solid #cbdcff; border-radius: 3px; color: #315bce; font-size: 10px; line-height: 16px; min-width: 16px; text-align: center; }.company-tag-holding { background: #fff2df; border-color: #e29c38; color: #9d5c08; font-weight: 700; }.company-code { color: #77869a; font: 11px 'DM Mono', monospace; margin-top: 3px; }
.company-meta { margin-top: 8px; }.pill { background: #f1f4f8; border-radius: 3px; color: #65758a; font-size: 10px; padding: 3px 5px; }.pill.good { background: #e8f7ef; color: #14805c; }.pill.warn { background: #fff2e3; color: #a96412; }
.rail-foot { border-top: 1px solid #e7ecf2; color: #7c8b9c; font-size: 12px; line-height: 1.8; margin: 22px 10px 0; padding-top: 18px; }
.rail-message { color: #7c8b9c; font-size: 12px; line-height: 1.7; margin: 14px 10px; }.rail-message-error { color: #b3533b; }
@media (max-width: 700px) { .research-rail { bottom: 0; box-shadow: 10px 0 26px rgb(32 55 82 / 14%); left: 0; padding-top: 20px; position: fixed; top: 52px; transform: translateX(-102%); transition: transform .25s ease; width: 278px; z-index: 30; }.research-rail.open { transform: translateX(0); } }
</style>