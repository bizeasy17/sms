<template>
    <el-card class="recent-updates-card" style="max-width: 480px" v-loading="loading">
        <template #header>
            <div class="card-header">
                <el-row align="middle" justify="space-between" style="width: 100%; gap: 8px;">
                    <el-col :span="24">
                        <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;">
                            <span style="font-size: 14px;">最近财报/快报更新</span>
                            <el-tag type="danger" size="small" round>{{ `${recentDays}天` }}</el-tag>
                        </div>
                    </el-col>
                    <el-col :span="24">
                        <div style="display: flex; flex-direction: column; gap: 8px; margin-top: 10px;">
                            <el-radio-group v-model="recentDays" size="small" @change="fetchRecentUpdates">
                                <el-radio-button :label="7">近7天</el-radio-button>
                                <el-radio-button :label="14">近14天</el-radio-button>
                                <el-radio-button :label="30">近30天</el-radio-button>
                            </el-radio-group>
                            <el-radio-group v-model="marketScope" size="small" @change="fetchRecentUpdates">
                                <el-radio-button label="60">沪</el-radio-button>
                                <el-radio-button label="00">深</el-radio-button>
                                <el-radio-button label="30">创</el-radio-button>
                                <el-radio-button label="68">科</el-radio-button>
                            </el-radio-group>
                            <el-radio-group v-model="reportFilter" size="small" @change="fetchRecentUpdates">
                                <el-radio-button label="ALL">全部</el-radio-button>
                                <el-radio-button label="Q1">Q1</el-radio-button>
                                <el-radio-button label="H1">H1</el-radio-button>
                                <el-radio-button label="Q3">Q3</el-radio-button>
                                <el-radio-button label="FY">FY</el-radio-button>
                                <el-radio-button label="快">快</el-radio-button>
                            </el-radio-group>
                        </div>
                    </el-col>
                </el-row>
            </div>
        </template>
        <el-tabs v-model="activeTab">
            <el-tab-pane label="更新列表" name="list">
                <template v-if="recentUpdateStocks.length === 0">
                    <div style="text-align: center; color: #888; margin: 8px 0;">
                        当前筛选下无财报/快报更新
                    </div>
                </template>
                <template v-else>
                    <el-scrollbar ref="recentListScrollbar" class="recent-list-scrollbar">
                        <el-row v-for="(stock, idx) in recentUpdateStocks" :key="stock.ts_code"
                            :ref="setStockRowRef(stock.ts_code)"
                            :class="{ 'recent-bookmark-row': isBookmarkedStock(stock) }"
                            style="margin-bottom: 8px;font-size: small;">
                            <el-col :span="24">
                                <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;">
                                    <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
                                    <el-link type="primary" href="#" @click.prevent="handleStockClick(stock.name, stock.ts_code, stock.basic_info?.website || '')"
                                        underline="never">
                                        {{ stock.name }} | {{ stock.ts_code }}
                                    </el-link>
                                    <el-tag type="warning" effect="plain" size="small">{{ formatRecentReportLabel(stock.recent_report_label) }}</el-tag>
                                    </div>
                                    <el-button
                                        size="small"
                                        plain
                                        :type="isBookmarkedStock(stock) ? 'warning' : 'default'"
                                        @click="saveBookmark(stock)"
                                    >
                                        {{ isBookmarkedStock(stock) ? '已书签' : '设书签' }}
                                    </el-button>
                                </div>
                            </el-col>
                            <el-col :span="24" v-if="stock.latest_financial_ann_date">
                                <div style="margin-left: 2px; color: #888;">
                                    <span>公告日期: </span>
                                    <span>{{ stock.latest_financial_ann_date }}</span>
                                </div>
                            </el-col>
                            <el-col :span="24" v-if="stock.basic_info.setup_date">
                                <div style="margin-left: 2px; color: #888;">
                                    <span>成立日期: </span>
                                    <span>{{ stock.basic_info.setup_date }}</span>
                                </div>
                            </el-col>
                            <el-col :span="24" v-if="stock.basic_info.website">
                                <div style="margin-left: 2px; color: #888;">
                                    <span>官网: </span>
                                    <el-link
                                        :href="stock.basic_info.website.startsWith('http') ? stock.basic_info.website : 'https://' + stock.basic_info.website"
                                        target="_blank" type="primary" style="font-size: 12px;">
                                        {{ stock.basic_info.website.startsWith('http') ? stock.basic_info.website : 'https://' +
                                            stock.basic_info.website }}
                                    </el-link>
                                </div>
                            </el-col>
                            <el-col :span="24" v-if="stock.basic_info.main_business">
                                <div style="margin-left: 2px; color: #888;">
                                    <span>主营: </span>
                                    <span>
                                        {{ stock.basic_info.main_business.length > 50 ? stock.basic_info.main_business.slice(0, 50)
                                            + '...' : stock.basic_info.main_business }}
                                    </span>
                                </div>
                            </el-col>
                            <el-col :span="24">
                                <el-divider v-if="idx !== recentUpdateStocks.length - 1" style="margin: 8px 0;" />
                            </el-col>
                        </el-row>
                    </el-scrollbar>
                </template>

                <div style="display: flex; flex-direction: column; gap: 8px; margin-top: 8px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <span style="font-size: 12px; color: #909399;">共 {{ recentUpdateStocks.length }} 只，已存 {{ bookmarkCount }} 组书签</span>
                        <span v-if="bookmark" style="font-size: 12px; color: #909399;">
                            当前分组书签: {{ bookmark.name }} | {{ bookmark.ts_code }}
                        </span>
                        <span v-else style="font-size: 12px; color: #c0c4cc;">
                            当前分组 {{ currentBookmarkScopeLabel }} 暂无书签
                        </span>
                    </div>
                    <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <el-button-group>
                            <el-button type="warning" plain size="small" @click="restoreBookmark" :disabled="!bookmark">
                                跳转当前分组书签
                            </el-button>
                            <el-button type="default" size="small" @click="fetchRecentUpdates">刷新</el-button>
                        </el-button-group>
                        <el-button v-if="bookmark" type="info" plain size="small" @click="clearBookmark">清除当前分组书签</el-button>
                    </div>
                </div>
            </el-tab-pane>

            <el-tab-pane label="同步汇总" name="summary">
                <div style="display: flex; flex-direction: column; gap: 6px; padding: 8px; border: 1px solid #ebeef5; border-radius: 6px; background: #fafafa;">
                    <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <span style="font-size: 12px; color: #606266;">同步日汇总</span>
                        <span style="font-size: 12px; color: #909399;">
                            今日新增 {{ recentSummary.sync.today_synced || 0 }} / 失败 {{ recentSummary.sync.today_missing || 0 }}
                        </span>
                    </div>
                    <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <span style="font-size: 12px; color: #606266;">近{{ recentDays }}天新增 {{ recentSummary.sync.synced_total || 0 }}</span>
                        <span style="font-size: 12px; color: #f56c6c;">近{{ recentDays }}天失败 {{ recentSummary.sync.missing_total || 0 }}</span>
                    </div>
                    <div v-if="recentSummary.sync.note" style="font-size: 12px; color: #909399;">
                        {{ recentSummary.sync.note }}
                    </div>
                    <el-scrollbar v-if="(recentSummary.sync.daily || []).length > 0" class="recent-summary-scrollbar">
                        <div
                            v-for="item in recentSummary.sync.daily || []"
                            :key="item.date"
                            style="display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: #606266; padding: 2px 0;"
                        >
                            <span>{{ item.date }}</span>
                            <span>新增 {{ item.synced || 0 }} / 失败 {{ item.missing || 0 }}</span>
                        </div>
                    </el-scrollbar>
                    <div v-else style="font-size: 12px; color: #909399; text-align: center; margin-top: 8px;">
                        当前筛选下暂无同步汇总数据
                    </div>
                </div>
            </el-tab-pane>
        </el-tabs>
    </el-card>
