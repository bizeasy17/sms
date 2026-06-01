<template>

    <el-affix :offset="75">
        <el-card style="max-width: 480px" v-loading="loading">
            <template #header>
                <div class="card-header">
                    <el-radio-group v-model="market" size="small" @change="handleMarketChange" class="market-radio-group">
                                <el-radio-button label="HO">持</el-radio-button>
                                <el-radio-button label="WL">自</el-radio-button>
                                <el-radio-button label="60">沪</el-radio-button>
                                <el-radio-button label="00">深</el-radio-button>
                                <el-radio-button label="30">创</el-radio-button>
                                <el-radio-button label="68">科</el-radio-button>
                    </el-radio-group>
                </div>
            </template>
            <el-scrollbar max-height="550px">
                <div v-for="(stock, idx) in watchlist" :key="stock" class="text item" style="font-size: 12px;">
                    <el-row :gutter="0">
                        <el-col :span="24">
                            <div style="display: flex; align-items: center; gap: 12px;">
                                <el-link type="primary" href="#" @click="handleStockClick(stock.name, stock.ts_code, stock.basic_info.website)"
                                    underline="never">
                                    {{ stock.name + ' | ' + stock.ts_code }}
                                </el-link>
                                <el-tag v-if="stock.valuation && stock.valuation.composite_valuation_status === 'under'" round
                                    effect="light" type="danger" size="small">低估 ({{ stock.valuation.composite_valuation_gap_pct ?? '-' }}%)</el-tag>
                                <el-tag v-else-if="stock.valuation && stock.valuation.composite_valuation_status === 'over'" round
                                    effect="light" type="success" size="small">高估 ({{ stock.valuation.composite_valuation_gap_pct ?? '-' }}%)</el-tag>
                                <el-tag v-else-if="stock.valuation && stock.valuation.composite_valuation_status === 'fair'" round
                                    effect="light" type="info" size="small">合理</el-tag>

                            </div>
                        </el-col>
                        <el-col :span="24">
                            <div style="margin-left: 2px; color: #888;">
                                <div v-if="stock.basic_info.setup_date || stock.recent_report_badge" style="display: flex; align-items: center; gap: 6px;">
                                    <span v-if="stock.basic_info.setup_date">成立日期: {{ stock.basic_info.setup_date }}</span>
                                    <RecentReportBadge :visible="stock.recent_report_badge" :label="stock.recent_report_label" />
                                </div>
                            </div>
                        </el-col>
                        <el-col :span="24">
                            <div style="margin-left: 2px; color: #888;">
                                <div v-if="stock.basic_info.website">
                                    <span>官网: </span>
                                    <el-link
                                        :href="stock.basic_info.website.startsWith('http') ? stock.basic_info.website : 'https://' + stock.basic_info.website"
                                        target="_blank" type="primary" style="font-size: 12px;">{{ "https://" +
                                            stock.basic_info.website }}</el-link>
                                </div>
                            </div>
                        </el-col>
                        <el-col :span="24">
                            <div style="margin-left: 2px; color: #888;">
                                <div v-if="stock.basic_info.main_business">
                                    <span>主营: </span>
                                    <span>{{ stock.basic_info.main_business }}</span>
                                </div>
                            </div>
                        </el-col>
                    </el-row>
                    <el-divider v-if="idx !== watchlist.length - 1" style="margin: 8px 0;" />
                </div>
            </el-scrollbar>
            <template #footer>
                <div class="watchlist-meta-row watchlist-footer-meta-row">
                    <span>已加载 {{ loadedCount }}/{{ totalCount || 0 }}</span>
                    <span v-if="resumeMarker && resumeMarker.market === market">上次: {{ resumeMarker.name }} | {{ resumeMarker.ts_code }}</span>
                </div>
                <div class="watchlist-footer-actions">
                    <el-switch
                        v-model="resumeLocateOnly"
                        size="small"
                        inline-prompt
                        active-text="仅定位"
                        inactive-text="自动翻页"
                    />
                    <el-button
                        type="warning"
                        plain
                        size="small"
                        @click="restoreLastViewedStock"
                        :disabled="!resumeMarker"
                    >
                        恢复上次
                    </el-button>
                    <el-button type="primary" size="small" @click="loadNextWatchlist" :disabled="from >= totalCount">下一页</el-button>
                </div>
            </template>
        </el-card>
    </el-affix>

    <!-- <el-backtop :right="100" :bottom="100" /> -->
</template>

