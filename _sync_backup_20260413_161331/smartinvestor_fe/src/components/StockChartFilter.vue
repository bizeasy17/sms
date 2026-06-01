<template>
    <el-card class="stock-chart-filter-card">
            <el-row :gutter="12">
                <el-col :span="14">

                    <el-row :gutter="8">
                        <el-col :span="24">
                            <div class="stock-title-actions">
                                <el-text type="primary" tag="b">
                                    <el-link
                                        :href="stockTradeStore.website.startsWith('http') ? stockTradeStore.website : 'https://' + stockTradeStore.website"
                                        target="_blank"
                                        type="primary"
                                        class="stock-name-link"
                                    >
                                        {{ stockTradeStore.name + ' | ' + stockTradeStore.tsCode }}
                                    </el-link>
                                </el-text>
                                <el-check-tag
                                    :checked="isInWatchlist"
                                    @change="toggleWatchlistStatus"
                                    class="compact-toggle-tag compact-toggle-watch"
                                >
                                    <span class="compact-toggle-label">自选</span>
                                </el-check-tag>
                                <el-check-tag
                                    :checked="isHolding"
                                    @change="toggleHoldingStatus"
                                    class="compact-toggle-tag compact-toggle-hold"
                                >
                                    <span class="compact-toggle-label">持仓</span>
                                </el-check-tag>
                            </div>
                        </el-col>
                        <el-col :span="24">
                            <el-row :gutter="8">
                                <el-col :span="8">
                                    <el-input v-if="inputVisible" ref="InputRef" v-model="inputValue" class="w-20" size="small"
                                        @keyup.enter="handleInputConfirm" @blur="handleInputConfirm" />
                                    <el-button v-else class="button-new-tag" size="small" @click="showInput">
                                        + 新标签
                                    </el-button>
                                </el-col>
                            </el-row>
                        </el-col>
                    </el-row>
                </el-col>
            </el-row>
            <el-row v-if="dynamicTags.length > 0" :gutter="12" class="tags-row">
                <el-col :span="24" style="text-align: left; font-size: x-small; color: gray;">
                    <el-tag v-for="tag in dynamicTags" :key="tag" closable :disable-transitions="false"
                        @close="handleClose(tag)">
                        {{ tag }}
                    </el-tag>
                </el-col>

            </el-row>
            <el-row :gutter="12" class="valuation-quickview-row">
                <el-col :span="24">
                    <StockValuationQuickView :embedded="true" />
                </el-col>
            </el-row>
    </el-card>
</template>

<script setup lang="ts">
import { nextTick, ref } from 'vue';
// Element Plus
import type { InputInstance } from 'element-plus';
import { ElMessage, ElRow, ElCol, ElCard, ElText, ElCheckTag, ElButton, ElTag, ElInput, ElLink } from 'element-plus';
import { useStockTradeStore } from '../stores/stockTradeStore';
import StockValuationQuickView from './StockValuationQuickView.vue';
import axios from 'axios';
import { inject } from 'vue';

const stockTradeStore = useStockTradeStore();

const isHolding = ref(false);
const isInWatchlist = ref(false);

const inputValue = ref('')
const dynamicTags = ref<string[]>([])
const inputVisible = ref(false)
const InputRef = ref<InputInstance>()

const baseURL = inject('baseURL');

function toCanonicalTsCode(code: string): string {
    const normalized = String(code || '').trim().toUpperCase();
    if (!normalized) return '';
    if (normalized.includes('.')) return normalized;
    if (!/^\d{6}$/.test(normalized)) return normalized;
    if (normalized.startsWith('6') || normalized.startsWith('5') || normalized.startsWith('9')) return `${normalized}.SH`;
    if (normalized.startsWith('8') || normalized.startsWith('4')) return `${normalized}.BJ`;
    return `${normalized}.SZ`;
}

function buildTsCodeCandidates(code: string): string[] {
    const normalized = String(code || '').trim().toUpperCase();
    const base = normalized.split('.')[0];
    const candidateSet = new Set<string>();
    if (normalized) candidateSet.add(normalized);
    if (base) candidateSet.add(base);
    const canonical = toCanonicalTsCode(normalized);
    if (canonical) candidateSet.add(canonical);
    if (base && /^\d{6}$/.test(base)) {
        candidateSet.add(`${base}.SH`);
        candidateSet.add(`${base}.SZ`);
        candidateSet.add(`${base}.BJ`);
    }
    return Array.from(candidateSet);
}

async function fetchStockStatus(tsCode: string) {
    if (!baseURL || !tsCode) return;
    try {
        const candidates = buildTsCodeCandidates(tsCode);
        let fallbackData: any = null;
        for (const candidate of candidates) {
            const res = await axios.get(`${baseURL}/watchlist/check/${candidate}/`);
            if (!res.data) continue;
            if (!fallbackData) {
                fallbackData = res.data;
            }
            if (res.data.hold_position || res.data.in_watchlist) {
                isHolding.value = !!res.data.hold_position;
                isInWatchlist.value = !!res.data.in_watchlist;
                return;
            }
        }
        if (fallbackData) {
            isHolding.value = !!fallbackData.hold_position;
            isInWatchlist.value = !!fallbackData.in_watchlist;
        }
    } catch (error) {
        console.error('Failed to fetch stock status:', error);
    }
}

