<template>

    <el-affix :offset="75">
        <el-card style="max-width: 480px" v-loading="loading">
            <template #header>
                <div class="card-header">
                    <el-row align="middle" justify="space-between" style="width: 100%;">
                        <el-col :span="4">
                            <span style="font-size: 14px;">列表</span>
                        </el-col>
                        <el-col :span="20" style="text-align: right;">
                            <el-tabs v-model="activeTab" @tab-change="handleTabChange" style="--el-tabs-header-height: 28px;">
                                <el-tab-pane name="groupA" label="组合"></el-tab-pane>
                                <el-tab-pane name="groupB" label="市场"></el-tab-pane>
                            </el-tabs>
                            <el-radio-group v-if="activeTab === 'groupA'" v-model="scope" size="small" @change="handleMarketChange">
                                <el-radio-button label="HO">持仓</el-radio-button>
                                <el-radio-button label="WL">自选</el-radio-button>
                                <el-radio-button label="RESULT">选股</el-radio-button>
                            </el-radio-group>
                            <el-radio-group v-else v-model="scope" size="small" @change="handleMarketChange">
                                <el-radio-button label="6">沪市</el-radio-button>
                                <el-radio-button label="0">深市</el-radio-button>
                                <el-radio-button label="30">创业</el-radio-button>
                                <el-radio-button label="688">科创</el-radio-button>
                            </el-radio-group>
                            <div v-if="scope === 'RESULT'" style="margin-top: 6px; display: flex; justify-content: flex-end; gap: 8px; align-items: center;">
                                <span style="font-size: 12px; color: #909399;">选股日期</span>
                                <el-date-picker
                                    v-model="selectedResultDate"
                                    type="date"
                                    value-format="YYYY-MM-DD"
                                    format="YYYY-MM-DD"
                                    placeholder="最新"
                                    size="small"
                                    style="width: 132px;"
                                    @change="handleResultDateChange"
                                >
                                    <template #default="cell">
                                        <div class="result-date-cell" :class="{ 'result-date-cell--marked': hasResultDate(cell) }">
                                            <span>{{ cell.text }}</span>
                                            <span v-if="hasResultDate(cell)" class="result-date-cell__dot"></span>
                                        </div>
                                    </template>
                                </el-date-picker>
                                <el-button size="small" type="warning" plain @click="sortResultByUndervalue('desc')">低估分降序</el-button>
                                <el-button size="small" type="warning" plain @click="sortResultByUndervalue('asc')">低估分升序</el-button>
                            </div>
                        </el-col>
                    </el-row>
                </div>
            </template>
            <el-scrollbar max-height="700px">
                <div v-for="(stock, idx) in watchlist" :key="`${stock.ts_code}-${idx}`" class="text item" style="font-size: 12px;">
                    <el-row :gutter="0">
                        <el-col :span="24">
                            <div style="display: flex; align-items: center; gap: 12px;">
                                <el-link type="primary" href="#" @click="handleStockClick(stock.name, stock.ts_code)"
                                    underline="never">
                                    {{ stock.name + ' | ' + stock.ts_code }}
                                </el-link>
                                <el-tag v-if="stock.prediction && stock.prediction.top_or_bottom === 'B'" round
                                    effect="light" type="danger" size="small">底 ({{
                                        stock.prediction.confidence.toFixed(2) }})</el-tag>
                                <el-tag v-else-if="stock.prediction && stock.prediction.top_or_bottom === 'T'" round
                                    effect="light" type="success" size="small">顶 ({{
                                        stock.prediction.confidence.toFixed(2) }})</el-tag>

                            </div>
                        </el-col>
                        <el-col :span="24">
                            <div style="margin-left: 2px; color: #888;">
                                <div v-if="stock.basic_info.setup_date || stock.recent_report_badge" style="display: flex; align-items: center; gap: 6px;">
                                    <span v-if="stock.basic_info.setup_date">成立日期: {{ stock.basic_info.setup_date }}</span>
                                    <RecentReportBadge :visible="stock.recent_report_badge" />
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
                                    <span>{{ truncateText(stock.basic_info.main_business, 100) }}</span>
                                </div>
                            </div>
                        </el-col>
                    </el-row>
                    <el-divider v-if="idx !== watchlist.length - 1" style="margin: 8px 0;" />
                </div>
                
            </el-scrollbar>
            <template #footer>
                <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                    <el-button type="default" size="small" :loading="loading" @click="refreshCurrentMarketLoadedStocks">
                        刷新当前市场
                    </el-button>
                    <el-button type="primary" size="small" @click="loadNextWatchlist">下一页</el-button>
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
import { ElAffix, ElRow, ElCol, ElButton, ElCard, ElDivider, ElLink, ElRadioButton, ElRadioGroup, ElTag, ElScrollbar, ElTabs, ElTabPane, ElDatePicker } from 'element-plus';
import { useStockTradeStore } from '../stores/stockTradeStore';
import { useStockPickingStore } from '../stores/stockPickingStore';
import RecentReportBadge from './RecentReportBadge.vue';

const stockTradeStore = useStockTradeStore();
const stockPickingStore = useStockPickingStore();
const activeTab = ref('groupA');
const scope = ref('HO');
const baseURL = inject('baseURL');
const watchlist = ref([]);
const selectedResultDate = ref('');
const resultAvailableDates = ref([]);
const resultAvailableDateSet = computed(() => new Set(resultAvailableDates.value));

