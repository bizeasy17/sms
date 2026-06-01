<template>
    <el-row :gutter="18">
        <el-col :span="tableResultSpan">
            <el-affix :offset="285">
                <el-card>
                    <el-scrollbar style="max-height: 400px; overflow: auto;">
                    <el-row>
                        <el-col :span="24">
                            <!-- First row content here -->
                            <el-table :data="pickingResult" style="width: 100%" size="small"
                                @row-dblclick="onRowDblClick">
                                <el-table-column prop="ts_code" label="代码" fixed="left">
                                    <template #default="{ row }">
                                        <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                                            <el-link type="primary" @click.stop="onStockClick(row)" style="font-size:12px"
                                                underline="never">{{ row.name + ' | ' + row.ts_code }}</el-link>
                                            <RecentReportBadge :visible="row.recent_report_badge" />
                                        </div>
                                    </template>
                                </el-table-column>
                                <el-table-column prop="top_or_bottom" label="高/低位">
                                    <template #default="{ row }">
                                        <el-tag v-if="row.top_or_bottom === 'B'" round
                                            effect="light" type="danger" size="small">底</el-tag>
                                        <el-tag v-else-if="row.top_or_bottom === 'T'" round
                                            effect="light" type="success" size="small">顶</el-tag>
                                    </template>
                                </el-table-column>
                                <el-table-column prop="close_qfq" label="收盘价" />
                                <el-table-column prop="pct_change_qfq" label="涨跌幅(%)">
                                    <template #default="{ row }">
                                        <span :style="{ color: row.pct_change_qfq >= 0 ? 'red' : 'green' }">
                                            {{ row.pct_change_qfq }}
                                        </span>
                                    </template>
                                </el-table-column>
                                <el-table-column prop="website" label="网站" :width="150">
                                    <template #default="{ row }">
                                        <el-link
                                            v-if="row.website"
                                            :href="row.website.startsWith('http') ? row.website : `https://${row.website}`"
                                            target="_blank"
                                            type="primary"
                                            style="font-size:12px"
                                            underline="hover"
                                        >
                                            {{ row.website }}
                                        </el-link>
                                        <span v-else>-</span>
                                    </template>
                                </el-table-column>
                                <el-table-column prop="main_business" label="主营业务" :width="350"/>
                                <!-- <el-table-column prop="freq" label="周期" />
                                <el-table-column prop="turnover_rate" label="换手率(%)" />
                                <el-table-column prop="turnover_rate_f" label="实际换手率(%)" />
                                <el-table-column prop="volume_ratio" label="量比" />
                                <el-table-column prop="pe" label="PE" />
                                <el-table-column prop="pe_ttm" label="PE(TTM)" />
                                <el-table-column prop="pb" label="PB" />
                                <el-table-column prop="ps" label="PS" />
                                <el-table-column prop="ps_ttm" label="PS(TTM)" />
                                <el-table-column prop="total_share" label="总股本(万)" />
                                <el-table-column prop="float_share" label="流通股本(万)" />
                                <el-table-column prop="free_share" label="自由流通股本(万)" />
                                <el-table-column prop="total_mv" label="总市值(百万)" />
                                <el-table-column prop="circ_mv" label="流通市值(百万)" />
                                <el-table-column prop="quantile_param" label="分位参数" /> -->
                            </el-table>

                        </el-col>
                    </el-row>
                    </el-scrollbar>
                    <el-row :gutter="12" style="margin-top: 10px;">
                        <el-col :span="controlSpan">
                            <!-- Second row content here -->
                            <el-button type="primary" @click="fetchPrevPage" size="small">上一页</el-button>

                            <el-button type="primary" @click="fetchNextPage" size="small">下一页</el-button>

                            <!-- Second row content here -->
                            <el-button type="primary" @click="expandTableResult" size="small">展开</el-button>
                        </el-col>
                    </el-row>
                </el-card>
            </el-affix>
        </el-col>
        <el-col :span="chartSpan">
            <StockChart :displayEmbed="true" />
        </el-col>
    </el-row>

</template>

<script setup lang="ts">
import { ElCard, ElTable, ElTableColumn, ElMessage, ElLink, ElRow, ElCol, 
    ElButton, ElAffix, ElScrollbar } from 'element-plus';
