<template>
    <el-card style="max-width: 480px" v-loading="loading">
        <template #header>
            <div class="card-header">
                <el-row align="middle" justify="space-between" style="width: 100%;">
                    <el-col :span="8">
                        <span style="font-size: 14px;">相同标签</span>
                    </el-col>
                    <el-col :span="16" style="text-align: right;">
                        <el-tag type="danger" size="small" round>{{ similarTag }}</el-tag>
                    </el-col>
                </el-row>
            </div>
        </template>
        <template v-if="tagSimilarStocks.length === 0">
            <div style="text-align: center; color: #888; margin: 8px 0;">
                无股票
            </div>
        </template>
        <template v-else>
            <el-row v-for="(stock, idx) in tagSimilarStocks" :key="stock.ts_code"
                style="margin-bottom: 8px;font-size: small;">
                <el-col :span="24">
                    <div style="display: flex; align-items: center; gap: 12px;">
                        <el-link type="primary" href="#" @click.prevent="handleStockClick(stock.name, stock.ts_code)"
                            underline="never">
                            {{ stock.name }} | {{ stock.ts_code }}
                        </el-link>
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
                    <el-divider v-if="idx !== tagSimilarStocks.length - 1" style="margin: 8px 0;" />
                </el-col>
            </el-row>
        </template>
        <template #footer>
            <div style="text-align: right;">
                <el-button type="primary" size="small" @click="loadNextWatchlist">下一页</el-button>
            </div>
        </template>
    </el-card>
</template>

<script setup>
import { ref, defineOptions, inject } from 'vue'
import axios from 'axios';
import { ElAffix, ElCard, ElScrollbar, ElRow, ElCol, ElLink, ElTag, ElDivider, ElButton, ElRadioGroup, ElRadioButton } from 'element-plus';
import { useStockTradeStore } from '../stores/stockTradeStore';

const baseURL = inject('baseURL');
const stockTradeStore = useStockTradeStore();
const tagSimilarStocks = ref([]);
const similarTag = ref('无标签');
// const triggerBySelf = ref(false);
const fetchTagSimilar = async () => {
    try {
        tagSimilarStocks.value = [];
        const response = await axios.get(`${baseURL}/tags/similar/${stockTradeStore.tsCode}/`);
        let responseData = response.data;
        tagSimilarStocks.value.push(...responseData.data);
        similarTag.value = responseData.tags[0];
        // if (triggerBySelf) triggerBySelf = false
    } catch (error) {
        similarTag.value = '无标签';

        console.error('Error fetching tag:', error);
    } finally {
        // loading.value = false;
    }
};

const handleStockClick = (name, tsCode) => {
    stockTradeStore.setTsCode(tsCode);
    stockTradeStore.setName(name);
    // triggerBySelf.value = true;
};

import { onMounted } from 'vue';

onMounted(() => {
    fetchTagSimilar();
});

import { watch } from 'vue';

watch(
    () => stockTradeStore.tsCode,
    () => {
        // if (triggerBySelf.value) return;
        fetchTagSimilar();
    }
);

defineOptions({
    name: 'TagRelevant'
})
</script>