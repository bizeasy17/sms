<template>
    <el-affix :offset="75">
        <el-card>
            <el-row :gutter="2" style="font-size: x-small; margin-bottom: 12px;color: gray;">
                <el-col :span="9">
                    <span style="display: flex; align-items: center;">
                        <span style="margin-right: 6px;">选股日期：</span>
                        <el-date-picker v-model="selectedDate" type="date" placeholder="选股日期" :size="'small'"
                            style="margin-right: 6px;" />

                    </span>
                </el-col>
                <el-col :span="5">
                    <!-- <span style="display: inline-block; vertical-align: middle;">模型：</span> -->
                    <el-radio-group v-model="selectedModel" size="small"
                        style="display: inline-block; vertical-align: middle; margin-left: 4px;">

                        <el-radio-button label="RF">RF</el-radio-button>
                        <el-radio-button label="XGB">XGB</el-radio-button>
                        <el-radio-button label="CAT">CAT</el-radio-button>
                    </el-radio-group>
                    <el-dropdown  @command="handleCommand">
                        <el-button size="small">v{{ mdlVersion }}</el-button>
                        <template #dropdown>
                            <el-dropdown-menu>
                                <el-dropdown-item command="1.1">1.1</el-dropdown-item>
                                <el-dropdown-item command="1.2">1.2</el-dropdown-item>
                                <el-dropdown-item command="1.3">1.3</el-dropdown-item>
                            </el-dropdown-menu>
                        </template>
                    </el-dropdown>
                </el-col>
                <el-col :span="5">
                    <span style="display: inline-block; vertical-align: middle;">周期：</span>
                    <el-radio-group v-model="selectedFreq" size="small"
                        style="display: inline-block; vertical-align: middle; margin-left: 4px;">
                        <el-radio-button label="D">日</el-radio-button>
                        <el-radio-button label="W">周</el-radio-button>
                        <el-radio-button label="M">月</el-radio-button>
                    </el-radio-group>

                </el-col>
                <el-col :span="5">
                    <span style="display: inline-block; vertical-align: middle;">时长：</span>
                    <el-radio-group v-model="selectedPickingPeriod" size="small"
                        style="display: inline-block; vertical-align: middle; margin-left: 4px;">
                        <el-radio-button label="30">30</el-radio-button>
                        <el-radio-button label="60">60</el-radio-button>
                        <el-radio-button label="200">200</el-radio-button>
                    </el-radio-group>

                </el-col>
            </el-row>
            <el-row :gutter="2" style="font-size: x-small; margin-bottom: 6px; color: gray;">
                <el-col :span="24">
                    <span style="display: inline-block; vertical-align: middle;">模型顶底：</span>
                    <el-radio-group v-model="selectedTopBottom" size="small"
                        style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="TB:NONE">请选择</el-radio-button>
                        <el-radio-button label="TB:T">顶</el-radio-button>
                        <el-radio-button label="TB:B">底</el-radio-button>
                    </el-radio-group>
                </el-col>
            </el-row>
            <el-row :gutter="2" style="font-size: x-small; margin-bottom: 6px; color: gray;">
                <el-col :span="24">
                    <span style="display: inline-block; vertical-align: middle;">统计低位：</span>
                    <el-radio-group v-model="selectedStat" size="small"
                        style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="STAT:NONE">请选择</el-radio-button>
                        <el-radio-button label="STAT:TVOL">成交量</el-radio-button>
                        <el-radio-button label="STAT:TCLOSE_QFQ">价格</el-radio-button>
                        <el-radio-button label="STAT:FTURNOVER_RATE">换手率</el-radio-button>
                        <el-radio-button label="STAT:FVOLUME_RATIO">量比</el-radio-button>
                        <el-radio-button label="STAT:FPE">PE</el-radio-button>
                        <el-radio-button label="STAT:FPB">PB</el-radio-button>
                        <el-radio-button label="STAT:FPS">PS</el-radio-button>
                    </el-radio-group>
                </el-col>
            </el-row>
            <el-row :gutter="2" style="font-size: x-small; margin-bottom: 6px; color: gray;">
                <el-col :span="24">
                    <span style="display: inline-block; vertical-align: middle;">成本分布：</span>
                    <el-radio-group v-model="selectedCost" size="small"
                        style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="COST:NONE">请选择</el-radio-button>
                        <el-radio-button label="COST:5">5pct</el-radio-button>
                        <el-radio-button label="COST:15">15pct</el-radio-button>
                        <el-radio-button label="COST:50">50pct</el-radio-button>
                        <el-radio-button label="COST:85">85pct</el-radio-button>
                        <el-radio-button label="COST:95">95pct</el-radio-button>
                    </el-radio-group>
                </el-col>
            </el-row>
            <el-row :gutter="2" style="font-size: x-small; margin-bottom: 6px;color: gray;">
                <el-col :span="24">
                    <span style="display: inline-block; vertical-align: middle;">技术形态：</span>
                    <el-radio-group v-model="selectedKShape" size="small"
                        style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="FEAT:NONE">请选择</el-radio-button>
                        <el-radio-button label="FEAT:IS_UPPER_SHADOW_SHAPE">上长阴影</el-radio-button>
                        <el-radio-button label="FEAT:IS_LOWER_SHADOW_SHAPE">下长阴影</el-radio-button>
                        <!-- <el-radio-button label="FEAT:TDOJI">十字星</el-radio-button> -->
                        <el-radio-button label="FEAT:IS_BULLISH_AND_DIVERGENT">多头发散</el-radio-button>
                        <el-radio-button label="FEAT:IS_BEARISH_AND_DIVERGENT">空头发散</el-radio-button>

                    </el-radio-group>
                </el-col>
            </el-row>
            <el-row :gutter="2" style="font-size: x-small; margin-bottom: 6px;color: gray;">
                <el-col :span="6">
                    <span style="display: inline-block; vertical-align: middle;">成交变化：</span>
                    <el-radio-group v-model="selectedVolumeChg" size="small"
                        style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="FEAT_DIFF:NONE">请选择</el-radio-button>
                        <el-radio-button label="FEAT_DIFF:CLOSE_QFQ_X_10PCT|VOL_X_10PCT">低位放量</el-radio-button>
                        <el-radio-button label="FEAT_DIFF:CLOSE_QFQ_X_90PCT|VOL_X_90PCT">高位放量</el-radio-button>
                    </el-radio-group>
                </el-col>
                <el-col :span="7">
                    <span style="display: inline-block; vertical-align: middle;">统计周期：</span>
                    <el-radio-group v-model="selectedStatPeriod" size="small"
                        style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="FEAT_DIFF:NONE">请选择</el-radio-button>
                        <el-radio-button label="30D">30</el-radio-button>
                        <el-radio-button label="60D">60</el-radio-button>
                        <el-radio-button label="90D">90</el-radio-button>
                        <el-radio-button label="120D">120</el-radio-button>
                        <el-radio-button label="200D">200</el-radio-button>
                    </el-radio-group>
                </el-col>
                <el-col :span="9">
                    <span style="display: inline-block; vertical-align: middle;">变化率：</span>
                    <el-radio-group v-model="selectedChgPct" size="small"
                        style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="FEAT_DIFF:NONE">请选择</el-radio-button>
                        <el-radio-button label="0.3">30%</el-radio-button>
                        <el-radio-button label="0.5">50%</el-radio-button>
                        <el-radio-button label="1.0">100%</el-radio-button>
                        <el-radio-button label="2.0">200%</el-radio-button>
                    </el-radio-group>
                </el-col>
            </el-row>
            <el-row :gutter="2" style="font-size: x-small; margin-bottom: 6px; color: gray;">
                <el-col :span="24">
                    <span style="display: inline-block; vertical-align: middle;">均线缠绕：</span>
                    <el-radio-group v-model="selectedMAETG" size="small"
                        style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="FEAT:NONE">请选择</el-radio-button>
                        <el-radio-button label="FEAT:MA6_MA10_ENTANGLED">MA6/10</el-radio-button>
                        <el-radio-button label="FEAT:MA6_MA10_MA25_ENTANGLED">MA6/10/25</el-radio-button>
                        <el-radio-button label="FEAT:MA6_MA10_MA25_MA60_ENTANGLED">MA6/10/25/60</el-radio-button>
                        <el-radio-button label="FEAT:MA6_MA10_MA25_MA60_MA120_MA200_ENTANGLED">MA6/10/25/60/120/200</el-radio-button>
                    </el-radio-group>
                </el-col>
            </el-row>
            <el-row :gutter="2" style="font-size: x-small;color: gray;">
                <el-col :span="24" style="">
                    <span style="display: inline-block; vertical-align: middle;">选股范围：</span>
                    <el-radio-group v-model="selectedScope" size="small"
                        style="display: inline-block; vertical-align: middle; margin-left: 8px;">
                        <el-radio-button label="SCOPE:NONE">请选择</el-radio-button>
                        <el-radio-button label="WATCHLIST">自</el-radio-button>
                        <el-radio-button label="60">沪</el-radio-button>
                        <el-radio-button label="0">深</el-radio-button>
                        <el-radio-button label="3">创</el-radio-button>
                        <el-radio-button label="688">科</el-radio-button>
                    </el-radio-group>
                </el-col>
            </el-row>
        </el-card>
    </el-affix>