<script setup>
import { computed, inject, ref, onMounted, watch } from 'vue';
import axios from 'axios';
// Element Plus
import { ElAffix, ElRow, ElCol, ElButton, ElCard, ElDivider, ElLink, ElMessage, ElRadioButton, ElRadioGroup, ElTag, ElScrollbar } from 'element-plus';
import { useStockTradeStore } from '../stores/stockTradeStore';
import RecentReportBadge from './RecentReportBadge.vue';

const stockTradeStore = useStockTradeStore();

const market = ref('HO');
const baseURL = inject('baseURL');
const watchlist = ref([]);

const from = ref(0);
const to = ref(50);
const indexIncre = ref(50)
const totalCount = ref(0)
const loading = ref(false)
const loadedCount = computed(() => watchlist.value.length)

const RESUME_MARKER_KEY = 'smartinvestor_watchlist_resume_v1'
const RESUME_MODE_KEY = 'smartinvestor_watchlist_resume_mode_v1'
const MAX_AUTO_RESTORE_LOAD = 300
const resumeMarker = ref(null)
const resumeLocateOnly = ref(false)

function readResumeMarker() {
    if (typeof window === 'undefined') {
        return null
    }
    try {
        const raw = window.localStorage.getItem(RESUME_MARKER_KEY)
        if (!raw) {
            return null
        }
        const parsed = JSON.parse(raw)
        if (!parsed || !parsed.ts_code || !parsed.market) {
            return null
        }
        return parsed
    } catch {
        return null
    }
}

function writeResumeMarker(marker) {
    resumeMarker.value = marker
    if (typeof window === 'undefined') {
        return
    }
    try {
        window.localStorage.setItem(RESUME_MARKER_KEY, JSON.stringify(marker))
    } catch {
        // ignore localStorage failures
    }
}

function readResumeMode() {
    if (typeof window === 'undefined') {
        return false
    }
    try {
        const raw = window.localStorage.getItem(RESUME_MODE_KEY)
        if (raw === null) {
            return false
        }
        return String(raw) === '1'
    } catch {
        return false
    }
}

function writeResumeMode(enabled) {
    if (typeof window === 'undefined') {
        return
    }
    try {
        window.localStorage.setItem(RESUME_MODE_KEY, enabled ? '1' : '0')
    } catch {
        // ignore localStorage failures
    }
}

function saveCurrentBrowseMarker(stock) {
    if (!stock || !stock.ts_code) {
        return
    }
    writeResumeMarker({
        market: market.value,
        ts_code: stock.ts_code,
        name: stock.name || '',
        website: stock?.basic_info?.website || '',
        updated_at: Date.now(),
    })
}

function isActiveStock(stock) {
    return String(stock?.ts_code || '').toUpperCase() === String(stockTradeStore.tsCode || '').toUpperCase()
}

function mergeUniqueStocks(existing, incoming) {
    const merged = [...existing]
    const seen = new Set(existing.map((item) => item.ts_code))
    for (const item of incoming || []) {
        if (!item?.ts_code || seen.has(item.ts_code)) {
            continue
        }
        seen.add(item.ts_code)
        merged.push(item)
    }
    return merged
}

function hasCurrentSelectionInList() {
    const current = String(stockTradeStore.tsCode || '').toUpperCase()
    if (!current) {
        return false
    }
    return watchlist.value.some((item) => String(item?.ts_code || '').toUpperCase() === current)
}

const selectStock = (stock, options = {}) => {
    if (!stock) {
        return;
    }
    stockTradeStore.setTsCode(stock.ts_code);
    stockTradeStore.setName(stock.name);
    stockTradeStore.setWebsite(stock.basic_info.website);
    const persistResume = options.persistResume !== false
    if (persistResume) {
        saveCurrentBrowseMarker(stock)
    }
};

const fetchWatchlist = async (market) => {
    loading.value = true;
    try {
        const response = await axios.get(`${baseURL}/watchlist/${from.value}/${to.value}/?format=json&market=${market}`);
        let responseData = response.data;
        const previousLength = watchlist.value.length;
        watchlist.value = mergeUniqueStocks(watchlist.value, responseData.data || []);
        totalCount.value = responseData.total;
        if (previousLength === 0 && !hasCurrentSelectionInList() && responseData.data?.length) {
            // Auto-select first stock for convenience, but do not overwrite user bookmark.
            selectStock(responseData.data[0], { persistResume: false });
        }
        // Increment from and to for next fetch
        from.value = to.value;
        to.value += indexIncre.value;
    } catch (error) {
        console.error('Error fetching watchlist:', error);
    } finally {
        loading.value = false;
    }
};

