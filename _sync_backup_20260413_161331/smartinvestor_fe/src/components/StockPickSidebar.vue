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
                            <el-radio-group v-model="scope" size="small" @change="handleMarketChange">
                                <el-radio-button label="RESULT">选股结果</el-radio-button>
                                <el-radio-button label="HO">持仓</el-radio-button>
                            </el-radio-group>
                        </el-col>
                    </el-row>
                </div>
            </template>
            <el-scrollbar max-height="700px">
                <div v-for="(stock, idx) in watchlist" :key="stock" class="text item" style="font-size: 12px;">
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
                                    <span>{{ stock.basic_info.main_business }}</span>
                                </div>
                            </div>
                        </el-col>
                    </el-row>
                    <el-divider v-if="idx !== watchlist.length - 1" style="margin: 8px 0;" />
                </div>
                
            </el-scrollbar>
            <template #footer>
                <div style="text-align: right;">
                    <el-button type="primary" size="small" @click="loadNextWatchlist">下一页</el-button>
                </div>
            </template>
        </el-card>
    </el-affix>

    <!-- <el-backtop :right="100" :bottom="100" /> -->
</template>

<script setup>
import { inject, ref, onMounted, watch } from 'vue';
import axios from 'axios';
// Element Plus
import { ElAffix, ElRow, ElCol, ElButton, ElCard, ElDivider, ElLink, ElRadioButton, ElRadioGroup, ElTag, ElScrollbar } from 'element-plus';
import { useStockTradeStore } from '../stores/stockTradeStore';
import { useStockPickingStore } from '../stores/stockPickingStore';
import RecentReportBadge from './RecentReportBadge.vue';

const stockTradeStore = useStockTradeStore();
const stockPickingStore = useStockPickingStore();
const scope = ref('HO'); // Default hold a position
const baseURL = inject('baseURL');
const watchlist = ref([]);

const from = ref(0);
const to = ref(50);
const indexIncre = ref(50)
const totalCount = ref(0)
const loading = ref(false)

const fetchWatchlist = async (market) => {
    loading.value = true;
    try {
        const response = await axios.get(`${baseURL}/watchlist/${from.value}/${to.value}/?format=json&market=${market}`);
        let responseData = response.data;
        watchlist.value.push(...responseData.data);
        totalCount.value = responseData.total;
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

const handleMarketChange = async (market) => {
    from.value = 0;
    to.value = indexIncre.value;
    watchlist.value = [];
    await fetchWatchlist(market);
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
</style>