</template>

<script setup>
import { computed, ref, defineOptions, inject, nextTick, onMounted } from 'vue'
import axios from 'axios';
import { ElCard, ElRow, ElCol, ElLink, ElTag, ElDivider, ElButton, ElButtonGroup, ElScrollbar, ElRadioGroup, ElRadioButton, ElMessage, ElTabs, ElTabPane } from 'element-plus';
import { useStockTradeStore } from '../stores/stockTradeStore';

const baseURL = inject('baseURL');
const stockTradeStore = useStockTradeStore();
const loading = ref(false);
const recentDays = ref(7);
const marketScope = ref('60');
const reportFilter = ref('ALL');
const activeTab = ref('list');
const recentUpdateStocks = ref([]);
const recentSummary = ref({
    updates_total: 0,
    label_counts: {},
    sync: {
        daily: [],
        today_synced: 0,
        today_missing: 0,
        synced_total: 0,
        missing_total: 0,
        note: '',
    },
});
const recentListScrollbar = ref(null);
const stockRowRefs = ref({});
const BOOKMARK_KEY = 'smartinvestor_recent_updates_bookmark_v1';
const bookmarkStore = ref({});

const normalizeStockCode = (value) => String(value || '').trim().toUpperCase();
const normalizeMarketScope = (value) => String(value || '60').trim().toUpperCase();
const normalizeReportFilter = (value) => String(value || 'ALL').trim().toUpperCase();

