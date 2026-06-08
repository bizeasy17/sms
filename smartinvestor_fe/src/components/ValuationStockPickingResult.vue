<template>
    <el-row :gutter="18">
        <el-col :span="24">
            <el-card>
                    <el-row style="margin-bottom: 10px;">
                        <el-col :span="24" style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
                            <span style="font-size: 12px; color: #606266;">周度低估清单下载：</span>
                            <el-link
                                v-if="downloadLinks.traditional.available && downloadLinks.traditional.downloadUrl"
                                :href="downloadLinks.traditional.downloadUrl"
                                type="primary"
                                underline="hover"
                                target="_blank"
                            >
                                下载传统估值 CSV
                            </el-link>
                            <span v-else style="font-size: 12px; color: #909399;">传统估值 CSV 未生成</span>
                            <span v-if="downloadLinks.traditional.updatedAt" style="font-size: 12px; color: #909399;">
                                {{ downloadLinks.traditional.updatedAt }}
                            </span>

                            <el-link
                                v-if="downloadLinks.predictive.available && downloadLinks.predictive.downloadUrl"
                                :href="downloadLinks.predictive.downloadUrl"
                                type="success"
                                underline="hover"
                                target="_blank"
                            >
                                下载预测估值 CSV
                            </el-link>
                            <span v-else style="font-size: 12px; color: #909399;">预测估值 CSV 未生成</span>
                            <span v-if="downloadLinks.predictive.updatedAt" style="font-size: 12px; color: #909399;">
                                {{ downloadLinks.predictive.updatedAt }}
                            </span>
                        </el-col>
                    </el-row>
                    <el-row v-if="showFinancialStageHint" style="margin-bottom: 8px;">
                        <el-col :span="24">
                            <el-tag size="small" type="warning" effect="light">
                                财务条件二阶段过滤已启用：首轮先按估值/风险出候选，再按净利YoY、EBITYoY和上一年净利/EBIT条件过滤。
                            </el-tag>
                        </el-col>
                    </el-row>
                    <el-row>
                        <el-col :span="24">
                            <el-table :data="pickingResult" style="width: 100%" size="small" height="400" @row-dblclick="onRowDblClick">
                                    <el-table-column prop="ts_code" label="代码" fixed="left">
                                        <template #default="{ row }">
                                            <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                                                <el-link type="primary" @click.stop="onStockClick(row)" style="font-size:12px" underline="never">{{ row.name + ' | ' + row.ts_code }}</el-link>
                                                <RecentReportBadge :visible="row.recent_report_badge" />
                                            </div>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="signal_peak_return_pct" label="最高涨幅(%)" :width="138">
                                        <template #default="{ row }">
                                            <span :style="{ color: (row.signal_peak_return_pct || 0) >= 0 ? 'red' : 'green' }">{{ formatPercentWithSymbol(row.signal_peak_return_pct) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="signal_trough_return_pct" label="最低涨幅(%)" :width="138">
                                        <template #default="{ row }">
                                            <span :style="{ color: (row.signal_trough_return_pct || 0) >= 0 ? 'red' : 'green' }">{{ formatPercentWithSymbol(row.signal_trough_return_pct) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="signal_current_return_pct" label="当前涨幅(%)" :width="138">
                                        <template #default="{ row }">
                                            <span :style="{ color: (row.signal_current_return_pct || 0) >= 0 ? 'red' : 'green' }">{{ formatPercentWithSymbol(row.signal_current_return_pct) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="sw_l3_name" label="SW行业" :width="150">
                                        <template #default="{ row }">
                                            <span>{{ row.sw_l3_name || row.industry_name || '-' }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="valuation_method" label="估值法" :width="90">
                                        <template #default="{ row }">
                                            <span>{{ methodLabel(row.valuation_method) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="close_qfq" label="当前价格" :width="90">
                                        <template #default="{ row }">
                                            <span>{{ formatPrice(row.close_qfq) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="valuation_price" label="估值价" :width="90" />
                                    <el-table-column prop="valuation_snapshot_updated_at" label="快照更新时间" :width="170">
                                        <template #default="{ row }">
                                            <span>{{ formatDateTime(row.valuation_snapshot_updated_at) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="valuation_profit_report_ann_date" label="财报发布日" :width="120">
                                        <template #default="{ row }">
                                            <span>{{ formatDateOnly(row.valuation_profit_report_ann_date || row.financial_ann_date) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="conservative_valuation_price" label="保守估值价" :width="110">
                                        <template #default="{ row }">
                                            <span>{{ formatPrice(row.conservative_valuation_price) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="composite_valuation_price" label="组合估值价" :width="110">
                                        <template #default="{ row }">
                                            <span>{{ formatPrice(row.composite_valuation_price) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="valuation_gap_pct" label="偏离(%)" :width="90">
                                        <template #default="{ row }">
                                            <span :style="{ color: (row.valuation_gap_pct || 0) >= 0 ? 'red' : 'green' }">{{ row.valuation_gap_pct ?? '-' }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="valuation_status" label="估值判断" :width="90">
                                        <template #default="{ row }">
                                            <el-tag v-if="row.valuation_status === 'under'" round effect="light" type="danger" size="small">低估</el-tag>
                                            <el-tag v-else-if="row.valuation_status === 'over'" round effect="light" type="success" size="small">高估</el-tag>
                                            <el-tag v-else-if="row.valuation_status === 'fair'" round effect="light" type="info" size="small">正常</el-tag>
                                            <span v-else>-</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="buy_candidate" label="候选" :width="88">
                                        <template #default="{ row }">
                                            <el-tag v-if="row.buy_candidate" round effect="light" type="danger" size="small">可买</el-tag>
                                            <el-tag v-else round effect="light" type="info" size="small">观察</el-tag>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="valuation_score" label="估值分数" :width="88">
                                        <template #default="{ row }">
                                            <span :style="{ color: getUndervalueScoreColor(row.valuation_score ?? row.undervalue_score) }">{{ formatScore(row.valuation_score ?? row.undervalue_score) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="!isPredictiveMode" prop="valuation_risk_level" label="风险级别" :width="92">
                                        <template #default="{ row }">
                                            <el-tag v-if="traditionalRiskTagType(row.valuation_risk_level)" round effect="light" :type="traditionalRiskTagType(row.valuation_risk_level)" size="small">{{ riskLabel(row.valuation_risk_level) }}</el-tag>
                                            <span v-else>-</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="financial_netprofit_yoy" label="净利YoY(%)" :width="95">
                                        <template #default="{ row }">
                                            <span>{{ formatPercent(row.financial_netprofit_yoy) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="financial_ebit_yoy" label="EBITYoY(%)" :width="95">
                                        <template #default="{ row }">
                                            <span>{{ formatPercent(row.financial_ebit_yoy) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="financial_prev_netprofit" label="上一年净利" :width="95">
                                        <template #default="{ row }">
                                            <el-tag :type="Number(row.financial_prev_netprofit) >= 0 ? 'success' : 'danger'" size="small" effect="light">
                                                {{ Number.isFinite(Number(row.financial_prev_netprofit)) ? (Number(row.financial_prev_netprofit) >= 0 ? '>=0' : '<0') : '-' }}
                                            </el-tag>
                                        </template>
                                    </el-table-column>
                                    <el-table-column prop="financial_prev_ebit" label="上一年EBIT" :width="95">
                                        <template #default="{ row }">
                                            <el-tag :type="Number(row.financial_prev_ebit) >= 0 ? 'success' : 'danger'" size="small" effect="light">
                                                {{ Number.isFinite(Number(row.financial_prev_ebit)) ? (Number(row.financial_prev_ebit) >= 0 ? '>=0' : '<0') : '-' }}
                                            </el-tag>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="isPredictiveMode" prop="earnings_report_type" label="报告口径" :width="90">
                                        <template #default="{ row }">
                                            <el-tag round effect="light" type="primary" size="small">{{ row.earnings_report_type || '-' }}</el-tag>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="isPredictiveMode" prop="signal_score" label="信号分" :width="88">
                                        <template #default="{ row }">
                                            <span :style="{ color: getSignalScoreColor(row.signal_score) }">{{ formatScore(row.signal_score) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="isPredictiveMode" prop="action" label="操作建议" :width="90">
                                        <template #default="{ row }">
                                            <el-tag v-if="actionTagType(row.action)" round effect="light" :type="actionTagType(row.action)" size="small">{{ actionLabel(row.action) }}</el-tag>
                                            <span v-else>-</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="isPredictiveMode" prop="risk_level" label="风险级别" :width="92">
                                        <template #default="{ row }">
                                            <el-tag v-if="riskTagType(row.risk_level)" round effect="light" :type="riskTagType(row.risk_level)" size="small">{{ riskLabel(row.risk_level) }}</el-tag>
                                            <span v-else>-</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="isPredictiveMode" prop="target_price" label="目标价" :width="88">
                                        <template #default="{ row }">
                                            <span>{{ formatPrice(row.target_price) }}</span>
                                        </template>
                                    </el-table-column>
                                    <el-table-column v-if="isPredictiveMode" prop="target_return_pct" label="目标收益率(%)" :width="110">
                                        <template #default="{ row }">
                                            <span :style="{ color: (row.target_return_pct || 0) >= 0 ? 'red' : 'green' }">{{ formatPercent(row.target_return_pct) }}</span>
                                        </template>
                                    </el-table-column>
                            </el-table>
                        </el-col>
                    </el-row>
                    <el-row :gutter="12" style="margin-top: 10px;">
                        <el-col :span="controlSpan">
                            <el-button type="primary" @click="fetchPrevPage" size="small">上一页</el-button>
                            <el-button type="primary" @click="fetchNextPage" size="small">下一页</el-button>
                            <el-button type="warning" plain @click="sortByUndervalue('desc')" size="small">低估分降序</el-button>
                            <el-button type="warning" plain @click="sortByUndervalue('asc')" size="small">低估分升序</el-button>
                            <span style="margin-left: 10px; color: #606266; font-size: 12px;">
                                命中总数: {{ totalFiltered }} | 当前范围: {{ currentRangeStart }}-{{ currentRangeEnd }}
                            </span>
                        </el-col>
                    </el-row>
            </el-card>
        </el-col>
    </el-row>

    <el-dialog
        v-model="detailDialogVisible"
        width="80%"
        top="5vh"
        destroy-on-close
    >
        <template #header>
            <div class="stock-title-actions">
                <div class="stock-title-left">
                    <el-text type="primary" tag="b">
                        <span class="stock-name-link">{{ detailDialogTitle }}</span>
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
                    <el-check-tag
                        :checked="isObserved"
                        @change="toggleObserveStatus"
                        class="compact-toggle-tag compact-toggle-observe"
                    >
                        <span class="compact-toggle-label compact-observe-label">关注</span>
                    </el-check-tag>
                </div>
            </div>
        </template>
        <div style="margin-bottom: 10px; display: flex; align-items: center; gap: 8px;">
            <el-button size="small" @click="switchDetailStock(-1)" :disabled="!hasPrevStock">前一只</el-button>
            <el-button size="small" @click="switchDetailStock(1)" :disabled="!hasNextStock">后一只</el-button>
            <span style="color: #909399; font-size: 12px;">{{ detailPositionText }}</span>
        </div>
        <el-tabs v-model="overviewTab" class="overview-tabs">
            <el-tab-pane label="估值一览" name="valuation">
                <StockValuationQuickView :embedded="true" />
            </el-tab-pane>
            <el-tab-pane label="技术趋势" name="trend" lazy>
                <div class="trend-tab-panel">
                    <StockChart ref="trendChartCompRef" :display-embed="true" :show-bottom-in-embed="true" />
                </div>
            </el-tab-pane>
            <el-tab-pane label="成本 / 财报" name="finance" lazy>
                <div class="finance-tab-panel">
                    <FinanceRelevant />
                </div>
            </el-tab-pane>
        </el-tabs>
        <template #footer>
            <div style="display: flex; justify-content: space-between; width: 100%;">
                <div>
                    <el-button @click="switchDetailStock(-1)" :disabled="!hasPrevStock">前一只</el-button>
                    <el-button @click="switchDetailStock(1)" :disabled="!hasNextStock">后一只</el-button>
                </div>
                <el-button type="primary" @click="detailDialogVisible = false">关闭</el-button>
            </div>
        </template>
    </el-dialog>
</template>

<script setup lang="ts">
import { ElCard, ElTable, ElTableColumn, ElMessage, ElLink, ElRow, ElCol, ElButton, ElTag, ElTabs, ElTabPane, ElDialog, ElCheckTag, ElText } from "element-plus";
import { computed, ref, watch, onMounted, nextTick } from "vue";
import axios from "axios";
import { inject } from "vue";
import { useValuationStockPickingStore } from "../stores/valuationStockPickingStore";
import { useStockTradeStore } from "../stores/stockTradeStore";
import { useStockChartFilterStore } from "../stores/stockChartFilterStore";
import StockChart from "../components/StockChart.vue";
import StockValuationQuickView from "./StockValuationQuickView.vue";
import FinanceRelevant from "./FinanceRelevant.vue";
import RecentReportBadge from "./RecentReportBadge.vue";

const valuationStockPickingStore = useValuationStockPickingStore();
const stockTradeStore = useStockTradeStore();
const stockChartFilterStore = useStockChartFilterStore();

const controlSpan = ref(10);
const detailDialogVisible = ref(false);
const detailRowIndex = ref(-1);
const isHolding = ref(false);
const isInWatchlist = ref(false);
const isObserved = ref(false);
const QUICK_PREVIEW_SCAN_LIMIT = "500";

const fromIndex = ref(0);
const toIndex = ref(25);
const increment = ref(25);
const curFromIndex = ref(0);
const curToIndex = ref(25);
const totalFiltered = ref(0);
const currentRangeStart = ref(0);
const currentRangeEnd = ref(0);
const effectiveFinancialFilters = ref<Record<string, any>>({});
const overviewTab = ref("valuation");
const trendChartCompRef = ref<InstanceType<typeof StockChart> | null>(null);

const baseURL = inject<string>("baseURL", "");
const pickingResult = ref<Array<Record<string, any>>>([]);
const isPredictiveMode = computed(() => valuationStockPickingStore.pickingMode === "MODE:PREDICTIVE");
const downloadLinks = ref({
    traditional: {
        available: false,
        downloadUrl: "",
        updatedAt: "",
    },
    predictive: {
        available: false,
        downloadUrl: "",
        updatedAt: "",
    },
});

const hasPrevStock = computed(() => detailRowIndex.value > 0);
const hasNextStock = computed(() => detailRowIndex.value >= 0 && detailRowIndex.value < pickingResult.value.length - 1);
const detailPositionText = computed(() => {
    if (detailRowIndex.value < 0 || pickingResult.value.length === 0) {
        return "";
    }
    return `${detailRowIndex.value + 1} / ${pickingResult.value.length}`;
});
const detailDialogTitle = computed(() => {
    if (detailRowIndex.value < 0 || detailRowIndex.value >= pickingResult.value.length) {
        return "个股详情";
    }
    const row = pickingResult.value[detailRowIndex.value] || {};
    return `${row.name || ""} | ${row.ts_code || ""}`.trim() || "个股详情";
});
const showFinancialStageHint = computed(() => {
    if (isPredictiveMode.value) {
        return false;
    }
    const filters = effectiveFinancialFilters.value || {};
    const applyFinancialFilters = Boolean(filters.apply_financial_filters);
    if (!applyFinancialFilters) {
        return false;
    }
    const hasNumericThreshold = (value: any) => {
        if (value === null || value === undefined || String(value).trim() === "") {
            return false;
        }
        const numeric = Number(value);
        return Number.isFinite(numeric);
    };
    const requirePrevNetprofit = Boolean(filters.require_positive_prev_netprofit);
    const requirePrevEbit = Boolean(filters.require_positive_prev_ebit);
    return hasNumericThreshold(filters.min_netprofit_yoy)
        || hasNumericThreshold(filters.min_ebit_yoy)
        || requirePrevNetprofit
        || requirePrevEbit;
});

function resolvePreferredValuationVariant(row: any) {
    const directVariant = String(row?.valuation_variant || "").trim();
    if (directVariant) {
        return directVariant;
    }
    const metaVariant = String(row?.result_meta?.valuation_variant || "").trim();
    if (metaVariant) {
        return metaVariant;
    }
    return "";
}

function buildApiUrl(path: string) {
    const base = String(baseURL || "").replace(/\/+$/, "");
    const normalizedPath = path.startsWith("/") ? path : `/${path}`;
    if (base.endsWith("/api") && normalizedPath.startsWith("/api/")) {
        return `${base}${normalizedPath.slice(4)}`;
    }
    return `${base}${normalizedPath}`;
}

function normalizeScopeForApi(scopeRaw: string): string {
    return String(scopeRaw || "")
        .split(",")
        .map((item) => item.trim())
        .filter((item) => !!item)
        .map((item) => {
            if (item === "0") return "00";
            if (item === "3") return "30";
            if (item === "688") return "68";
            return item;
        })
        .join(",");
}

async function loadWeeklyDownloadLinks() {
    if (!baseURL) {
        return;
    }
    try {
        const res = await axios.get(buildApiUrl("/stock-pick-valuation/weekly-downloads/"));
        const data = res?.data?.data || {};
        downloadLinks.value = {
            traditional: {
                available: Boolean(data?.traditional?.available),
                downloadUrl: data?.traditional?.download_url ? buildApiUrl(data.traditional.download_url) : "",
                updatedAt: data?.traditional?.updated_at || "",
            },
            predictive: {
                available: Boolean(data?.predictive?.available),
                downloadUrl: data?.predictive?.download_url ? buildApiUrl(data.predictive.download_url) : "",
                updatedAt: data?.predictive?.updated_at || "",
            },
        };
    } catch (_error) {
        downloadLinks.value = {
            traditional: { available: false, downloadUrl: "", updatedAt: "" },
            predictive: { available: false, downloadUrl: "", updatedAt: "" },
        };
    }
}

function syncDetailStock(row: any) {
    stockTradeStore.setTsCode(row.ts_code);
    stockTradeStore.setName(row.name);
    stockTradeStore.setWebsite(row.website);
    stockTradeStore.setPreferredValuationVariant(resolvePreferredValuationVariant(row));
}

function clearDetailStockStatus() {
    isHolding.value = false;
    isInWatchlist.value = false;
    isObserved.value = false;
}

function toCanonicalTsCode(code: string) {
    const normalized = String(code || "").trim().toUpperCase();
    if (!normalized) return "";
    if (normalized.includes(".")) return normalized;
    if (!/^\d{6}$/.test(normalized)) return normalized;
    if (normalized.startsWith("6") || normalized.startsWith("5") || normalized.startsWith("9")) return `${normalized}.SH`;
    if (normalized.startsWith("8") || normalized.startsWith("4")) return `${normalized}.BJ`;
    return `${normalized}.SZ`;
}

function buildTsCodeCandidates(code: string) {
    const normalized = String(code || "").trim().toUpperCase();
    const base = normalized.split(".")[0];
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

async function fetchDetailStockStatus(tsCode: string) {
    clearDetailStockStatus();
    if (!baseURL || !tsCode) {
        return;
    }
    try {
        const candidates = buildTsCodeCandidates(tsCode);
        let fallbackData: any = null;
        for (const candidate of candidates) {
            const res = await axios.get(`${baseURL}/watchlist/check/${candidate}/`);
            if (!res.data) {
                continue;
            }
            if (!fallbackData) {
                fallbackData = res.data;
            }
            if (res.data.hold_position || res.data.in_watchlist || res.data.observe_status) {
                isHolding.value = !!res.data.hold_position;
                isInWatchlist.value = !!res.data.in_watchlist;
                isObserved.value = !!res.data.observe_status;
                return;
            }
        }
        if (fallbackData) {
            isHolding.value = !!fallbackData.hold_position;
            isInWatchlist.value = !!fallbackData.in_watchlist;
            isObserved.value = !!fallbackData.observe_status;
        }
    } catch (_error) {
        clearDetailStockStatus();
    }
}

async function toggleWatchlistStatus(watchlist: boolean) {
    try {
        const tsCode = String(stockTradeStore.tsCode || "").trim();
        if (!baseURL || !tsCode) {
            return;
        }
        const res = watchlist
            ? await axios.post(`${baseURL}/watchlist/add/${tsCode}/`)
            : await axios.put(`${baseURL}/watchlist/delete/${tsCode}/`);
        if (res.status === 200) {
            isInWatchlist.value = !!res.data.in_watchlist;
            isHolding.value = !!res.data.hold_position;
            isObserved.value = !!res.data.observe_status;
            ElMessage.success(isInWatchlist.value ? '已加入自选股' : '已移除自选股');
        }
    } catch (error) {
        console.error('Failed to toggle watchlist status:', error);
        ElMessage.error('操作失败，请稍后重试');
    }
}

async function toggleHoldingStatus(hold: boolean) {
    try {
        const tsCode = String(stockTradeStore.tsCode || "").trim();
        if (!baseURL || !tsCode) {
            return;
        }
        const res = await axios({
            url: hold ? `${baseURL}/watchlist/hold/${tsCode}/` : `${baseURL}/watchlist/unhold/${tsCode}/`,
            method: hold ? 'post' : 'put',
        });
        if (res.status === 200) {
            isHolding.value = !!res.data.hold_position;
            isInWatchlist.value = !!res.data.in_watchlist;
            isObserved.value = !!res.data.observe_status;
            ElMessage.success(isHolding.value ? '已标记为持仓' : '已取消持仓标记');
        }
    } catch (error) {
        console.error('Failed to toggle holding status:', error);
        ElMessage.error('操作失败，请稍后重试');
    }
}

async function toggleObserveStatus(observe: boolean) {
    try {
        const tsCode = String(stockTradeStore.tsCode || "").trim();
        if (!baseURL || !tsCode) {
            return;
        }
        const res = await axios({
            url: observe ? `${baseURL}/watchlist/observe/${tsCode}/` : `${baseURL}/watchlist/unobserve/${tsCode}/`,
            method: observe ? 'post' : 'put',
        });
        if (res.status === 200) {
            isObserved.value = !!res.data.observe_status;
            isHolding.value = !!res.data.hold_position;
            isInWatchlist.value = !!res.data.in_watchlist;
            ElMessage.success(isObserved.value ? '已标记为关注' : '已取消关注');
        }
    } catch (error) {
        console.error('Failed to toggle observe status:', error);
        ElMessage.error('操作失败，请稍后重试');
    }
}

async function openDetailAt(index: number) {
    if (index < 0 || index >= pickingResult.value.length) {
        return;
    }
    detailRowIndex.value = index;
    syncDetailStock(pickingResult.value[index]);
    await fetchDetailStockStatus(String(pickingResult.value[index]?.ts_code || ""));
    detailDialogVisible.value = true;
}

const onRowDblClick = (row: any) => {
    const idx = pickingResult.value.indexOf(row);
    if (idx >= 0) {
        openDetailAt(idx);
        return;
    }
    const code = String(row?.ts_code || "").trim().toUpperCase();
    const fallbackIdx = pickingResult.value.findIndex((item) => String(item?.ts_code || "").trim().toUpperCase() === code);
    openDetailAt(fallbackIdx);
};

function switchDetailStock(offset: number) {
    if (detailRowIndex.value < 0) {
        return;
    }
    const nextIndex = detailRowIndex.value + offset;
    if (nextIndex < 0 || nextIndex >= pickingResult.value.length) {
        return;
    }
    void openDetailAt(nextIndex);
}

watch(
    () => overviewTab.value,
    (tab) => {
        if (tab !== "trend") {
            return;
        }
        nextTick(() => {
            trendChartCompRef.value?.refreshTrendLayout?.();
        });
    }
);

const onStockClick = (row: any) => {
    syncDetailStock(row);
};

function formatPrice(value: any) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "-";
    return numeric.toFixed(2);
}

function formatPercent(value: any) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "-";
    return numeric.toFixed(2);
}

function formatPercentWithSymbol(value: any) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "-";
    return `${numeric.toFixed(2)}%`;
}

function formatScore(value: any) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "-";
    return numeric.toFixed(0);
}

function formatDateTime(value: any) {
    const text = String(value || "").trim();
    if (!text) return "-";
    const parsed = new Date(text);
    if (Number.isNaN(parsed.getTime())) {
        return text;
    }
    const yyyy = parsed.getFullYear();
    const mm = String(parsed.getMonth() + 1).padStart(2, "0");
    const dd = String(parsed.getDate()).padStart(2, "0");
    const hh = String(parsed.getHours()).padStart(2, "0");
    const mi = String(parsed.getMinutes()).padStart(2, "0");
    const ss = String(parsed.getSeconds()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${hh}:${mi}:${ss}`;
}

function formatDateOnly(value: any) {
    const text = String(value || "").trim();
    if (!text) return "-";
    const parsed = new Date(text);
    if (Number.isNaN(parsed.getTime())) {
        return text.length >= 10 ? text.slice(0, 10) : text;
    }
    const yyyy = parsed.getFullYear();
    const mm = String(parsed.getMonth() + 1).padStart(2, "0");
    const dd = String(parsed.getDate()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd}`;
}

function resolveUndervalueScore(row: Record<string, any>) {
    const directValuationScore = Number(row?.valuation_score);
    if (Number.isFinite(directValuationScore)) {
        return directValuationScore;
    }
    const directUnderScore = Number(row?.undervalue_score);
    if (Number.isFinite(directUnderScore)) {
        return directUnderScore;
    }
    return null;
}

function sortByUndervalue(order: "asc" | "desc") {
    const direction = order === "asc" ? 1 : -1;
    pickingResult.value = [...pickingResult.value].sort((a, b) => {
        const scoreA = resolveUndervalueScore(a);
        const scoreB = resolveUndervalueScore(b);
        if (scoreA === null && scoreB === null) return String(a?.ts_code || "").localeCompare(String(b?.ts_code || ""));
        if (scoreA === null) return 1;
        if (scoreB === null) return -1;
        if (scoreA === scoreB) return String(a?.ts_code || "").localeCompare(String(b?.ts_code || ""));
        return (scoreA - scoreB) * direction;
    });
}

const valuationMethodLabelMap: Record<string, string> = {
    recommended: "行业推荐",
    market_style: "市场风格",
    scarcity_overlay: "稀缺性",
    pe: "PE",
    pb: "PB",
    ps: "PS",
    peg: "PEG",
    fcff_dcf: "FCFF",
    ddm: "DDM",
    market_cap: "市值法",
};

function methodLabel(method: any) {
    const key = String(method || "").trim().toLowerCase();
    return valuationMethodLabelMap[key] || String(method || "-");
}

function getUndervalueScoreColor(value: any) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "#909399";
    if (numeric >= 75) return "#cf1322";
    if (numeric >= 55) return "#d46b08";
    return "#606266";
}

function getSignalScoreColor(value: any) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "#909399";
    if (numeric >= 70) return "#cf1322";
    if (numeric >= 55) return "#d46b08";
    return "#606266";
}

function normalizeAction(action: any) {
    return String(action || "").trim().toUpperCase();
}

function actionTagType(action: any) {
    const normalized = normalizeAction(action);
    if (normalized === "BUY" || normalized === "B") return "danger";
    if (normalized === "SELL_PART") return "warning";
    if (normalized === "SELL" || normalized === "S") return "success";
    if (normalized === "HOLD" || normalized === "H") return "info";
    return "";
}

function actionLabel(action: any) {
    const normalized = normalizeAction(action);
    if (normalized === "BUY" || normalized === "B") return "买";
    if (normalized === "SELL" || normalized === "SELL_PART" || normalized === "S") return "卖";
    if (normalized === "HOLD" || normalized === "H") return "持";
    return "-";
}

function normalizeRisk(risk: any) {
    return String(risk || "").trim().toUpperCase();
}

function riskTagType(risk: any) {
    const normalized = normalizeRisk(risk);
    if (normalized === "LOW" || normalized === "L") return "danger";
    if (normalized === "MEDIUM" || normalized === "M") return "warning";
    if (normalized === "HIGH" || normalized === "H") return "success";
    return "";
}

function traditionalRiskTagType(risk: any) {
    const normalized = normalizeRisk(risk);
    if (normalized === "LOW" || normalized === "L") return "success";
    if (normalized === "MEDIUM" || normalized === "M") return "warning";
    if (normalized === "HIGH" || normalized === "H") return "danger";
    return "";
}

function riskLabel(risk: any) {
    const normalized = normalizeRisk(risk);
    if (normalized === "LOW" || normalized === "L") return "低";
    if (normalized === "MEDIUM" || normalized === "M") return "中";
    if (normalized === "HIGH" || normalized === "H") return "高";
    return "-";
}

async function fetchPickingResult() {
    try {
        if (valuationStockPickingStore.scopeParam === "SCOPE:NONE") {
            pickingResult.value = [];
            valuationStockPickingStore.setPickingResults([]);
            return;
        }

        const isFirstPageRequest = fromIndex.value === 0;
        const valuationMethodVal = valuationStockPickingStore.valuationMethod.split(":")[1].toLowerCase();
        const valuationStatusVal = valuationStockPickingStore.valuationStatus.split(":")[1] !== "NONE" ? valuationStockPickingStore.valuationStatus.split(":")[1].toLowerCase() : "";
        const buyCandidateOnlyVal = valuationStockPickingStore.buyCandidateOnly.split(":")[1] === "ONLY" ? "1" : "";
        const valuationPickStrategyVal = valuationStockPickingStore.valuationPickStrategy.split(":")[1].toLowerCase();
        const minNetprofitYoyVal = String(valuationStockPickingStore.minNetprofitYoy || "").trim();
        const minEbitYoyVal = String(valuationStockPickingStore.minEbitYoy || "").trim();
        const requirePositivePrevNetprofitVal = valuationStockPickingStore.requirePositivePrevNetprofit ? "1" : "0";
        const requirePositivePrevEbitVal = valuationStockPickingStore.requirePositivePrevEbit ? "1" : "0";
        const applyFinancialFiltersVal = valuationStockPickingStore.applyFinancialFilters ? "1" : "0";
        const priorityPolicyVal = String(valuationStockPickingStore.priorityPolicy || "score_desc").trim().toLowerCase();
        const pickingModeVal = valuationStockPickingStore.pickingMode.split(":")[1].toLowerCase();
        const earningsReportTypeVal = valuationStockPickingStore.earningsReportType.split(":")[1];
        const signalActionVal = valuationStockPickingStore.signalAction.split(":")[1];
        const riskLevelParam = String(valuationStockPickingStore.riskLevel || "")
            .split(",")
            .map((item) => item.trim().toUpperCase())
            .filter((item) => item === "LOW" || item === "MEDIUM" || item === "HIGH")
            .join(",");
        const featureDataSourceVal = valuationStockPickingStore.featureDataSource.split(":")[1];
        const sharedMinScoreVal = String(valuationStockPickingStore.minSignalScore || "").trim();

        const search = new URLSearchParams();
        search.set("freq", valuationStockPickingStore.freq);
        search.set("from_index", String(fromIndex.value));
        search.set("to_index", String(toIndex.value));
        search.set("quick_preview", "1");
        search.set("preview_scan_limit", QUICK_PREVIEW_SCAN_LIMIT);
        search.set("picking_mode", pickingModeVal);
        search.set("valuation_method", valuationMethodVal);
        if (valuationStatusVal) search.set("valuation_status", valuationStatusVal);
        search.set("valuation_band_pct", valuationStockPickingStore.valuationBandPct);
        search.set("valuation_pick_strategy", valuationPickStrategyVal);
        if (minNetprofitYoyVal) search.set("min_netprofit_yoy", minNetprofitYoyVal);
        if (minEbitYoyVal) search.set("min_ebit_yoy", minEbitYoyVal);
        search.set("apply_financial_filters", applyFinancialFiltersVal);
        search.set("require_positive_prev_netprofit", requirePositivePrevNetprofitVal);
        search.set("require_positive_prev_ebit", requirePositivePrevEbitVal);
        if (priorityPolicyVal) search.set("priority_policy", priorityPolicyVal);
        if (buyCandidateOnlyVal) search.set("buy_candidate_only", buyCandidateOnlyVal);
        if (valuationStockPickingStore.swIndustry) search.set("sw_industry", valuationStockPickingStore.swIndustry);
        search.set("earnings_report_type", earningsReportTypeVal);
        if (riskLevelParam) search.set("risk_level", riskLevelParam);
        if (pickingModeVal === "predictive") {
            if (signalActionVal !== "ALL") search.set("signal_action", signalActionVal);
            if (sharedMinScoreVal) search.set("min_signal_score", sharedMinScoreVal);
            if (valuationStockPickingStore.minTargetReturnPct) search.set("min_target_return_pct", valuationStockPickingStore.minTargetReturnPct);
            if (featureDataSourceVal !== "ALL") search.set("feature_data_source", featureDataSourceVal);
        } else {
            if (sharedMinScoreVal) search.set("min_valuation_score", sharedMinScoreVal);
        }

        const scopePath = normalizeScopeForApi(valuationStockPickingStore.scopeParam);
        const url = `${buildApiUrl(`/stock-pick-valuation/${valuationStockPickingStore.tradeDate}/${scopePath}/`)}?${search.toString()}`;
        const requestFrom = fromIndex.value;
        const requestTo = toIndex.value;
        const res = await axios.get(url);

        if (res.data) {
            pickingResult.value = res.data.data || [];
            const responseMeta = (res.data || {}).meta || {};
            const responseValuationFilter = (res.data || {}).valuation_filter || {};
            effectiveFinancialFilters.value = responseValuationFilter.effective_financial_filters || {};
            totalFiltered.value = Number(responseMeta.total_filtered || 0);
            if (isFirstPageRequest) {
                valuationStockPickingStore.markResultDate(
                    valuationStockPickingStore.tradeDate,
                    totalFiltered.value > 0,
                );
            }
            if (pickingResult.value.length > 0) {
                currentRangeStart.value = requestFrom + 1;
                currentRangeEnd.value = requestFrom + pickingResult.value.length;
            } else {
                currentRangeStart.value = 0;
                currentRangeEnd.value = 0;
            }
            const selectedStrategy = valuationStockPickingStore.valuationPickStrategy.split(":")[1]?.toLowerCase?.() || "baseline";
            if (
                isFirstPageRequest
                && selectedStrategy !== "baseline"
                && Number(responseMeta.strategy_effective_stocks || 0) === 0
            ) {
                ElMessage.info("当前样本里每只股票仅有单候选估值，切换主值策略不会改变估值价格。");
            }
            const noResult = !Array.isArray(res.data.data) || res.data.data.length === 0;
            if (isFirstPageRequest && noResult && responseMeta.requested_trade_date_has_data === false) {
                const latestDate = responseMeta.latest_trade_date_for_freq;
                ElMessage.warning(
                    latestDate
                        ? `当前选择日期 ${valuationStockPickingStore.tradeDate} 无交易数据，最新可用交易日为 ${latestDate}`
                        : `当前选择日期 ${valuationStockPickingStore.tradeDate} 无交易数据，请切换交易日后重试`
                );
            }

            curFromIndex.value = requestFrom;
            curToIndex.value = requestTo;
            fromIndex.value = requestTo;
            toIndex.value = requestTo + increment.value;

            valuationStockPickingStore.setPickingResults(
                (res.data.data || []).map((item: any) => ({
                    ts_code: item.ts_code,
                    name: item.name,
                    close_qfq: item.close_qfq,
                    pct_change_qfq: item.pct_change_qfq,
                }))
            );
        }
    } catch (error) {
        ElMessage.error("获取估值选股结果失败，请稍后重试");
    }
}

async function warmupPickingCache() {
    try {
        if (valuationStockPickingStore.scopeParam === "SCOPE:NONE") {
            return;
        }
        const valuationMethodVal = valuationStockPickingStore.valuationMethod.split(":")[1].toLowerCase();
        const valuationStatusVal = valuationStockPickingStore.valuationStatus.split(":")[1] !== "NONE" ? valuationStockPickingStore.valuationStatus.split(":")[1].toLowerCase() : "";
        const valuationPickStrategyVal = valuationStockPickingStore.valuationPickStrategy.split(":")[1].toLowerCase();
        const pickingModeVal = valuationStockPickingStore.pickingMode.split(":")[1].toLowerCase();

        const search = new URLSearchParams();
        search.set("freq", valuationStockPickingStore.freq);
        search.set("from_index", "0");
        search.set("to_index", "1");
        search.set("quick_preview", "1");
        search.set("preview_scan_limit", QUICK_PREVIEW_SCAN_LIMIT);
        search.set("picking_mode", pickingModeVal);
        search.set("valuation_method", valuationMethodVal);
        if (valuationStatusVal) search.set("valuation_status", valuationStatusVal);
        search.set("valuation_band_pct", valuationStockPickingStore.valuationBandPct);
        search.set("valuation_pick_strategy", valuationPickStrategyVal);

        const scopePath = normalizeScopeForApi(valuationStockPickingStore.scopeParam);
        const url = `${buildApiUrl(`/stock-pick-valuation/${valuationStockPickingStore.tradeDate}/${scopePath}/`)}?${search.toString()}`;
        await axios.get(url);
    } catch (_error) {
        // Warmup is best-effort and should not affect user interaction.
    }
}

async function fetchPrevPage() {
    if (curFromIndex.value <= 0) return;
    fromIndex.value = curFromIndex.value - increment.value;
    toIndex.value = curToIndex.value - increment.value;
    await fetchPickingResult();
}

async function fetchNextPage() {
    await fetchPickingResult();
}

watch(
    [
        () => valuationStockPickingStore.tradeDate,
        () => valuationStockPickingStore.scopeParam,
        () => valuationStockPickingStore.freq,
        () => valuationStockPickingStore.pickingMode,
        () => valuationStockPickingStore.valuationMethod,
        () => valuationStockPickingStore.valuationStatus,
        () => valuationStockPickingStore.valuationBandPct,
        () => valuationStockPickingStore.valuationPickStrategy,
        () => valuationStockPickingStore.minNetprofitYoy,
        () => valuationStockPickingStore.minEbitYoy,
        () => valuationStockPickingStore.requirePositivePrevNetprofit,
        () => valuationStockPickingStore.requirePositivePrevEbit,
        () => valuationStockPickingStore.priorityPolicy,
        () => valuationStockPickingStore.buyCandidateOnly,
        () => valuationStockPickingStore.swIndustry,
        () => valuationStockPickingStore.earningsReportType,
        () => valuationStockPickingStore.signalAction,
        () => valuationStockPickingStore.riskLevel,
        () => valuationStockPickingStore.minSignalScore,
        () => valuationStockPickingStore.minTargetReturnPct,
        () => valuationStockPickingStore.featureDataSource,
        () => valuationStockPickingStore.fiscalYear,
    ],
    () => {
        fromIndex.value = 0;
        toIndex.value = 25;
        currentRangeStart.value = 0;
        currentRangeEnd.value = 0;
        fetchPickingResult();
    },
    { immediate: true }
);

onMounted(() => {
    stockChartFilterStore.setTopBottomSwitch(false);
    loadWeeklyDownloadLinks();
    warmupPickingCache();
});
</script>

<style scoped>
.stock-title-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
}

.stock-title-left {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    min-width: 0;
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

.compact-toggle-tag.is-checked.compact-toggle-observe {
    background: #ecfdf3;
    border-color: #34d399;
    color: #047857;
}

.compact-observe-label {
    display: inline-flex;
    align-items: center;
    gap: 4px;
}

.compact-toggle-label {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.2px;
}
</style>