const from = ref(0);
const to = ref(50);
const indexIncre = ref(50)
const totalCount = ref(0)
const loading = ref(false)
const groupAMarkets = new Set(['HO', 'WL', 'RESULT'])
const groupBMarkets = new Set(['6', '0', '30', '688'])

const getDateCellKey = (cell) => {
    if (!cell) {
        return '';
    }
    const dayjsObj = cell.dayjs;
    if (!dayjsObj || typeof dayjsObj.format !== 'function') {
        return '';
    }
    return dayjsObj.format('YYYY-MM-DD');
};

const hasResultDate = (cell) => {
    const key = getDateCellKey(cell);
    return Boolean(key && resultAvailableDateSet.value.has(key));
};

const truncateText = (value, limit = 100) => {
    const text = String(value || '').trim();
    if (!text) {
        return '';
    }
    return text.length > limit ? `${text.slice(0, limit)}...` : text;
};

const resolveResultUndervalueScore = (stock) => {
    const direct = Number(stock?.undervalue_score);
    if (Number.isFinite(direct)) {
        return direct;
    }
    const metaValue = Number(stock?.result_meta?.undervalue_score);
    if (Number.isFinite(metaValue)) {
        return metaValue;
    }
    return null;
};

const sortResultByUndervalue = (order) => {
    if (scope.value !== 'RESULT') {
        return;
    }
    const direction = order === 'asc' ? 1 : -1;
    watchlist.value = [...watchlist.value].sort((a, b) => {
        const scoreA = resolveResultUndervalueScore(a);
        const scoreB = resolveResultUndervalueScore(b);
        if (scoreA === null && scoreB === null) {
            return String(a?.ts_code || '').localeCompare(String(b?.ts_code || ''));
        }
        if (scoreA === null) return 1;
        if (scoreB === null) return -1;
        if (scoreA === scoreB) {
            return String(a?.ts_code || '').localeCompare(String(b?.ts_code || ''));
        }
        return (scoreA - scoreB) * direction;
    });
};

const fetchWatchlist = async (market) => {
    loading.value = true;
    try {
        const params = new URLSearchParams();
        params.set('format', 'json');
        params.set('market', market);
        if (market === 'RESULT' && selectedResultDate.value) {
            params.set('pick_date', selectedResultDate.value);
        }
        const response = await axios.get(`${baseURL}/watchlist/${from.value}/${to.value}/?${params.toString()}`);
        let responseData = response.data;
        watchlist.value.push(...responseData.data);
        totalCount.value = responseData.total;
        if (market === 'RESULT' && Array.isArray(responseData.result_available_dates)) {
            resultAvailableDates.value = responseData.result_available_dates
                .map((item) => String(item || '').slice(0, 10))
                .filter((item) => Boolean(item));
        }
        if (market === 'RESULT' && !selectedResultDate.value && responseData.result_file_date) {
            selectedResultDate.value = responseData.result_file_date;
        }
        // set default tsCode and name
        if (watchlist.value.length > 0) {
            stockTradeStore.setTsCode(watchlist.value[0].ts_code);
            stockTradeStore.setName(watchlist.value[0].name);
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
    await fetchWatchlist(scope.value);
    // Prevent over-fetching if next "from" exceeds totalCount
    if (from.value >= totalCount.value) {
        from.value = totalCount.value;
        to.value = totalCount.value;
    }
};

const refreshCurrentMarketLoadedStocks = async () => {
    const loadedCount = watchlist.value.length;
    const targetCount = loadedCount > 0 ? loadedCount : indexIncre.value;

    from.value = 0;
    to.value = targetCount;
    watchlist.value = [];

    await fetchWatchlist(scope.value);

    // If loaded count exceeds total after refresh, normalize cursor.
    if (from.value >= totalCount.value) {
        from.value = totalCount.value;
        to.value = totalCount.value;
    }
};

const handleTabChange = async (tabName) => {
    if (tabName === 'groupA' && !groupAMarkets.has(scope.value)) {
        scope.value = 'HO';
    }
    if (tabName === 'groupB' && !groupBMarkets.has(scope.value)) {
        scope.value = '6';
    }
    await handleMarketChange(scope.value);
};

const handleMarketChange = async (market) => {
    from.value = 0;
    to.value = indexIncre.value;
    watchlist.value = [];
    await fetchWatchlist(market);
};

const handleResultDateChange = async () => {
    if (scope.value !== 'RESULT') {
        return;
    }
    await handleMarketChange('RESULT');
};

const handleStockClick = (name, ts_code) => {
    stockTradeStore.setName(name);
    stockTradeStore.setTsCode(ts_code);
};

onMounted(() => {
    fetchWatchlist(scope.value);
});

watch(
    () => stockPickingStore.pickingResults,
    (newResult, oldResult) => {
        console.log('pickingResult changed scanned on siderbar:', newResult);
        // You can add more logic here if needed when pickingResult changes
    }
);

defineOptions({
    name: 'Watchlist'
});
</script>

<style scoped>
.item {
    margin-top: 10px;
    margin-right: 20px;
}

.result-date-cell {
    position: relative;
    width: 24px;
    height: 24px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 12px;
}

.result-date-cell--marked {
    color: #c8161d;
    font-weight: 600;
}

.result-date-cell__dot {
    position: absolute;
    right: -2px;
    top: -2px;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #c8161d;
}
</style>