import { ref, watch, onMounted } from 'vue';
import axios from 'axios';
import { inject } from 'vue';
import { useStockPickingStore } from '../stores/stockPickingStore';
import { useStockTradeStore } from '../stores/stockTradeStore';
import { useStockChartFilterStore } from '../stores/stockChartFilterStore';
import StockChart from '../components/StockChart.vue';
import RecentReportBadge from './RecentReportBadge.vue';

const stockPickingStore = useStockPickingStore();
const stockTradeStore = useStockTradeStore();
const stockChartFilterStore = useStockChartFilterStore();

const tableResultSpan = ref(24);
const chartSpan = ref(0);
const controlSpan = ref(10);
const isResultTableElapsed = ref(false);

const fromIndex = ref(0);
const toIndex = ref(25);
const increment = ref(25);
const curFromIndex = ref(0);
const curToIndex = ref(25);

const baseURL = inject('baseURL');

const pickingResult = ref<Array<Record<string, any>>>([{
}]);


const onRowDblClick = (row: any) => {
    console.log(row);
    // pickingResultVisible.value = false;
    stockTradeStore.setTsCode(row.ts_code);
    stockTradeStore.setName(row.name);
    stockTradeStore.setWebsite(row.website);
    // Expand the result table if not already expanded

    if (!isResultTableElapsed.value) {
        tableResultSpan.value = 8;
        chartSpan.value = 16;
        controlSpan.value = 20;
        isResultTableElapsed.value = true;
    }
};

const expandTableResult = () => {
    isResultTableElapsed.value = false;
    tableResultSpan.value = 24;
    chartSpan.value = 0;
    controlSpan.value = 10;
};

const onStockClick = (row: any) => {
    console.log(row);
    stockTradeStore.setTsCode(row.ts_code);
    stockTradeStore.setName(row.name);
    stockTradeStore.setWebsite(row.website);
}

async function fetchPickingResult(
    date: string,
    scope: string,
    model: string,
    freq: string,
    period: string,
    stat: string,
    tech: string,
    ma: string,
    cost: string,
    modelVersion: string = '1.2',
    topOrBottom: string = 'TB:NONE',
    volumeChg: string = 'FEAT_DIFF:NONE',
    statPeriod: string = '60',
    volumeChgPct: string = 'FEAT_DIFF:NONE',
) {
    try {
        const isFirstPageRequest = fromIndex.value === 0;
        // Extract values after ':' if not 'NONE'
        const statVal = stat.split(':')[1] !== 'NONE' ? stat : '';
        const techVal = tech.split(':')[1] !== 'NONE' ? tech : '';
        const maVal = ma.split(':')[1] !== 'NONE' ? ma : '';
        const costVal = cost.split(':')[1] !== 'NONE' ? cost : '';
        // const volumeChgVal = volumeChg.split(':')[1] !== 'NONE' ? volumeChg.split(':')[1] : '';
        // const statPeriodVal = statPeriod.split(':')[1] !== 'NONE' ? statPeriod.split(':')[1] : '';
        const volChgVal = volumeChg.split(':')[1] !== 'NONE' && statPeriod.split(':')[1] !== 'NONE' && volumeChgPct.split(':')[1] !== 'NONE' ? volumeChg + '|' + statPeriod + '|' + volumeChgPct : ''; 
        const topOrBottomVal = topOrBottom.split(':')[1] !== 'NONE' ? topOrBottom.split(':')[1] : 'B,T';

        // Build param string, skip empty
        const paramsArr = [statVal, techVal, maVal, costVal, volChgVal].filter(Boolean);
        const paramsStr = paramsArr.join('|');
        const finalParamsStr = paramsStr || 'ALL';
        const url = `${baseURL}/stock-pick/${date}/${scope}/${model}/${modelVersion}/${topOrBottomVal}/${freq}/${period}/${finalParamsStr}/${fromIndex.value}/${toIndex.value}`;
        const res = await axios.get(url);
        if (res.data) {
            pickingResult.value = res.data.data;

            const responseData = res.data || {};
            const responseMeta = responseData.meta || {};
            const noResult = !Array.isArray(responseData.data) || responseData.data.length === 0;
            if (
                isFirstPageRequest &&
                noResult &&
                responseMeta.requested_trade_date_has_data === false
            ) {
                const latestDate = responseMeta.latest_trade_date_for_freq;
                ElMessage.warning(
                    latestDate
                        ? `当前选择日期 ${date} 无交易数据，最新可用交易日为 ${latestDate}`
                        : `当前选择日期 ${date} 无交易数据，请切换交易日后重试`
                );
            }

            curFromIndex.value = fromIndex.value;
            curToIndex.value = toIndex.value;
            fromIndex.value = toIndex.value;
            toIndex.value += increment.value;
            // If you want to store results in the store, assign to a reactive property instead, e.g.:
            const resultArr = res.data.data.map((item: any) => ({
                ts_code: item.ts_code,
                name: item.name,
                close_qfq: item.close_qfq,
                pct_change_qfq: item.pct_change_qfq
            }));
            stockPickingStore.setPickingResults(resultArr);
        }
    } catch (error) {
        console.error('Failed to fetch picking result:', error);
        ElMessage.error('获取选股结果失败，请稍后重试');
    }
}