</template>

<script setup lang="ts">
import { ref } from 'vue';
// Element Plus;
import { ElButton, ElRow, ElCol, ElCard, ElRadioGroup, ElRadioButton, ElAffix, ElDatePicker, ElDropdown, ElDropdownMenu, ElDropdownItem } from 'element-plus';
import { useStockTradeStore } from '../stores/stockTradeStore';
import { useStockPickingStore } from '../stores/stockPickingStore';
import { watch } from 'vue';


const stockTradeStore = useStockTradeStore();
const stockPickingStore = useStockPickingStore();

const selectedModel = ref('XGB');
const selectedPickingPeriod = ref('60');
const selectedTopBottom = ref('TB:NONE');
const selectedFreq = ref('D');
const selectedMAETG = ref('FEAT:NONE');
const selectedDate = ref(new Date());
const selectedStat = ref('STAT:NONE');

const selectedKShape = ref('FEAT:NONE');
const selectedVolumeChg = ref('FEAT_DIFF:NONE');
const selectedStatPeriod = ref('FEAT_DIFF:NONE');
const selectedChgPct = ref('FEAT_DIFF:NONE');
const selectedScope = ref('SCOPE:NONE');
const selectedCost = ref('COST:NONE');

const mdlVersion = ref('1.1');

// Add handleCommand method for el-dropdown
function handleCommand(command: string) {
    mdlVersion.value = command;
}