const normalizeBookmarkEntry = (value) => {
    if (!value?.ts_code || !value?.marketScope) {
        return null;
    }
    return {
        ts_code: normalizeStockCode(value.ts_code),
        name: String(value.name || ''),
        website: String(value.website || ''),
        recentDays: Number(value.recentDays) || 7,
        marketScope: normalizeMarketScope(value.marketScope),
        reportFilter: normalizeReportFilter(value.reportFilter),
        recent_report_label: String(value.recent_report_label || ''),
        saved_at: Number(value.saved_at) || Date.now(),
    };
};

const getBookmarkScopeKey = (scope = marketScope.value, report = reportFilter.value) => {
    return `${normalizeMarketScope(scope)}__${normalizeReportFilter(report)}`;
};

const bookmark = computed(() => bookmarkStore.value[getBookmarkScopeKey()] || null);
const bookmarkCount = computed(() => Object.keys(bookmarkStore.value || {}).length);

const formatMarketScopeLabel = (value) => {
    const normalized = normalizeMarketScope(value);
    if (normalized === '60') {
        return '沪';
    }
    if (normalized === '00') {
        return '深';
    }
    if (normalized === '30') {
        return '创';
    }
    if (normalized === '68') {
        return '科';
    }
    return normalized;
};

const formatReportFilterLabel = (value) => {
    const normalized = normalizeReportFilter(value);
    if (normalized === 'ALL') {
        return '全部';
    }
    return normalized;
};

const formatRecentReportLabel = (value) => {
    const normalized = String(value || '').trim().toUpperCase();
    if (!normalized) {
        return '更新';
    }
    if (['快', 'EXP', 'EXPRESS', 'EXPRESS_VIP'].includes(normalized)) {
        return '快';
    }
    return normalized;
};

const currentBookmarkScopeLabel = computed(() => {
    return `${formatMarketScopeLabel(marketScope.value)} / ${formatReportFilterLabel(reportFilter.value)}`;
});

const readBookmarkStore = () => {
    if (typeof window === 'undefined') {
        return {};
    }
    try {
        const raw = window.localStorage.getItem(BOOKMARK_KEY);
        if (!raw) {
            return {};
        }
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object') {
            return {};
        }

        const legacyEntry = normalizeBookmarkEntry(parsed);
        if (legacyEntry) {
            return {
                [getBookmarkScopeKey(legacyEntry.marketScope, legacyEntry.reportFilter)]: legacyEntry,
            };
        }

        const nextStore = {};
        for (const [key, value] of Object.entries(parsed)) {
            const normalizedEntry = normalizeBookmarkEntry(value);
            if (!normalizedEntry) {
                continue;
            }
            nextStore[key] = normalizedEntry;
        }
        return nextStore;
    } catch {
        return {};
    }
};

const writeBookmarkStore = (value) => {
    bookmarkStore.value = value;
    if (typeof window === 'undefined') {
        return;
    }
    try {
        if (!value || Object.keys(value).length === 0) {
            window.localStorage.removeItem(BOOKMARK_KEY);
            return;
        }
        window.localStorage.setItem(BOOKMARK_KEY, JSON.stringify(value));
    } catch {
        // ignore localStorage failures
    }
};

const isBookmarkedStock = (stock) => normalizeStockCode(stock?.ts_code) === normalizeStockCode(bookmark.value?.ts_code);

const setStockRowRef = (tsCode) => (element) => {
    const normalizedCode = normalizeStockCode(tsCode);
    if (!normalizedCode) {
        return;
    }
    if (element) {
        stockRowRefs.value[normalizedCode] = element;
        return;
    }
    delete stockRowRefs.value[normalizedCode];
};

const scrollToStock = async (tsCode) => {
    const normalizedCode = normalizeStockCode(tsCode);
    if (!normalizedCode) {
        return;
    }
    await nextTick();
    const rowElement = stockRowRefs.value[normalizedCode]?.$el || stockRowRefs.value[normalizedCode];
    if (!rowElement?.scrollIntoView) {
        return;
    }
    rowElement.scrollIntoView({ block: 'center', behavior: 'smooth' });
};

const selectStock = (stock) => {
    if (!stock?.ts_code) {
        return;
    }
    stockTradeStore.setTsCode(stock.ts_code);
    stockTradeStore.setName(stock.name || '');
    stockTradeStore.setWebsite(stock?.basic_info?.website || stock?.website || '');
};