async function fetchPrevPage() {
    if (curFromIndex.value <= 0) {
        return;
    }

    fromIndex.value = curFromIndex.value - increment.value;
    toIndex.value = curToIndex.value - increment.value;

    await fetchPickingResult(
        stockPickingStore.tradeDate,
        stockPickingStore.scopeParam,
        stockPickingStore.model,
        stockPickingStore.freq,
        stockPickingStore.period,
        stockPickingStore.statParam,
        stockPickingStore.techParam,
        stockPickingStore.maParam,
        stockPickingStore.costParam,
        stockPickingStore.modelVersion,
        stockPickingStore.topBottom,
        stockPickingStore.volumeChgParam,
        stockPickingStore.statPeriodParam,
        stockPickingStore.chgPctParam,
    );
}

async function fetchNextPage() {
    await fetchPickingResult(
        stockPickingStore.tradeDate,
        stockPickingStore.scopeParam,
        stockPickingStore.model,
        stockPickingStore.freq,
        stockPickingStore.period,
        stockPickingStore.statParam,
        stockPickingStore.techParam,
        stockPickingStore.maParam,
        stockPickingStore.costParam,
        stockPickingStore.modelVersion,
        stockPickingStore.topBottom,
        stockPickingStore.volumeChgParam,
        stockPickingStore.statPeriodParam,
        stockPickingStore.chgPctParam,
    );
}

watch(
    [
        () => stockPickingStore.tradeDate,
        () => stockPickingStore.scopeParam,
        () => stockPickingStore.model,
        () => stockPickingStore.freq,
        () => stockPickingStore.period,
        () => stockPickingStore.statParam,
        () => stockPickingStore.techParam,
        () => stockPickingStore.maParam,
        () => stockPickingStore.costParam,
        () => stockPickingStore.modelVersion,
        () => stockPickingStore.topBottom,
        () => stockPickingStore.volumeChgParam,
        () => stockPickingStore.statPeriodParam,
        () => stockPickingStore.chgPctParam,
    ],
    () => {
        fromIndex.value = 0;
        toIndex.value = 25;

        fetchPickingResult(
            stockPickingStore.tradeDate,
            stockPickingStore.scopeParam,
            stockPickingStore.model,
            stockPickingStore.freq,
            stockPickingStore.period,
            stockPickingStore.statParam,
            stockPickingStore.techParam,
            stockPickingStore.maParam,
            stockPickingStore.costParam,
            stockPickingStore.modelVersion,
            stockPickingStore.topBottom,
            stockPickingStore.volumeChgParam,
            stockPickingStore.statPeriodParam,
            stockPickingStore.chgPctParam,
        );
    }
);

onMounted(() => {
    fetchPickingResult(
        stockPickingStore.tradeDate,
        stockPickingStore.scopeParam,
        stockPickingStore.model,
        stockPickingStore.freq,
        stockPickingStore.period,
        stockPickingStore.statParam,
        stockPickingStore.techParam,
        stockPickingStore.maParam,
        stockPickingStore.costParam,
        stockPickingStore.modelVersion,
        stockPickingStore.topBottom,
        stockPickingStore.volumeChgParam,
        stockPickingStore.statPeriodParam,
        stockPickingStore.chgPctParam,
    );
    stockChartFilterStore.setTopBottomSwitch(true);
});
</script>

<style scoped></style>