watch(
    () => stockTradeStore.tsCode,
    (newTsCode) => {
        if (newTsCode) {
            // You can add logic here if needed when tsCode changes
        }
    }
);


watch(
    [
        selectedStatPeriod,
        selectedVolumeChg,
        selectedChgPct,
        selectedFreq,
        selectedDate,
        selectedModel,
        selectedKShape,
        selectedStat,
        selectedMAETG,
        selectedScope,
        selectedCost,
        mdlVersion,
        selectedTopBottom
    ],
    () => {
        stockPickingStore.setTradeDate(
            selectedDate.value instanceof Date
                ? new Date(selectedDate.value.getTime() - selectedDate.value.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
                : selectedDate.value
        );
        stockPickingStore.setModel(selectedModel.value);
        stockPickingStore.setPeriod(selectedPickingPeriod.value);
        stockPickingStore.setFreq(selectedFreq.value);
        stockPickingStore.setTechParam(selectedKShape.value);
        stockPickingStore.setStatParam(selectedStat.value);
        stockPickingStore.setScopeParam(selectedScope.value);
        stockPickingStore.setMaParam(selectedMAETG.value);
        stockPickingStore.setVolumeChgParam(selectedVolumeChg.value);
        stockPickingStore.setCostParam(selectedCost.value);
        stockPickingStore.setModelVersion(mdlVersion.value);
        stockPickingStore.setTopBottom(selectedTopBottom.value);
        stockPickingStore.setStatPeriod(selectedStatPeriod.value);
        stockPickingStore.setVolumeChgParam(selectedVolumeChg.value);
        stockPickingStore.setChgPctParam(selectedChgPct.value);
        // chartFilterStore.setFreq(selectedFreq.value);
        // chartFilterStore.setPeriod(selectedPeriod.value);
        // chartFilterStore.setModel(selectedModel.value);
        // chartFilterStore.setTopBottomSwitch(true);
    }
);

defineOptions({
    name: 'StockPickingFilter'
});
</script>

<style scoped></style>