const loadNextWatchlist = async () => {
    if (from.value >= totalCount.value) {
        return;
    }
    await fetchWatchlist(market.value);
    // Prevent over-fetching if next "from" exceeds totalCount
    if (from.value >= totalCount.value) {
        from.value = totalCount.value;
        to.value = totalCount.value;
    }
};

const handleMarketChange = async (market) => {
    from.value = 0;
    to.value = indexIncre.value;
    watchlist.value = [];
    await fetchWatchlist(market);
};

async function restoreLastViewedStock() {
    const marker = resumeMarker.value || readResumeMarker()
    if (!marker || !marker.ts_code || !marker.market) {
        ElMessage.info('没有可恢复的浏览记录')
        return
    }

    if (market.value !== marker.market) {
        market.value = marker.market
        await handleMarketChange(marker.market)
    }

    const markerTsCode = String(marker.ts_code || '').toUpperCase()
    let target = watchlist.value.find((item) => String(item?.ts_code || '').toUpperCase() === markerTsCode)
    if (!target && resumeLocateOnly.value) {
        selectStock({
            ts_code: marker.ts_code,
            name: marker.name || marker.ts_code,
            basic_info: { website: marker.website || '' },
        })
        ElMessage.info('已恢复到上次股票（仅定位模式未自动翻页）')
        return
    }

    const targetLoaded = await fastLoadUntilFound(markerTsCode)
    target = targetLoaded || watchlist.value.find((item) => String(item?.ts_code || '').toUpperCase() === markerTsCode)

    while (!target && from.value < totalCount.value && loadedCount.value < MAX_AUTO_RESTORE_LOAD) {
        await loadNextWatchlist()
        target = watchlist.value.find((item) => String(item?.ts_code || '').toUpperCase() === markerTsCode)
    }

    if (target) {
        selectStock(target)
        ElMessage.success('已恢复到上次浏览股票')
        return
    }

    selectStock({
        ts_code: marker.ts_code,
        name: marker.name || marker.ts_code,
        basic_info: { website: marker.website || '' },
    })

    if (loadedCount.value >= MAX_AUTO_RESTORE_LOAD) {
        ElMessage.warning(`已跳转到股票，但为避免一次加载过多，仅自动加载前 ${MAX_AUTO_RESTORE_LOAD} 只`) 
    } else {
        ElMessage.info('已跳转到上次浏览股票（列表中尚未定位到该条）')
    }
}

async function fastLoadUntilFound(markerTsCode) {
    if (!markerTsCode) {
        return null
    }
    let target = watchlist.value.find((item) => String(item?.ts_code || '').toUpperCase() === markerTsCode)
    if (target) {
        return target
    }

    let chunk = indexIncre.value
    while (!target && from.value < totalCount.value && loadedCount.value < MAX_AUTO_RESTORE_LOAD) {
        const remainingBudget = MAX_AUTO_RESTORE_LOAD - loadedCount.value
        if (remainingBudget <= 0) {
            break
        }

        const oldTo = to.value
        const nextTo = Math.min(from.value + Math.min(chunk, remainingBudget), totalCount.value)
        if (nextTo <= from.value) {
            break
        }

        to.value = nextTo
        await fetchWatchlist(market.value)
        target = watchlist.value.find((item) => String(item?.ts_code || '').toUpperCase() === markerTsCode)
        chunk = Math.min(chunk * 2, 400)

        if (!target && to.value === oldTo) {
            break
        }
    }
    return target || null
}

const handleStockClick = (name, ts_code, website) => {
    selectStock({ name, ts_code, basic_info: { website } });
};

onMounted(() => {
    resumeMarker.value = readResumeMarker()
    resumeLocateOnly.value = readResumeMode()
    fetchWatchlist(market.value);
});

watch(resumeLocateOnly, (value) => {
    writeResumeMode(!!value)
})

defineOptions({
    name: 'Watchlist'
});
</script>

<style scoped>
.card-header {
    width: 100%;
}

.market-radio-group {
    display: flex;
    width: 100%;
}

.market-radio-group :deep(.el-radio-button) {
    flex: 1;
}

.market-radio-group :deep(.el-radio-button__inner) {
    width: 100%;
    padding-left: 0;
    padding-right: 0;
    text-align: center;
}

.item {
    margin-top: 10px;
    margin-right: 20px;
}

.watchlist-meta-row {
    margin-top: 8px;
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: #606266;
    gap: 8px;
}

.watchlist-footer-meta-row {
    margin-top: 0;
    margin-bottom: 10px;
}

.watchlist-footer-actions {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
}
</style>