async function toggleWatchlistStatus(watchlist: boolean) {
    try {
        let res;
        if (watchlist) {
            const url = `${baseURL}/watchlist/add/${stockTradeStore.tsCode}/`;
            res = await axios.post(url);
        } else {
            const url = `${baseURL}/watchlist/delete/${stockTradeStore.tsCode}/`;
            res = await axios.put(url);
        }
        if (res.status === 200) {
            isInWatchlist.value = !isInWatchlist.value;
            ElMessage.success(isInWatchlist.value ? '已加入自选股' : '已移除自选股');
        }
    } catch (error) {
        console.error('Failed to toggle watchlist status:', error);
        ElMessage.error('操作失败，请稍后重试');
    }
}

async function toggleHoldingStatus(hold: boolean) {
    try {
        const url = hold
            ? `${baseURL}/watchlist/hold/${stockTradeStore.tsCode}/`
            : `${baseURL}/watchlist/unhold/${stockTradeStore.tsCode}/`;
        const method = hold ? 'post' : 'put';
        const res = await axios({ url, method });
        if (res.status === 200) {
            isHolding.value = hold;
            isInWatchlist.value = res.data.in_watchlist; // 持仓后自动加入自选股，否则移除
            ElMessage.success(isHolding.value ? '已标记为持仓' : '已取消持仓标记');
        }
    } catch (error) {
        console.error('Failed to toggle holding status:', error);
        ElMessage.error('操作失败，请稍后重试');
    }
}

async function fetchStockTags(tsCode: string) {
    try {
        const res = await axios.get(`${baseURL}/tags/${tsCode}/`);
        if (Array.isArray(res.data.tags)) {
            dynamicTags.value = res.data.tags;
        }
    } catch (error) {
        console.error('Failed to fetch stock tags:', error);
    }
}


async function addStockTag(tsCode: string, tag: string) {
    try {
        const url = `${baseURL}/tags/add/${tsCode}/${encodeURIComponent(tag)}/`;
        const res = await axios.post(url);
        if (res.status === 200) {
            dynamicTags.value.push(tag);
            ElMessage.success('已添加标签');
        }
    } catch (error) {
        console.error('Failed to add stock tag:', error);
        ElMessage.error('添加标签失败，可能标签已存在');
    }
}

async function deleteStockTag(tsCode: string, tag: string) {
    try {
        const url = `${baseURL}/tags/delete/${tsCode}/${encodeURIComponent(tag)}/`;
        const res = await axios.delete(url);
        if (res.status === 200) {
            dynamicTags.value = dynamicTags.value.filter((t) => t !== tag);
            // dynamicTags.value.splice(dynamicTags.value.indexOf(tag), 1);
            ElMessage.success('已删除标签');
        }
    } catch (error) {
        console.error('Failed to delete stock tag:', error);
        ElMessage.error('删除标签失败，请稍后重试');
    }
}


const handleClose = (tag: string) => {
    deleteStockTag(stockTradeStore.tsCode, tag);
}

const showInput = () => {
    inputVisible.value = true;
    nextTick(() => {
        InputRef.value!.input!.focus()
    })
}

const handleInputConfirm = () => {
    addStockTag(stockTradeStore.tsCode, inputValue.value);
    inputVisible.value = false
    inputValue.value = ''
}

import { onMounted } from 'vue';

onMounted(() => {
    if (stockTradeStore.tsCode) {
        fetchStockStatus(stockTradeStore.tsCode);
        fetchStockTags(stockTradeStore.tsCode);
    }
});

import { watch } from 'vue';

watch(
    () => stockTradeStore.tsCode,
    (newTsCode) => {
        if (newTsCode) {
            fetchStockStatus(newTsCode);
            fetchStockTags(newTsCode);
        }
    }
);

defineOptions({
    name: 'StockChartFilter'
});
</script>

<style scoped>
.stock-title-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
}

.stock-name-link {
    font-size: 14px;
    font-weight: bold;
}

.compact-toggle-tag {
    border-radius: 999px;
    border: 1px solid #d0d7de;
    background: #ffffff;
    padding: 2px 10px;
    line-height: 1.15;
    color: #475569;
    transition: all 0.2s ease;
}

.compact-toggle-tag:hover {
    border-color: #94a3b8;
}

.compact-toggle-tag.is-checked.compact-toggle-watch {
    background: #fff1f2;
    border-color: #fb7185;
    color: #be123c;
}

.compact-toggle-tag.is-checked.compact-toggle-hold {
    background: #eff6ff;
    border-color: #60a5fa;
    color: #1d4ed8;
}

.compact-toggle-label {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.2px;
}

.tags-row {
    margin-top: 4px;
}

.valuation-quickview-row {
    margin-top: 10px;
}
</style>