const saveBookmark = (stock, options = {}) => {
    if (!stock?.ts_code) {
        return;
    }
    writeBookmarkStore({
        ...bookmarkStore.value,
        [getBookmarkScopeKey()]: normalizeBookmarkEntry({
        ts_code: normalizeStockCode(stock.ts_code),
        name: String(stock.name || ''),
        website: String(stock?.basic_info?.website || ''),
        recentDays: Number(recentDays.value) || 7,
        marketScope: normalizeMarketScope(marketScope.value),
        reportFilter: normalizeReportFilter(reportFilter.value),
        recent_report_label: String(stock.recent_report_label || ''),
        saved_at: Date.now(),
        }),
    });
    if (options.silent !== true) {
        ElMessage.success('已记录书签');
    }
};

const clearBookmark = () => {
    const nextStore = { ...bookmarkStore.value };
    delete nextStore[getBookmarkScopeKey()];
    writeBookmarkStore(nextStore);
    ElMessage.info('已清除当前分组书签');
};

const fetchRecentUpdates = async () => {
    loading.value = true;
    try {
        const response = await axios.get(`${baseURL}/recent-financial-updates/?days=${recentDays.value}&scope=${marketScope.value}&report=${encodeURIComponent(reportFilter.value)}`);
        const rows = Array.isArray(response?.data?.data) ? response.data.data : [];
        const summary = response?.data?.summary || {};
        recentUpdateStocks.value = [...rows].sort((a, b) => {
            const codeA = String(a?.ts_code || '').toUpperCase();
            const codeB = String(b?.ts_code || '').toUpperCase();
            return codeA.localeCompare(codeB);
        });
        recentSummary.value = {
            updates_total: Number(summary?.updates_total || 0),
            label_counts: summary?.label_counts || {},
            sync: {
                daily: Array.isArray(summary?.sync?.daily) ? summary.sync.daily : [],
                today_synced: Number(summary?.sync?.today_synced || 0),
                today_missing: Number(summary?.sync?.today_missing || 0),
                synced_total: Number(summary?.sync?.synced_total || 0),
                missing_total: Number(summary?.sync?.missing_total || 0),
                note: String(summary?.sync?.note || ''),
            },
        };
    } catch (error) {
        recentUpdateStocks.value = [];
        recentSummary.value = {
            updates_total: 0,
            label_counts: {},
            sync: {
                daily: [],
                today_synced: 0,
                today_missing: 0,
                synced_total: 0,
                missing_total: 0,
                note: '',
            },
        };
        console.error('Error fetching recent financial updates:', error);
    } finally {
        loading.value = false;
    }
};

const handleStockClick = (name, tsCode, website = '') => {
    const stock = {
        name,
        ts_code: tsCode,
        basic_info: { website },
    };
    selectStock(stock);
    saveBookmark(stock, { silent: true });
};

const restoreBookmark = async () => {
    const marker = bookmark.value;
    if (!marker?.ts_code) {
        ElMessage.info('没有可用书签');
        return;
    }

    recentDays.value = Number(marker.recentDays) || 7;
    marketScope.value = String(marker.marketScope || '60');
    reportFilter.value = String(marker.reportFilter || 'ALL');

    await fetchRecentUpdates();

    const targetCode = normalizeStockCode(marker.ts_code);
    const target = recentUpdateStocks.value.find((stock) => normalizeStockCode(stock?.ts_code) === targetCode);

    if (target) {
        selectStock(target);
        await scrollToStock(target.ts_code);
        ElMessage.success('已跳转到书签股票');
        return;
    }

    selectStock({
        ts_code: marker.ts_code,
        name: marker.name || marker.ts_code,
        website: marker.website || '',
    });
    ElMessage.warning('已恢复书签筛选，但当前列表中未找到该股票');
};

onMounted(() => {
    bookmarkStore.value = readBookmarkStore();
    fetchRecentUpdates();
});

defineOptions({
    name: 'RecentFinancialUpdatesTag'
})
</script>

<style scoped>
.recent-bookmark-row {
    border-left: 3px solid #e6a23c;
    padding-left: 8px;
}

.recent-updates-card {
    height: calc(100vh - 96px);
    max-height: calc(100vh - 96px);
}

.recent-updates-card :deep(.el-card__body) {
    height: calc(100% - 56px);
    overflow: hidden;
    display: flex;
    flex-direction: column;
    min-height: 0;
}

.recent-updates-card :deep(.el-tabs) {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
}

.recent-updates-card :deep(.el-tabs__content) {
    flex: 1;
    min-height: 0;
}

.recent-updates-card :deep(.el-tab-pane) {
    height: 100%;
    min-height: 0;
}

.recent-list-scrollbar {
    max-height: calc(100vh - 420px);
}

.recent-summary-scrollbar {
    max-height: calc(100vh - 420px);
}

@media (max-height: 800px) {
    .recent-updates-card {
        height: calc(100vh - 84px);
        max-height: calc(100vh - 84px);
    }

    .recent-list-scrollbar,
    .recent-summary-scrollbar {
        max-height: calc(100vh - 380px);
    }
}
</style>