<template>
  <el-card :class="{ 'embedded-valuation-card': embedded }" :shadow="embedded ? 'never' : 'always'"
    :body-style="embedded ? { padding: '0' } : undefined" :style="embedded ? 'border: none;' : ''">
    <el-skeleton :loading="loading" animated :rows="4">
      <template #default>
        <el-alert v-if="activeCorporateActionImpact" type="warning" :closable="false" show-icon
          style="margin-bottom: 8px;">
          <template #title>
            检测到除权摊薄影响: 股本变化 {{ formatGap(activeCorporateActionImpact.share_change_ratio_pct) }}%
          </template>
          <template #default>
            <div style="font-size: 12px; line-height: 1.6; color: #7c2d12;">
              {{ activeCorporateActionImpact.message || '估值回落可能由股本扩张驱动，建议结合归一化口径观察。' }}
            </div>
            <div style="font-size: 12px; color: #92400e;">
              {{ corporateActionMeta }}
            </div>
          </template>
        </el-alert>
        <div style="font-size: 12px; color: #606266; margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
          <span>财报季:</span>
          <el-radio-group v-model="selectedEarningsReportType" size="small" @change="onUserReportTypeChange">
            <el-radio-button label="Q1">Q1</el-radio-button>
            <el-radio-button label="H1">H1</el-radio-button>
            <el-radio-button label="Q3">Q3</el-radio-button>
            <el-radio-button label="FY">FY</el-radio-button>
            <el-radio-button label="快">快报</el-radio-button>
            <el-radio-button label="FUSION">Fusion</el-radio-button>
          </el-radio-group>
        </div>
        <div class="section-toggle" @click="valuationSectionExpanded = !valuationSectionExpanded">
          <span>估值摘要</span>
          <span>{{ valuationSectionExpanded ? '收起' : '展开' }}</span>
        </div>
        <div v-show="valuationSectionExpanded" class="valuation-block valuation-block-traditional">
          <el-card class="holding-summary-card" shadow="never">
            <template #header>
              <div class="holding-summary-card-header">
                <span class="holding-summary-card-title">持仓建议</span>
                <div class="holding-summary-card-badges">
                  <el-tag size="small" effect="light" type="danger">{{ traditionalTieredTemplate?.style_label || '均衡'
                    }}</el-tag>
                  <el-tag size="small" effect="light" type="info">{{
                    traditionalTieredTemplate?.volatility_profile?.volatility_label ||
                    traditionalTieredTemplate?.position_guidance?.volatility_label || '中波动' }}</el-tag>
                  <el-tag size="small" effect="light" type="warning">仓位 {{
                    traditionalTieredTemplate?.position_guidance?.suggested_position_range || '-' }}</el-tag>
                </div>
              </div>
            </template>
            <div class="holding-summary-card-body">
              <div class="holding-summary-card-text">{{ holdingSummaryText }}</div>
              <div class="holding-trigger-board">
                <div class="holding-trigger-switch">
                  <span class="holding-trigger-switch-label">叠加到K线</span>
                  <el-switch v-model="klineTriggerOverlayEnabled" size="small" />
                </div>
                <div class="holding-trigger-line">
                  <span class="holding-trigger-label">升仓触发</span>
                  <span class="holding-trigger-value">{{ traditionalPositionTriggerHints.upgradeHint }}</span>
                </div>
                <div class="holding-trigger-line">
                  <span class="holding-trigger-label">降仓触发</span>
                  <span class="holding-trigger-value">{{ traditionalPositionTriggerHints.downgradeHint }}</span>
                </div>
              </div>
              <div class="holding-summary-card-footer">
                <span>传统底线 {{ traditionalTieredTemplate?.position_guidance?.suggested_position_range || '-' }}</span>
                <span>预测节奏 {{ predictiveTieredTemplate?.positionRange || '-' }}</span>
              </div>
            </div>
          </el-card>
          <div class="valuation-block-header">
            <span class="valuation-block-title">传统估值</span>
            <span class="valuation-block-subtitle">基于传统方法口径</span>
          </div>
          <el-tabs v-model="traditionalValuationTab" style="margin-bottom: 6px;">
            <el-tab-pane label="传统快照" name="snapshot" />
            <el-tab-pane label="三档估值+仓位" name="tiered" />
          </el-tabs>
          <div v-if="traditionalValuationTab === 'snapshot'">
            <div style="color: #606266; margin-bottom: 6px;">
              <span>传统信号:</span>
              <el-tag size="small" effect="light" style="margin-left: 6px;"
                :type="earningsActionTagType(summary.buy_candidate ? 'BUY' : 'SELL')">{{
                  earningsActionLabel(summary.buy_candidate ? 'BUY' : 'SELL') }}</el-tag>
              <span style="margin-left: 6px;">低估分 {{ formatScore(summary.undervalue_score) }}</span>
              <span style="margin-left: 6px;">风险分 {{ formatScore(valuationRisk?.risk_score) }}</span>
              <el-tag size="small" effect="light" style="margin-left: 6px;"
                :type="valuationRiskTagType(valuationRisk?.risk_level)">{{ riskLevelLabel(valuationRisk?.risk_level)
                }}</el-tag>
            </div>
            <el-alert v-if="traditionalFiscalStaleHint" type="warning" :closable="false" show-icon
              style="margin-bottom: 8px;">
              <template #title>{{ traditionalFiscalStaleHint }}</template>
            </el-alert>
            <div style="color: #606266; margin-bottom: 6px;">
              <span>估值财报:</span>
              <span style="margin-left: 6px;">{{ valuationReportMeta }}</span>
            </div>
            <div v-if="traditionalOptimizationMetaText" style="margin-bottom: 6px; color: #409eff;">
              <span>传统优化:</span>
              <span style="margin-left: 6px;">{{ traditionalOptimizationMetaText }}</span>
            </div>
            <el-row :gutter="10">
              <el-col :span="12">
                <div class="valuation-side-card valuation-side-card-primary">
                  <div>
                    <span>组合估值价:</span>
                    <span style="margin-left: 6px; font-weight: 600;">{{ formatPrice(summary.composite_valuation_price)
                      }}</span>
                    <span style="margin-left: 4px; color: #93c5fd; font-weight: 600;">/ {{
                      formatPrice(summaryOptimized.composite_valuation_price_optimized ??
                      summary.composite_valuation_price)
                      }}</span>
                    <span style="margin-left: 4px; color: #f59e0b; font-weight: 600;">/ {{
                      formatPrice(applyMarketOverallAdjustedPrice(summary.composite_valuation_price,
                      marketOverallMultiplierForDisplay)) }}</span>
                  </div>
                  <div style="margin-top: 4px;">
                    <span>偏离:</span>
                    <span style="margin-left: 6px;">{{ formatGap(summary.composite_valuation_gap_pct) }}%</span>
                    <span style="margin-left: 8px; color: #8c8c8c;">锚{{
                      formatAnchorDateSuffix(summary.anchor_trade_date) }}
                      <span :style="{ color: anchorSnapshotTrendColor(resolveAnchorSnapshotReturnPct(summary)) }">{{
                        anchorSnapshotTrendSymbol(resolveAnchorSnapshotReturnPct(summary)) }}</span> {{
                          formatGap(resolveAnchorSnapshotReturnPct(summary)) }}%</span>
                    <el-tag size="small" effect="light" style="margin-left: 8px;"
                      :type="statusTagType(summary.composite_valuation_status)">{{
                        statusLabel(summary.composite_valuation_status) }}</el-tag>
                  </div>
                  <div style="margin-top: 4px;">
                    <span>统一股本口径(当前):</span>
                    <span style="margin-left: 6px; font-weight: 600;">{{
                      formatPrice(summaryNormalized.composite_valuation_price) }}</span>
                    <span style="margin-left: 4px; color: #93c5fd; font-weight: 600;">/ {{
                      formatPrice(summaryNormalizedOptimized.composite_valuation_price_optimized ??
                      summaryNormalized.composite_valuation_price) }}</span>
                  </div>
                  <div style="margin-top: 4px;">
                    <span>归一化偏离:</span>
                    <span style="margin-left: 6px;">{{ formatGap(summaryNormalized.composite_valuation_gap_pct)
                      }}%</span>
                    <span style="margin-left: 8px; color: #8c8c8c;">锚{{
                      formatAnchorDateSuffix(summaryNormalized.anchor_trade_date) }} <span
                        :style="{ color: anchorSnapshotTrendColor(resolveAnchorSnapshotReturnPct(summaryNormalized)) }">{{
                          anchorSnapshotTrendSymbol(resolveAnchorSnapshotReturnPct(summaryNormalized)) }}</span> {{
                          formatGap(resolveAnchorSnapshotReturnPct(summaryNormalized)) }}%</span>
                    <el-tag size="small" effect="light" style="margin-left: 8px;"
                      :type="statusTagType(summaryNormalized.composite_valuation_status)">{{
                        statusLabel(summaryNormalized.composite_valuation_status) }}</el-tag>
                  </div>
                </div>
              </el-col>
              <el-col :span="12">
                <div class="valuation-side-card valuation-side-card-secondary">
                  <div>
                    <span>保守估值价:</span>
                    <span style="margin-left: 6px; font-weight: 600;">{{
                      formatPrice(summary.conservative_valuation_price)
                      }}</span>
                    <span style="margin-left: 4px; color: #93c5fd; font-weight: 600;">/ {{
                      formatPrice(summaryOptimized.conservative_valuation_price_optimized ??
                      summary.conservative_valuation_price) }}</span>
                    <span style="margin-left: 4px; color: #f59e0b; font-weight: 600;">/ {{
                      formatPrice(applyMarketOverallAdjustedPrice(summary.conservative_valuation_price,
                      marketOverallMultiplierForDisplay)) }}</span>
                  </div>
                  <div style="margin-top: 4px;">
                    <span>偏离:</span>
                    <span style="margin-left: 6px;">{{ formatGap(summary.conservative_valuation_gap_pct) }}%</span>
                    <span style="margin-left: 8px; color: #8c8c8c;">锚{{
                      formatAnchorDateSuffix(summary.anchor_trade_date) }}
                      <span :style="{ color: anchorSnapshotTrendColor(resolveAnchorSnapshotReturnPct(summary)) }">{{
                        anchorSnapshotTrendSymbol(resolveAnchorSnapshotReturnPct(summary)) }}</span> {{
                          formatGap(resolveAnchorSnapshotReturnPct(summary)) }}%</span>
                    <el-tag size="small" effect="light" style="margin-left: 8px;"
                      :type="statusTagType(summary.conservative_valuation_status)">{{
                        statusLabel(summary.conservative_valuation_status) }}</el-tag>
                  </div>
                  <div style="margin-top: 4px;">
                    <span>统一股本口径(当前):</span>
                    <span style="margin-left: 6px; font-weight: 600;">{{
                      formatPrice(summaryNormalized.conservative_valuation_price) }}</span>
                    <span style="margin-left: 4px; color: #93c5fd; font-weight: 600;">/ {{
                      formatPrice(summaryNormalizedOptimized.conservative_valuation_price_optimized ??
                      summaryNormalized.conservative_valuation_price) }}</span>
                  </div>
                  <div style="margin-top: 4px;">
                    <span>归一化偏离:</span>
                    <span style="margin-left: 6px;">{{ formatGap(summaryNormalized.conservative_valuation_gap_pct)
                      }}%</span>
                    <span style="margin-left: 8px; color: #8c8c8c;">锚{{
                      formatAnchorDateSuffix(summaryNormalized.anchor_trade_date) }} <span
                        :style="{ color: anchorSnapshotTrendColor(resolveAnchorSnapshotReturnPct(summaryNormalized)) }">{{
                          anchorSnapshotTrendSymbol(resolveAnchorSnapshotReturnPct(summaryNormalized)) }}</span> {{
                          formatGap(resolveAnchorSnapshotReturnPct(summaryNormalized)) }}%</span>
                    <el-tag size="small" effect="light" style="margin-left: 8px;"
                      :type="statusTagType(summaryNormalized.conservative_valuation_status)">{{
                        statusLabel(summaryNormalized.conservative_valuation_status) }}</el-tag>
                  </div>
                </div>
              </el-col>
            </el-row>
            <div
              v-if="summary.market_style_valuation_price !== null || summaryNormalized.market_style_valuation_price !== null"
              style="margin-top: 6px; padding-top: 6px; border-top: 1px dashed #e5e7eb; color: #606266;">
              <span>市场风格价:</span>
              <span style="margin-left: 6px; font-weight: 600;">{{ formatPrice(summary.market_style_valuation_price)
                }}</span>
              <span style="margin-left: 4px; color: #93c5fd; font-weight: 600;">/ {{
                formatPrice(summaryOptimized.market_style_valuation_price_optimized ??
                  summary.market_style_valuation_price)
                }}</span>
              <span style="margin-left: 8px;">{{ formatGap(summary.market_style_valuation_gap_pct) }}%</span>
              <el-tag size="small" effect="light" style="margin-left: 8px;"
                :type="statusTagType(summary.market_style_valuation_status)">
                {{ statusLabel(summary.market_style_valuation_status) }}
              </el-tag>
              <div style="margin-top: 4px; color: #606266;">
                <span>统一股本口径(当前):</span>
                <span style="margin-left: 6px; font-weight: 600;">{{
                  formatPrice(summaryNormalized.market_style_valuation_price)
                  }}</span>
                <span style="margin-left: 4px; color: #93c5fd; font-weight: 600;">/ {{
                  formatPrice(summaryNormalizedOptimized.market_style_valuation_price_optimized ??
                    summaryNormalized.market_style_valuation_price) }}</span>
                <span style="margin-left: 8px;">{{ formatGap(summaryNormalized.market_style_valuation_gap_pct)
                  }}%</span>
                <el-tag size="small" effect="light" style="margin-left: 8px;"
                  :type="statusTagType(summaryNormalized.market_style_valuation_status)">
                  {{ statusLabel(summaryNormalized.market_style_valuation_status) }}
                </el-tag>
              </div>
            </div>
          </div>
          <div v-else>
            <div style="color: #606266; margin-bottom: 6px;">{{ holdingSummaryText }}</div>
            <el-alert v-if="traditionalTieredTemplate && traditionalTieredTemplate.style_reasons?.length" type="info"
              :closable="false" show-icon style="margin-bottom: 8px;">
              <template #title>
                风格识别: {{ traditionalTieredTemplate.style_label }}
                <span style="margin-left: 6px; color: #64748b;">score {{
                  formatGap(traditionalTieredTemplate.style_score) }}</span>
              </template>
              <template #default>
                <div style="font-size: 12px; color: #64748b;">
                  行业 {{ traditionalTieredTemplate.industry_name || '-' }} | 依据 {{
                    traditionalTieredTemplate.style_reasons.join(' / ') }}
                </div>
              </template>
            </el-alert>
            <el-row :gutter="10">
              <el-col :span="8">
                <div class="valuation-side-card valuation-side-card-secondary">
                  <div><strong>{{ traditionalTieredTemplate?.tiers?.conservative?.label || '风控优先' }}</strong></div>
                  <div style="margin-top: 4px;">目标价 {{
                    formatPrice(traditionalTieredTemplate?.tiers?.conservative?.target_price)
                    }}</div>
                  <div style="margin-top: 4px;">预期收益 {{
                    formatGap(traditionalTieredTemplate?.tiers?.conservative?.expected_return_pct) }}%</div>
                  <div style="margin-top: 4px;">区间 {{
                    formatPrice(traditionalTieredTemplate?.tiers?.conservative?.range?.lower)
                    }} - {{ formatPrice(traditionalTieredTemplate?.tiers?.conservative?.range?.upper) }}</div>
                  <div style="margin-top: 4px; color: #64748b;">覆盖 {{
                    tierCoverageText(traditionalTieredTemplate?.tiers?.conservative?.coverage_ratio) }}</div>
                </div>
              </el-col>
              <el-col :span="8">
                <div class="valuation-side-card valuation-side-card-primary">
                  <div><strong>{{ traditionalTieredTemplate?.tiers?.balanced?.label || '平衡' }}</strong></div>
                  <div style="margin-top: 4px;">目标价 {{
                    formatPrice(traditionalTieredTemplate?.tiers?.balanced?.target_price) }}
                  </div>
                  <div style="margin-top: 4px;">预期收益 {{
                    formatGap(traditionalTieredTemplate?.tiers?.balanced?.expected_return_pct) }}%</div>
                  <div style="margin-top: 4px;">区间 {{
                    formatPrice(traditionalTieredTemplate?.tiers?.balanced?.range?.lower) }} -
                    {{ formatPrice(traditionalTieredTemplate?.tiers?.balanced?.range?.upper) }}</div>
                  <div style="margin-top: 4px; color: #64748b;">覆盖 {{
                    tierCoverageText(traditionalTieredTemplate?.tiers?.balanced?.coverage_ratio) }}</div>
                </div>
              </el-col>
              <el-col :span="8">
                <div class="valuation-side-card valuation-side-card-secondary">
                  <div><strong>{{ traditionalTieredTemplate?.tiers?.aggressive?.label || '成长进攻' }}</strong></div>
                  <div style="margin-top: 4px;">目标价 {{
                    formatPrice(traditionalTieredTemplate?.tiers?.aggressive?.target_price)
                    }}</div>
                  <div style="margin-top: 4px;">预期收益 {{
                    formatGap(traditionalTieredTemplate?.tiers?.aggressive?.expected_return_pct) }}%</div>
                  <div style="margin-top: 4px;">区间 {{
                    formatPrice(traditionalTieredTemplate?.tiers?.aggressive?.range?.lower) }}
                    - {{ formatPrice(traditionalTieredTemplate?.tiers?.aggressive?.range?.upper) }}</div>
                  <div style="margin-top: 4px; color: #64748b;">覆盖 {{
                    tierCoverageText(traditionalTieredTemplate?.tiers?.aggressive?.coverage_ratio) }}</div>
                </div>
              </el-col>
            </el-row>
            <div style="margin-top: 8px; color: #334155; font-size: 12px;">
              仓位建议 {{ traditionalTieredTemplate?.position_guidance?.suggested_position_range || '-' }}
              <span style="margin-left: 8px; color: #64748b;">{{ traditionalTieredTemplate?.position_guidance?.message
                || ''
                }}</span>
            </div>
            <div v-if="traditionalBlendHintText"
              style="margin-top: 4px; color: #94a3b8; font-size: 11px; line-height: 1.4;">
              {{ traditionalBlendHintText }}
            </div>
            <div style="margin-top: 6px; color: #64748b; font-size: 12px;">
              权重预览: 保守 {{ tierWeightPreview(traditionalTieredTemplate?.tiers?.conservative?.weights) }}
            </div>
            <div style="margin-top: 4px; color: #64748b; font-size: 12px;">
              权重预览: 平衡 {{ tierWeightPreview(traditionalTieredTemplate?.tiers?.balanced?.weights) }}
            </div>
            <div style="margin-top: 4px; color: #64748b; font-size: 12px;">
              权重预览: 进攻 {{ tierWeightPreview(traditionalTieredTemplate?.tiers?.aggressive?.weights) }}
            </div>
          </div>
        </div>

        <div v-show="valuationSectionExpanded" class="valuation-block valuation-block-predictive">
          <div class="valuation-block-header">
            <span class="valuation-block-title">预测估值</span>
            <div style="display: flex; align-items: center; gap: 8px;">
              <span class="valuation-block-subtitle">基于 earnings signal 口径</span>
              <span style="font-size: 11px; color: #64748b;">{{ predictiveContextLabel }}</span>
              <span v-if="predictiveLoading" style="font-size: 11px; color: #64748b;">刷新中...</span>
              <span v-else style="font-size: 11px; color: #94a3b8;">{{ predictiveRefreshMeta }}</span>
              <el-select v-model="selectedPredictModelSlot" size="small" style="width: 132px;"
                :disabled="predictiveLoading">
                <el-option label="生产模型(默认)" value="production" />
                <el-option label="候选模型" value="candidate" />
              </el-select>
              <el-button size="small" text :disabled="predictiveLoading || !stockTradeStore.tsCode"
                @click="fetchPredictiveSignalOnly()">
                刷新
              </el-button>
            </div>
          </div>
          <div style="color: #606266; margin-bottom: 6px;">
            <span>预测信号:</span>
            <el-tag size="small" effect="light" style="margin-left: 6px;"
              :type="earningsActionTagType(earningsSignal?.action)">{{ earningsActionLabel(earningsSignal?.action)
              }}</el-tag>
            <span style="margin-left: 6px;">分数 {{ formatScore(earningsSignal?.signal_score) }}</span>
            <el-tag size="small" effect="light" style="margin-left: 6px;"
              :type="earningsRiskTagType(earningsSignal?.risk_level)">{{ riskLevelLabel(earningsSignal?.risk_level)
              }}</el-tag>
          </div>
          <el-tabs v-model="predictiveValuationTab" style="margin-bottom: 6px;">
            <el-tab-pane label="预测快照" name="snapshot" />
            <el-tab-pane label="三档估值+仓位" name="tiered" />
          </el-tabs>
          <div v-if="predictiveValuationTab === 'snapshot'">
            <div style="margin-bottom: 6px; color: #334155;">{{ earningsSignalQuantMeta }}</div>
            <div style="margin-bottom: 6px; color: #606266;">{{ earningsSignalMeta }}</div>
            <el-row :gutter="10" style="margin-bottom: 6px;">
              <el-col :span="12">
                <div class="valuation-side-card valuation-side-card-primary">
                  <div style="display: flex; align-items: center; justify-content: space-between;">
                    <strong>最新预测估值</strong>
                    <el-tag size="small" effect="light" :type="earningsActionTagType(predictiveLatestView?.action)">{{
                      earningsActionLabel(predictiveLatestView?.action) }}</el-tag>
                  </div>
                  <div style="margin-top: 6px; color: #334155;">
                    <span style="font-size: 12px;">分数优先</span>
                    <span style="margin-left: 6px; font-size: 20px; font-weight: 700;">{{
                      formatScore(predictiveLatestView?.signal_score) }}</span>
                    <el-tag size="small" effect="light" style="margin-left: 6px;"
                      :type="earningsRiskTagType(predictiveLatestView?.risk_level)">{{
                        riskLevelLabel(predictiveLatestView?.risk_level) }}</el-tag>
                  </div>
                  <div style="margin-top: 6px;">目标价 {{
                    formatPrice(resolvePredictiveCoreTargetPrice(predictiveLatestView)) }}
                  </div>
                  <div style="margin-top: 4px;">区间 {{ formatPrice(resolvePredictiveCoreTargetLow(predictiveLatestView))
                    }} - {{
                      formatPrice(resolvePredictiveCoreTargetHigh(predictiveLatestView)) }}</div>
                  <div style="margin-top: 4px;">预期收益 {{ formatGap(resolvePredictiveCoreReturnPct(predictiveLatestView))
                    }}%
                  </div>
                  <div style="margin-top: 4px; color: #64748b; font-size: 12px;">
                    锚点{{ formatAnchorDateSuffix(predictiveLatestView?.anchor_trade_date ??
                    predictiveLatestView?.asof_date) }}
                    <span style="margin-left: 6px;">公告 {{ formatDateOnly(predictiveLatestView?.financial_ann_date) ||
                      '-'
                      }}</span>
                  </div>
                </div>
              </el-col>
              <el-col :span="12">
                <div class="valuation-side-card valuation-side-card-secondary">
                  <div style="display: flex; align-items: center; justify-content: space-between;">
                    <strong>{{ selectedEarningsReportType }} 发布时点估值</strong>
                    <el-tag size="small" effect="light"
                      :type="earningsActionTagType(predictiveReportAnchorView?.action)">{{
                        earningsActionLabel(predictiveReportAnchorView?.action) }}</el-tag>
                  </div>
                  <div style="margin-top: 6px; color: #334155;">
                    <span style="font-size: 12px;">分数优先</span>
                    <span style="margin-left: 6px; font-size: 20px; font-weight: 700;">{{
                      formatScore(predictiveReportAnchorView?.signal_score) }}</span>
                    <el-tag size="small" effect="light" style="margin-left: 6px;"
                      :type="earningsRiskTagType(predictiveReportAnchorView?.risk_level)">{{
                        riskLevelLabel(predictiveReportAnchorView?.risk_level) }}</el-tag>
                  </div>
                  <div style="margin-top: 6px;">目标价 {{
                    formatPrice(resolvePredictiveCoreTargetPrice(predictiveReportAnchorView))
                    }}</div>
                  <div style="margin-top: 4px;">区间 {{
                    formatPrice(resolvePredictiveCoreTargetLow(predictiveReportAnchorView)) }}
                    - {{ formatPrice(resolvePredictiveCoreTargetHigh(predictiveReportAnchorView)) }}</div>
                  <div style="margin-top: 4px;">预期收益 {{
                    formatGap(resolvePredictiveCoreReturnPct(predictiveReportAnchorView))
                    }}%</div>
                  <div style="margin-top: 4px; color: #64748b; font-size: 12px;">
                    锚点{{ formatAnchorDateSuffix(predictiveReportAnchorView?.anchor_trade_date ??
                    predictiveReportAnchorView?.asof_date) }}
                    <span style="margin-left: 6px;">公告 {{ formatDateOnly(predictiveReportAnchorView?.financial_ann_date)
                      || '-'
                      }}</span>
                  </div>
                </div>
              </el-col>
            </el-row>
            <div style="margin-bottom: 8px; color: #475569; font-size: 12px;">
              <span>分数变化 {{ formatGap(predictiveCompareSummary?.score_delta) }}</span>
              <span style="margin-left: 10px;">目标价变化 {{ formatGap(predictiveCompareSummary?.target_price_delta_pct)
                }}%</span>
              <el-tag size="small" effect="light" style="margin-left: 10px;"
                :type="predictiveCompareSummary?.action_changed ? 'warning' : 'success'">
                {{ predictiveCompareSummary?.action_changed ? '操作变化' : '操作稳定' }}
              </el-tag>
            </div>
            <div style="margin-bottom: 6px;">
              <el-button size="small" text @click="predictiveDetailExpanded = !predictiveDetailExpanded">
                {{ predictiveDetailExpanded ? '收起价格细节' : '展开价格细节' }}
              </el-button>
            </div>
            <div v-show="predictiveDetailExpanded"
              style="padding: 8px; border: 1px dashed #e5e7eb; border-radius: 6px; color: #64748b; font-size: 12px; line-height: 1.7;">
              <div>最新视图: 原始目标价 {{ formatPrice(predictiveLatestView?.target_price_raw) }} | 优化目标价 {{
                formatPrice(predictiveLatestView?.target_price_optimized) }} | 市场因子价 {{
                  formatPrice(applyMarketOverallAdjustedPrice(predictiveLatestView?.target_price_raw ??
                    predictiveLatestView?.target_price, marketOverallMultiplierForDisplay)) }}</div>
              <div>报告视图: 原始目标价 {{ formatPrice(predictiveReportAnchorView?.target_price_raw) }} | 优化目标价 {{
                formatPrice(predictiveReportAnchorView?.target_price_optimized) }} | 市场因子价 {{
                  formatPrice(applyMarketOverallAdjustedPrice(predictiveReportAnchorView?.target_price_raw ??
                    predictiveReportAnchorView?.target_price, marketOverallMultiplierForDisplay)) }}</div>
            </div>
          </div>
          <div v-else>
            <div style="color: #606266; margin-bottom: 6px;">{{ predictiveTierSummaryText }}</div>
            <el-alert v-if="predictiveTieredTemplate" type="info" :closable="false" show-icon
              style="margin-bottom: 8px;">
              <template #title>
                预测质量风格: {{ predictiveTieredTemplate.styleLabel }}
                <span style="margin-left: 6px; color: #64748b;">score {{
                  formatGap(predictiveTieredTemplate.reliabilityScore) }}</span>
              </template>
              <template #default>
                <div style="font-size: 12px; color: #64748b;">
                  依据 {{ predictiveTieredTemplate.reasons.join(' / ') || '-' }}
                </div>
              </template>
            </el-alert>
            <el-row :gutter="10">
              <el-col :span="8">
                <div class="valuation-side-card valuation-side-card-secondary">
                  <div><strong>风控优先</strong></div>
                  <div style="margin-top: 4px;">目标价 {{
                    formatPrice(predictiveTieredTemplate?.tiers?.conservative?.targetPrice)
                    }}</div>
                  <div style="margin-top: 4px;">预期收益 {{
                    formatGap(predictiveTieredTemplate?.tiers?.conservative?.expectedReturnPct) }}%</div>
                  <div style="margin-top: 4px;">区间 {{
                    formatPrice(predictiveTieredTemplate?.tiers?.conservative?.rangeLower) }}
                    - {{ formatPrice(predictiveTieredTemplate?.tiers?.conservative?.rangeUpper) }}</div>
                </div>
              </el-col>
              <el-col :span="8">
                <div class="valuation-side-card valuation-side-card-primary">
                  <div><strong>平衡</strong></div>
                  <div style="margin-top: 4px;">目标价 {{
                    formatPrice(predictiveTieredTemplate?.tiers?.balanced?.targetPrice) }}
                  </div>
                  <div style="margin-top: 4px;">预期收益 {{
                    formatGap(predictiveTieredTemplate?.tiers?.balanced?.expectedReturnPct)
                    }}%</div>
                  <div style="margin-top: 4px;">区间 {{ formatPrice(predictiveTieredTemplate?.tiers?.balanced?.rangeLower)
                    }} - {{
                      formatPrice(predictiveTieredTemplate?.tiers?.balanced?.rangeUpper) }}</div>
                </div>
              </el-col>
              <el-col :span="8">
                <div class="valuation-side-card valuation-side-card-secondary">
                  <div><strong>进攻</strong></div>
                  <div style="margin-top: 4px;">目标价 {{
                    formatPrice(predictiveTieredTemplate?.tiers?.aggressive?.targetPrice) }}
                  </div>
                  <div style="margin-top: 4px;">预期收益 {{
                    formatGap(predictiveTieredTemplate?.tiers?.aggressive?.expectedReturnPct) }}%</div>
                  <div style="margin-top: 4px;">区间 {{
                    formatPrice(predictiveTieredTemplate?.tiers?.aggressive?.rangeLower) }} -
                    {{ formatPrice(predictiveTieredTemplate?.tiers?.aggressive?.rangeUpper) }}</div>
                </div>
              </el-col>
            </el-row>
            <div style="margin-top: 8px; color: #334155; font-size: 12px;">
              仓位建议 {{ predictiveTieredTemplate?.positionRange || '-' }}
              <span style="margin-left: 8px; color: #64748b;">{{ predictiveTieredTemplate?.positionMessage || ''
                }}</span>
            </div>
          </div>
        </div>
        <div class="section-toggle" @click="variantTableExpanded = !variantTableExpanded">
          <span>多行业变体表格</span>
          <span>{{ variantTableExpanded ? '收起' : '展开' }}</span>
        </div>
        <div style="font-size: 12px; color: #334155; margin: 6px 0 8px 0;">
          {{ valuationRisk?.summary || '-' }}
        </div>
        <div v-show="variantTableExpanded">
          <el-tabs v-if="variantTabs.length > 1" v-model="activeVariant" class="valuation-variant-tabs"
            @tab-change="onVariantTabChange">
            <el-tab-pane v-for="item in variantTabs" :key="item.valuation_variant" :name="item.valuation_variant"
              :label="item.label" />
          </el-tabs>
          <el-table :data="visibleRows" size="small" style="width: 100%" empty-text="暂无估值数据">
            <el-table-column prop="valuation_method" label="方法" :width="95">
              <template #default="{ row }">
                <span>{{ methodLabel(row.valuation_method) }}</span>
                <el-tag v-if="row.corporate_action_impact?.impact_detected" size="small" effect="light" type="warning"
                  style="margin-left: 6px;">
                  除权影响
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="valuation_price" label="估值价(原/指)" :width="170">
              <template #default="{ row }">
                <span>{{ formatPrice(row.valuation_price) }}</span>
                <span style="margin-left: 4px; color: #93c5fd; font-weight: 600;">
                  / {{ formatPrice(applyMarketOverallAdjustedPrice(row.valuation_price,
                  marketOverallMultiplierForDisplay)) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="valuation_gap_pct" label="偏离(%)" :width="95">
              <template #default="{ row }">
                <span :style="{ color: Number(row.valuation_gap_pct || 0) >= 0 ? '#cf1322' : '#389e0d' }">
                  {{ formatGap(row.valuation_gap_pct) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="valuation_status" label="判断" :width="90">
              <template #default="{ row }">
                <el-tag v-if="row.valuation_status === 'under'" type="danger" size="small" effect="light">低估</el-tag>
                <el-tag v-else-if="row.valuation_status === 'over'" type="success" size="small"
                  effect="light">高估</el-tag>
                <el-tag v-else-if="row.valuation_status === 'fair'" type="info" size="small" effect="light">合理</el-tag>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="敏感" :width="90">
              <template #default="{ row }">
                <el-tag v-if="isThresholdSensitive(row.valuation_gap_pct)" type="warning" size="small"
                  effect="light">阈值敏感</el-tag>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column prop="source" label="来源" :width="90">
              <template #default="{ row }">
                <el-tag v-if="row.source === 'snapshot_cache' || row.source === 'prefill_command'" type="warning"
                  size="small" effect="light">缓存</el-tag>
                <el-tag v-else-if="row.source === 'live_compute'" type="primary" size="small" effect="light">实时</el-tag>
                <span v-else>{{ row.source || '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="profit_data_source" label="财报来源" :width="130">
              <template #default="{ row }">
                <span>{{ row.profit_data_source || '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="profit_report_end_date" label="财报期" :width="110">
              <template #default="{ row }">
                <span>{{ row.profit_report_end_date || '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="归一化估值" :width="122" show-overflow-tooltip>
              <template #default="{ row }">
                <span>{{ formatPrice(row.valuation_price_normalized_to_latest_share) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="归一化偏离(%)" :width="122" show-overflow-tooltip>
              <template #default="{ row }">
                <span
                  :style="{ color: Number(row.valuation_gap_pct_normalized_to_latest_share || 0) >= 0 ? '#cf1322' : '#389e0d' }">
                  {{ formatGap(row.valuation_gap_pct_normalized_to_latest_share) }}
                </span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </template>
    </el-skeleton>
  </el-card>
</template>

<script setup lang="ts">
import { ElAlert, ElButton, ElCard, ElCol, ElOption, ElRadioButton, ElRadioGroup, ElRow, ElSelect, ElSkeleton, ElSwitch, ElTable, ElTableColumn, ElTag, ElTabs, ElTabPane } from 'element-plus'
import axios from 'axios'
import { computed, inject, ref, watch, onMounted } from 'vue'
import { useStockTradeStore } from '../stores/stockTradeStore'
import { useStockChartFilterStore } from '../stores/stockChartFilterStore'
import { calculateDisplayReturnPct } from '../utils/valuationDisplay'
import { fetchValuationMethodsWithSharedCache } from '../utils/valuationQuickViewCache'

const props = defineProps({
  embedded: {
    type: Boolean,
    default: false,
  },
})
const embedded = props.embedded

type ValuationMethodRow = {
  valuation_method: string
  valuation_variant?: string
  valuation_price: number | null
  valuation_gap_pct: number | null
  valuation_status: string
  source: string | null
  profit_data_source?: string | null
  profit_report_end_date?: string | null
  profit_report_ann_date?: string | null
  profit_report_type?: string | null
  industry_level?: string | null
  industry_code?: string | null
  industry_name?: string | null
  compare_group?: string | null
  match_score?: number | null
  valuation_price_normalized_to_latest_share?: number | null
  valuation_gap_pct_normalized_to_latest_share?: number | null
  valuation_status_normalized_to_latest_share?: string | null
  snapshot_total_share?: number | null
  current_total_share?: number | null
  corporate_action_impact?: CorporateActionImpact | null
}

type CorporateActionDividendEvent = {
  end_date?: string | null
  ann_date?: string | null
  record_date?: string | null
  ex_date?: string | null
  pay_date?: string | null
  stock_distribution_ratio?: number | null
  cash_div_tax?: number | null
  div_proc?: string | null
}

type CorporateActionImpact = {
  impact_type?: string
  impact_detected?: boolean
  snapshot_trade_date?: string | null
  current_trade_date?: string | null
  snapshot_total_share?: number | null
  current_total_share?: number | null
  share_change_ratio_pct?: number | null
  latest_dividend_event?: CorporateActionDividendEvent | null
  message?: string | null
}

type ValuationVariantTab = {
  valuation_variant: string
  label: string
  industry_level?: string | null
  industry_code?: string | null
  industry_name?: string | null
  compare_group?: string | null
  match_score?: number | null
  method_count?: number
}

type ValuationSummary = {
  anchor_trade_date?: string | null
  anchor_basis_price?: number | null
  undervalue_score?: number | null
  buy_candidate?: boolean
  valuation_under_methods?: string[]
  valuation_valid_methods?: string[]
  composite_valuation_price: number | null
  composite_valuation_status: string
  composite_valuation_gap_pct: number | null
  composite_valuation_anchor_gap_pct?: number | null
  composite_valuation_price_raw?: number | null
  composite_valuation_price_optimized?: number | null
  composite_valuation_return_pct_raw?: number | null
  composite_valuation_return_pct_optimized?: number | null
  composite_valuation_status_optimized?: string
  composite_valuation_gap_pct_optimized?: number | null
  conservative_valuation_price: number | null
  conservative_valuation_status: string
  conservative_valuation_gap_pct: number | null
  conservative_valuation_anchor_gap_pct?: number | null
  conservative_valuation_price_raw?: number | null
  conservative_valuation_price_optimized?: number | null
  conservative_valuation_return_pct_raw?: number | null
  conservative_valuation_return_pct_optimized?: number | null
  conservative_valuation_status_optimized?: string
  conservative_valuation_gap_pct_optimized?: number | null
  market_style_valuation_price: number | null
  market_style_valuation_status: string
  market_style_valuation_gap_pct: number | null
  market_style_valuation_price_raw?: number | null
  market_style_valuation_price_optimized?: number | null
  market_style_valuation_return_pct_raw?: number | null
  market_style_valuation_return_pct_optimized?: number | null
  market_style_valuation_status_optimized?: string
  market_style_valuation_gap_pct_optimized?: number | null
  traditional_optimization_meta?: {
    enabled?: boolean
    method_count?: number | null
    dispersion_ratio?: number | null
    risk_score?: number | null
    reliability_weight?: number | null
  } | null
}

type TraditionalTierRange = {
  lower: number | null
  upper: number | null
}

type TraditionalTierItem = {
  label: string
  target_price: number | null
  expected_return_pct: number | null
  range: TraditionalTierRange
  coverage_ratio: number
  used_methods: string[]
  weights: Record<string, number>
}

type TraditionalTieredTemplate = {
  enabled: boolean
  style_key: string
  style_label: string
  style_score: number
  style_reasons: string[]
  industry_code?: string | null
  industry_name: string
  variant_weights?: Record<string, number>
  blend?: {
    enabled?: boolean
    applied?: boolean
    dominant_variant?: string
    active_variant?: string
    variant_count?: number
  } | null
  indicator_profile?: {
    roe?: number | null
    gross_margin?: number | null
    debt_to_assets?: number | null
    indicator_end_date?: string | null
  } | null
  method_prices?: Record<string, number>
  tiers: {
    conservative?: TraditionalTierItem
    balanced?: TraditionalTierItem
    aggressive?: TraditionalTierItem
  }
  position_guidance?: {
    suggested_position_range?: string
    message?: string
    holding_summary?: string
    style_key?: string
    style_label?: string
    volatility_bucket?: string
    volatility_label?: string
    state_key?: string
    state_label?: string
  } | null
  volatility_profile?: {
    atr?: number | null
    atr_ratio?: number | null
    realized_volatility_20d?: number | null
    volatility_bucket?: string | null
    volatility_label?: string | null
    lookback?: number | null
  } | null
  holding_summary?: string | null
  reference?: {
    current_price?: number | null
    traditional_composite_price?: number | null
    traditional_conservative_price?: number | null
  } | null
}

type PredictiveTierItem = {
  targetPrice: number | null
  expectedReturnPct: number | null
  rangeLower: number | null
  rangeUpper: number | null
}

type PredictiveTieredTemplate = {
  styleKey: 'high_confidence' | 'balanced' | 'low_confidence'
  styleLabel: string
  reliabilityScore: number
  reasons: string[]
  tiers: {
    conservative: PredictiveTierItem
    balanced: PredictiveTierItem
    aggressive: PredictiveTierItem
  }
  positionRange: string
  positionMessage: string
}

type EarningsSignal = {
  ts_code: string
  report_type: string
  anchor_mode?: string | null
  signal_score: number | null
  action: string
  risk_level: string
  target_price: number | null
  target_price_raw: number | null
  target_price_optimized: number | null
  target_market_cap: number | null
  target_market_cap_raw: number | null
  target_market_cap_optimized: number | null
  target_return_pct: number | null
  target_return_pct_raw: number | null
  target_return_pct_anchor?: number | null
  target_return_pct_anchor_optimized?: number | null
  target_return_pct_optimized: number | null
  target_price_low: number | null
  target_price_high: number | null
  target_price_low_raw: number | null
  target_price_high_raw: number | null
  target_price_low_optimized: number | null
  target_price_high_optimized: number | null
  target_market_cap_low: number | null
  target_market_cap_high: number | null
  target_market_cap_low_raw: number | null
  target_market_cap_high_raw: number | null
  target_market_cap_low_optimized: number | null
  target_market_cap_high_optimized: number | null
  target_return_low_pct: number | null
  target_return_high_pct: number | null
  target_return_low_pct_raw: number | null
  target_return_high_pct_raw: number | null
  target_return_low_pct_anchor?: number | null
  target_return_high_pct_anchor?: number | null
  target_return_low_pct_anchor_optimized?: number | null
  target_return_high_pct_anchor_optimized?: number | null
  target_return_low_pct_optimized: number | null
  target_return_high_pct_optimized: number | null
  model_version: string | null
  asof_date: string | null
  anchor_trade_date?: string | null
  anchor_close_price?: number | null
  financial_fiscal_year: number | null
  financial_ann_date: string | null
  market_regime: string | null
  quantitative_target_components: {
    base_return_pct?: number | null
    prob_return_pct?: number | null
    earnings_return_pct?: number | null
    industry_return_pct?: number | null
    max_abs_return_cap_pct?: number | null
    market_regime?: string | null
    market_overall_adjustment?: {
      enabled?: boolean
      state?: string | null
      score?: number | null
      multiplier?: number | null
      asof_trade_date?: string | null
    } | null
  } | null
  predictive_tiered_template?: PredictiveTieredTemplate | null
}

type PredictiveCompareSummary = {
  score_delta: number | null
  target_price_delta_pct: number | null
  action_changed: boolean
  confidence_hint: string
}

type PredictiveComparePayload = {
  ts_code: string
  selected_report_type: string
  latest_view: any
  report_anchor_view: any
  compare_summary?: PredictiveCompareSummary | null
  compare_meta?: {
    anchor_policy?: string
    fusion_policy?: string
  } | null
}

type ValuationRisk = {
  risk_level: string
  risk_score: number | null
  summary: string | null
}

const baseURL = inject<string>('baseURL', '')
const stockTradeStore = useStockTradeStore()
const stockChartFilterStore = useStockChartFilterStore()

const rows = ref<ValuationMethodRow[]>([])
const dataByVariant = ref<Record<string, ValuationMethodRow[]>>({})
const summaryByVariant = ref<Record<string, ValuationSummary>>({})
const summaryByVariantNormalized = ref<Record<string, ValuationSummary>>({})
const summaryByVariantOptimized = ref<Record<string, ValuationSummary>>({})
const summaryByVariantNormalizedOptimized = ref<Record<string, ValuationSummary>>({})
const variantTabs = ref<ValuationVariantTab[]>([])
const activeVariant = ref('default')
const currentPrice = ref<number | null>(null)
const currentTradeDate = ref<string>('')
const currentTotalShare = ref<number | null>(null)
const loading = ref(false)
const bandPct = ref('0.1')
const fetchSeq = ref(0)
const predictiveFetchSeq = ref(0)
const earningsSignal = ref<EarningsSignal | null>(null)
const valuationRisk = ref<ValuationRisk | null>(null)
const earningsDegradeReason = ref<string>('')
const selectedEarningsReportType = ref('FY')
const selectedPredictModelSlot = ref('production')
const selectedPredictAnchorMode = ref<'ann' | 'live'>('ann')
const lastValuationReportType = ref('FY')
const userPinnedReportType = ref(false)
const programmaticReportTypeSync = ref(false)
const skipNextValuationFetch = ref(false)
const summary = ref<ValuationSummary>(emptySummary())
const summaryNormalized = ref<ValuationSummary>(emptySummary())
const summaryOptimized = ref<ValuationSummary>(emptySummary())
const summaryNormalizedOptimized = ref<ValuationSummary>(emptySummary())
const traditionalTieredTemplateByVariant = ref<Record<string, TraditionalTieredTemplate>>({})
const topTraditionalTieredTemplate = ref<TraditionalTieredTemplate | null>(null)
const traditionalTieredTemplate = ref<TraditionalTieredTemplate | null>(null)
const valuationSectionExpanded = ref(true)
const traditionalValuationTab = ref('snapshot')
const predictiveValuationTab = ref('snapshot')
const variantTableExpanded = ref(false)
const predictiveLoading = ref(false)
const predictiveLastRefreshAt = ref<number | null>(null)
const predictiveFusionFallbackHit = ref(false)
const predictiveDetailExpanded = ref(false)
const predictiveCompare = ref<PredictiveComparePayload | null>(null)
const predictiveSignalCache = new Map<string, any>()
const predictiveSignalPending = new Map<string, Promise<any>>()

function emptySummary(): ValuationSummary {
  return {
    anchor_trade_date: null,
    anchor_basis_price: null,
    composite_valuation_price: null,
    composite_valuation_status: 'unknown',
    composite_valuation_gap_pct: null,
    composite_valuation_anchor_gap_pct: null,
    conservative_valuation_price: null,
    conservative_valuation_status: 'unknown',
    conservative_valuation_gap_pct: null,
    conservative_valuation_anchor_gap_pct: null,
    market_style_valuation_price: null,
    market_style_valuation_status: 'unknown',
    market_style_valuation_gap_pct: null,
    traditional_optimization_meta: null,
  }
}

function resolveSummary(raw: any): ValuationSummary {
  return {
    anchor_trade_date: raw?.anchor_trade_date ?? null,
    anchor_basis_price: raw?.anchor_basis_price ?? null,
    undervalue_score: raw?.undervalue_score ?? null,
    buy_candidate: Boolean(raw?.buy_candidate),
    valuation_under_methods: Array.isArray(raw?.valuation_under_methods) ? raw.valuation_under_methods : [],
    valuation_valid_methods: Array.isArray(raw?.valuation_valid_methods) ? raw.valuation_valid_methods : [],
    composite_valuation_price: raw?.composite_valuation_price ?? null,
    composite_valuation_status: String(raw?.composite_valuation_status || 'unknown'),
    composite_valuation_gap_pct: raw?.composite_valuation_gap_pct ?? null,
    composite_valuation_anchor_gap_pct: raw?.composite_valuation_anchor_gap_pct ?? null,
    composite_valuation_price_raw: raw?.composite_valuation_price_raw ?? null,
    composite_valuation_price_optimized: raw?.composite_valuation_price_optimized ?? null,
    composite_valuation_return_pct_raw: raw?.composite_valuation_return_pct_raw ?? null,
    composite_valuation_return_pct_optimized: raw?.composite_valuation_return_pct_optimized ?? null,
    composite_valuation_status_optimized: raw?.composite_valuation_status_optimized ? String(raw.composite_valuation_status_optimized) : 'unknown',
    composite_valuation_gap_pct_optimized: raw?.composite_valuation_gap_pct_optimized ?? null,
    conservative_valuation_price: raw?.conservative_valuation_price ?? null,
    conservative_valuation_status: String(raw?.conservative_valuation_status || 'unknown'),
    conservative_valuation_gap_pct: raw?.conservative_valuation_gap_pct ?? null,
    conservative_valuation_anchor_gap_pct: raw?.conservative_valuation_anchor_gap_pct ?? null,
    conservative_valuation_price_raw: raw?.conservative_valuation_price_raw ?? null,
    conservative_valuation_price_optimized: raw?.conservative_valuation_price_optimized ?? null,
    conservative_valuation_return_pct_raw: raw?.conservative_valuation_return_pct_raw ?? null,
    conservative_valuation_return_pct_optimized: raw?.conservative_valuation_return_pct_optimized ?? null,
    conservative_valuation_status_optimized: raw?.conservative_valuation_status_optimized ? String(raw.conservative_valuation_status_optimized) : 'unknown',
    conservative_valuation_gap_pct_optimized: raw?.conservative_valuation_gap_pct_optimized ?? null,
    market_style_valuation_price: raw?.market_style_valuation_price ?? null,
    market_style_valuation_status: String(raw?.market_style_valuation_status || 'unknown'),
    market_style_valuation_gap_pct: raw?.market_style_valuation_gap_pct ?? null,
    market_style_valuation_price_raw: raw?.market_style_valuation_price_raw ?? null,
    market_style_valuation_price_optimized: raw?.market_style_valuation_price_optimized ?? null,
    market_style_valuation_return_pct_raw: raw?.market_style_valuation_return_pct_raw ?? null,
    market_style_valuation_return_pct_optimized: raw?.market_style_valuation_return_pct_optimized ?? null,
    market_style_valuation_status_optimized: raw?.market_style_valuation_status_optimized ? String(raw.market_style_valuation_status_optimized) : 'unknown',
    market_style_valuation_gap_pct_optimized: raw?.market_style_valuation_gap_pct_optimized ?? null,
    traditional_optimization_meta: raw?.traditional_optimization_meta ?? null,
  }
}

const methodLabelMap: Record<string, string> = {
  scarcity_overlay: '稀缺性',
  market_style: '市场风格',
  pe: 'PE',
  pb: 'PB',
  ps: 'PS',
  peg: 'PEG',
  fcff_dcf: 'FCFF',
  ddm: 'DDM',
  market_cap: '市值法',
}

const visibleRows = computed(() =>
  rows.value.filter((item) => String(item.valuation_method || '').toLowerCase() !== 'market_style')
)

function onVariantTabChange(tabName: string | number) {
  const variant = String(tabName || 'default')
  activeVariant.value = variant
  const variantRows = (dataByVariant.value[variant] || []) as ValuationMethodRow[]
  rows.value = variantRows
  summary.value = summaryByVariant.value[variant] || emptySummary()
  summaryNormalized.value = summaryByVariantNormalized.value[variant] || emptySummary()
  summaryOptimized.value = summaryByVariantOptimized.value[variant] || emptySummary()
  summaryNormalizedOptimized.value = summaryByVariantNormalizedOptimized.value[variant] || emptySummary()
  traditionalTieredTemplate.value = resolveTraditionalTemplatePriority(
    topTraditionalTieredTemplate.value,
    traditionalTieredTemplateByVariant.value,
    variant,
    variantRows,
    summaryByVariant.value[variant] || emptySummary(),
    currentPrice.value ?? stockTradeStore.close,
  )
}

function methodLabel(method: string) {
  return methodLabelMap[method] || method?.toUpperCase?.() || '-'
}

function tierCoverageText(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '-'
  return `${(Number(value) * 100).toFixed(0)}%`
}

function tierWeightPreview(weights: Record<string, number> | null | undefined) {
  if (!weights || typeof weights !== 'object') return '-'
  const entries = Object.entries(weights)
    .filter(([, weight]) => Number(weight) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 4)
    .map(([method, weight]) => `${methodLabel(method)} ${(Number(weight) * 100).toFixed(0)}%`)
  return entries.length ? entries.join(' | ') : '-'
}

function resolveTraditionalTemplatePriority(
  topTemplate: TraditionalTieredTemplate | null | undefined,
  byVariant: Record<string, TraditionalTieredTemplate>,
  variant: string,
  variantRows: ValuationMethodRow[],
  summaryPayload: ValuationSummary,
  currentPriceInput: number | null,
): TraditionalTieredTemplate | null {
  if (topTemplate && typeof topTemplate === 'object') {
    return topTemplate
  }
  if (byVariant && byVariant[variant]) {
    return byVariant[variant]
  }
  return (
    _buildFallbackTraditionalTieredTemplate(
      variant,
      variantRows,
      summaryPayload,
      currentPriceInput,
    ) || null
  )
}

const traditionalBlendHintText = computed(() => {
  const payload = traditionalTieredTemplate.value
  if (!payload || !payload.enabled) return ''
  const blend = payload.blend
  const variantWeights = payload.variant_weights
  if (!blend || !blend.enabled || !variantWeights || typeof variantWeights !== 'object') {
    return ''
  }

  const dominant = String(blend.dominant_variant || '').trim()
  const topWeights = Object.entries(variantWeights)
    .filter(([, weight]) => Number.isFinite(Number(weight)) && Number(weight) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 3)
    .map(([variantName, weight]) => `${variantName} ${(Number(weight) * 100).toFixed(1)}%`)

  const chunks: string[] = []
  if (blend.applied) chunks.push('融合已启用')
  if (dominant) chunks.push(`主导 ${dominant}`)
  if (topWeights.length) chunks.push(`权重 ${topWeights.join(' | ')}`)
  return chunks.join(' · ')
})

function _clamp(value: number, low: number, high: number) {
  return Math.max(low, Math.min(high, value))
}

function _quantile(sortedValues: number[], q: number) {
  if (!sortedValues.length) return null
  const qq = _clamp(q, 0, 1)
  const index = (sortedValues.length - 1) * qq
  const low = Math.floor(index)
  const high = Math.ceil(index)
  const lv = sortedValues[low]
  const hv = sortedValues[high]
  if (low === high) return lv
  return lv + (hv - lv) * (index - low)
}

function _resolveFallbackTierWeights(methodPrices: Record<string, number>, styleKey: string): Record<string, number> {
  const preferredByStyle: Record<string, string[]> = {
    conservative: ['pb', 'pe', 'ddm', 'fcff_dcf', 'ps', 'peg', 'sw_history', 'scarcity_overlay'],
    balanced: ['pe', 'pb', 'ps', 'fcff_dcf', 'ddm', 'peg', 'sw_history', 'scarcity_overlay'],
    aggressive: ['pe', 'ps', 'peg', 'scarcity_overlay', 'sw_history', 'pb', 'fcff_dcf', 'ddm'],
  }
  const ordered = preferredByStyle[styleKey] || preferredByStyle.balanced
  const available = ordered.filter((method) => Number.isFinite(Number(methodPrices[method])))
  if (!available.length) return {}

  const sliced = available.slice(0, 4)
  const base = sliced.map((_, index) => Math.max(0.1, 1 - index * 0.18))
  const total = base.reduce((acc, num) => acc + num, 0) || 1
  const result: Record<string, number> = {}
  sliced.forEach((method, index) => {
    result[method] = Number((base[index] / total).toFixed(4))
  })
  return result
}

type PredictiveIndustryRegime = 'growth' | 'cyclical' | 'defensive'

const PREDICTIVE_REGIME_CODE_RULES: Array<{ regime: PredictiveIndustryRegime; prefixes: string[] }> = [
  // 与后端传统高成长映射保持一致
  { regime: 'growth', prefixes: ['80108', '80175', '80176', '8515'] },
  // 与后端传统周期资源映射保持一致
  {
    regime: 'cyclical',
    prefixes: ['80102', '80103', '80104', '80105', '80106', '80107', '80109', '80111', '80112', '80117', '80118', '80119', '80120', '80121', '8517', '8503', '85037', '85038', '85039', '85040'],
  },
  // 与后端传统稳定价值映射保持一致
  { regime: 'defensive', prefixes: ['80178', '80179', '80188', '80195', '80196'] },
]

function _normalizeIndustryCode(raw: unknown): string {
  const text = String(raw || '').trim().toUpperCase()
  if (!text) return ''
  const matched = text.match(/\d+/)
  return matched ? matched[0] : ''
}

function _resolvePredictiveIndustryRegime(industryCodeRaw: unknown): PredictiveIndustryRegime | null {
  const code = _normalizeIndustryCode(industryCodeRaw)
  if (!code) return null
  for (const rule of PREDICTIVE_REGIME_CODE_RULES) {
    if (rule.prefixes.some((prefix) => code.startsWith(prefix))) {
      return rule.regime
    }
  }
  return null
}

function _resolvePredictiveRegimeFromTraditionalStyleKey(styleKeyRaw: unknown): PredictiveIndustryRegime | null {
  const styleKey = String(styleKeyRaw || '').trim().toLowerCase()
  if (!styleKey) return null
  if (styleKey === 'high_growth') return 'growth'
  if (styleKey === 'cyclical_resource') return 'cyclical'
  if (styleKey === 'stable_value') return 'defensive'
  return null
}

function _resolvePredictiveIndustryCodeCandidates(): string[] {
  const activeVariantName = String(activeVariant.value || 'default')
  const activeMeta = variantTabs.value.find((item) => String(item.valuation_variant || '') === activeVariantName)
  const fromActiveMeta = String(activeMeta?.industry_code || '').trim()
  const fromTemplate = String(traditionalTieredTemplate.value?.industry_code || '').trim()
  const fromRows = (rows.value || [])
    .map((row) => String(row?.industry_code || '').trim())
    .filter((code) => Boolean(code))
  const ordered = [fromActiveMeta, fromTemplate, ...fromRows].filter((code) => Boolean(code))
  return Array.from(new Set(ordered))
}

function _buildFallbackTraditionalTieredTemplate(
  variant: string,
  variantRows: ValuationMethodRow[],
  summaryPayload: ValuationSummary,
  currentPriceInput: number | null,
): TraditionalTieredTemplate | null {
  const cp = toNullableNumber(currentPriceInput)
  if (cp === null || cp <= 0) return null

  const methodPrices: Record<string, number> = {}
  for (const row of variantRows || []) {
    const method = String(row?.valuation_method || '').trim().toLowerCase()
    const price = toNullableNumber(row?.valuation_price)
    if (!method || price === null || price <= 0) continue
    methodPrices[method] = price
  }

  const rawPrices = Object.values(methodPrices).filter((value) => Number.isFinite(value) && value > 0)
  const sorted = [...rawPrices].sort((a, b) => a - b)
  if (!sorted.length) return null

  const q35 = _quantile(sorted, 0.35) ?? sorted[0]
  const q50 = _quantile(sorted, 0.5) ?? sorted[Math.floor(sorted.length / 2)]
  const q70 = _quantile(sorted, 0.7) ?? sorted[sorted.length - 1]

  const conservativeFromSummary = toNullableNumber(summaryPayload?.conservative_valuation_price)
  const balancedFromSummary = toNullableNumber(summaryPayload?.composite_valuation_price)

  let conservativeTarget = conservativeFromSummary ?? q35
  let balancedTarget = balancedFromSummary ?? q50
  let aggressiveTarget = Math.max(q70, balancedTarget * 1.08)

  conservativeTarget = Math.min(conservativeTarget, balancedTarget * 0.98)
  aggressiveTarget = Math.max(aggressiveTarget, balancedTarget * 1.03)

  const methodCount = sorted.length
  const dispersionPct = (sorted[sorted.length - 1] - sorted[0]) / (q50 || cp)
  const reliabilityScore = _clamp(85 - dispersionPct * 120 + methodCount * 4, 20, 92)

  let styleKey = 'balanced'
  let styleLabel = '平衡风格'
  if (reliabilityScore >= 72) {
    styleKey = 'aggressive'
    styleLabel = '高可信进攻'
  } else if (reliabilityScore <= 48) {
    styleKey = 'conservative'
    styleLabel = '防守优先'
  }

  const volatilityBucket = dispersionPct >= 0.55 ? 'high' : (dispersionPct >= 0.3 ? 'mid' : 'low')
  const volatilityLabel = volatilityBucket === 'high' ? '高波动' : (volatilityBucket === 'mid' ? '中波动' : '低波动')

  const rangeRule = volatilityBucket === 'high'
    ? {
      conservative: [0.95, 1.02],
      balanced: [0.94, 1.07],
      aggressive: [0.92, 1.14],
    }
    : volatilityBucket === 'low'
      ? {
        conservative: [0.97, 1.03],
        balanced: [0.96, 1.06],
        aggressive: [0.94, 1.1],
      }
      : {
        conservative: [0.96, 1.03],
        balanced: [0.95, 1.07],
        aggressive: [0.93, 1.12],
      }

  const buildTier = (
    label: string,
    target: number,
    lowerMul: number,
    upperMul: number,
    coverage: number,
    weightStyle: string,
  ): TraditionalTierItem => ({
    label,
    target_price: Number(target.toFixed(4)),
    expected_return_pct: Number((((target / cp) - 1.0) * 100).toFixed(2)),
    range: {
      lower: Number((target * lowerMul).toFixed(4)),
      upper: Number((target * upperMul).toFixed(4)),
    },
    coverage_ratio: coverage,
    used_methods: Object.keys(_resolveFallbackTierWeights(methodPrices, weightStyle)),
    weights: _resolveFallbackTierWeights(methodPrices, weightStyle),
  })

  const tiers = {
    conservative: buildTier('风控优先', conservativeTarget, rangeRule.conservative[0], rangeRule.conservative[1], 0.3, 'conservative'),
    balanced: buildTier('平衡', balancedTarget, rangeRule.balanced[0], rangeRule.balanced[1], 0.5, 'balanced'),
    aggressive: buildTier('成长进攻', aggressiveTarget, rangeRule.aggressive[0], rangeRule.aggressive[1], 0.2, 'aggressive'),
  }

  const conLower = toNullableNumber(tiers.conservative.range.lower)
  const balLower = toNullableNumber(tiers.balanced.range.lower)
  const balUpper = toNullableNumber(tiers.balanced.range.upper)
  const aggUpper = toNullableNumber(tiers.aggressive.range.upper)

  let stateKey = 'within_balanced'
  let stateLabel = '平衡区间'
  let suggestedRange = '35%-55%'
  let message = '位于平衡区间，维持中性仓位。'

  if (conLower !== null && cp < conLower) {
    stateKey = 'below_conservative'
    stateLabel = '低估区'
    suggestedRange = volatilityBucket === 'high' ? '50%-70%' : '60%-80%'
    message = '低于保守区下沿，建议分批提升仓位。'
  } else if (balLower !== null && cp < balLower) {
    stateKey = 'below_balanced'
    stateLabel = '偏低区'
    suggestedRange = volatilityBucket === 'high' ? '40%-60%' : '45%-65%'
    message = '低于平衡区下沿，建议温和加仓。'
  } else if (aggUpper !== null && cp > aggUpper) {
    stateKey = 'above_aggressive'
    stateLabel = '高估区'
    suggestedRange = volatilityBucket === 'high' ? '10%-25%' : '15%-30%'
    message = '高于进攻区上沿，建议防守并降低仓位。'
  } else if (balUpper !== null && cp > balUpper) {
    stateKey = 'within_aggressive'
    stateLabel = '偏高区'
    suggestedRange = volatilityBucket === 'high' ? '20%-35%' : '25%-40%'
    message = '处于偏高区间，建议逐步降仓。'
  }

  const variantMeta = variantTabs.value.find((item) => String(item.valuation_variant || '') === String(variant || ''))
  const industryName = String(variantMeta?.industry_name || variantMeta?.label || '').trim() || '默认估值'
  const holdingSummary = `${styleLabel} | 波动${volatilityLabel} | 平衡目标 ${formatPrice(tiers.balanced.target_price)} | 建议仓位 ${suggestedRange}`

  return {
    enabled: true,
    style_key: styleKey,
    style_label: styleLabel,
    style_score: Number(reliabilityScore.toFixed(2)),
    style_reasons: [
      `method_count=${methodCount}`,
      `dispersion=${(dispersionPct * 100).toFixed(2)}%`,
      'fallback_from_summary',
    ],
    industry_name: industryName,
    method_prices: Object.fromEntries(Object.entries(methodPrices).map(([k, v]) => [k, Number(v.toFixed(4))])),
    tiers,
    position_guidance: {
      suggested_position_range: suggestedRange,
      message,
      holding_summary: holdingSummary,
      style_key: styleKey,
      style_label: styleLabel,
      volatility_bucket: volatilityBucket,
      volatility_label: volatilityLabel,
      state_key: stateKey,
      state_label: stateLabel,
    },
    volatility_profile: {
      atr: null,
      atr_ratio: null,
      realized_volatility_20d: null,
      volatility_bucket: volatilityBucket,
      volatility_label: volatilityLabel,
      lookback: 20,
    },
    holding_summary: holdingSummary,
    reference: {
      current_price: cp,
      traditional_composite_price: balancedFromSummary,
      traditional_conservative_price: conservativeFromSummary,
    },
  }
}

const traditionalTierSummaryText = computed(() => {
  const payload = traditionalTieredTemplate.value
  if (!payload || !payload.enabled) {
    return '模板不可用'
  }
  const holdingSummary = String(payload.holding_summary || payload.position_guidance?.holding_summary || '').trim()
  if (holdingSummary) {
    return holdingSummary
  }
  const balanced = payload.tiers?.balanced
  if (!balanced) {
    return `${payload.style_label}风格 | 模板待补全`
  }
  const volatilityLabel = payload.volatility_profile?.volatility_label || payload.position_guidance?.volatility_label || '中波动'
  return `${payload.style_label}风格 | ${volatilityLabel} | 平衡目标 ${formatPrice(balanced.target_price)} | 参考仓位 ${payload.position_guidance?.suggested_position_range || '-'}`
})

const holdingSummaryText = computed(() => {
  const traditional = traditionalTieredTemplate.value
  if (!traditional || !traditional.enabled) {
    return '模板不可用'
  }

  const baseSummary = traditionalTierSummaryText.value
  const predictive = predictiveTieredTemplate.value
  if (predictive) {
    return `${baseSummary} | 预测节奏 ${predictive.styleLabel} ${predictive.positionRange}，${predictive.positionMessage}`
  }
  return baseSummary
})

const traditionalPositionTriggerHints = computed(() => {
  const payload = traditionalTieredTemplate.value
  const guidance = payload?.position_guidance
  const tiers = payload?.tiers || {}

  const conLower = toNullableNumber(tiers.conservative?.range?.lower)
  const balLower = toNullableNumber(tiers.balanced?.range?.lower)
  const balUpper = toNullableNumber(tiers.balanced?.range?.upper)
  const aggUpper = toNullableNumber(tiers.aggressive?.range?.upper)
  const stateKey = String(guidance?.state_key || '').trim().toLowerCase()

  const unknown = '待价格更新后计算'
  const cp = toNullableNumber(payload?.reference?.current_price ?? currentPrice.value ?? stockTradeStore.close)
  if (cp === null || cp <= 0) {
    return {
      upgradeHint: unknown,
      downgradeHint: unknown,
    }
  }

  switch (stateKey) {
    case 'below_conservative':
      return {
        upgradeHint: '已处于本模板最高仓位档',
        downgradeHint: conLower !== null ? `若股价反弹至 >= ${formatPrice(conLower)}，仓位可能下调` : unknown,
      }
    case 'below_balanced':
      return {
        upgradeHint: conLower !== null ? `若股价回落至 <= ${formatPrice(conLower)}，可提升仓位` : unknown,
        downgradeHint: balLower !== null ? `若股价反弹至 >= ${formatPrice(balLower)}，仓位可能下调` : unknown,
      }
    case 'within_balanced':
      return {
        upgradeHint: balLower !== null ? `若股价回落至 < ${formatPrice(balLower)}，可提升仓位` : unknown,
        downgradeHint: balUpper !== null ? `若股价上行至 > ${formatPrice(balUpper)}，仓位可能下调` : unknown,
      }
    case 'within_aggressive':
      return {
        upgradeHint: balUpper !== null ? `若股价回落至 <= ${formatPrice(balUpper)}，可提升仓位` : unknown,
        downgradeHint: aggUpper !== null ? `若股价上行至 > ${formatPrice(aggUpper)}，仓位可能下调` : unknown,
      }
    case 'above_aggressive':
      return {
        upgradeHint: aggUpper !== null ? `若股价回落至 <= ${formatPrice(aggUpper)}，可提升仓位` : unknown,
        downgradeHint: '已处于本模板最低仓位档',
      }
    default:
      return {
        upgradeHint: conLower !== null ? `关注 ${formatPrice(conLower)} 下方加仓机会` : unknown,
        downgradeHint: aggUpper !== null ? `关注 ${formatPrice(aggUpper)} 上方减仓风险` : unknown,
      }
  }
})

const klineTriggerOverlayEnabled = computed({
  get: () => Boolean(stockTradeStore.positionTriggerLineEnabled),
  set: (value: boolean) => stockTradeStore.setPositionTriggerLineEnabled(Boolean(value)),
})

function resolveTraditionalTriggerPrices(payload: TraditionalTieredTemplate | null): { upgradePrice: number | null; downgradePrice: number | null } {
  const tiers = payload?.tiers || {}
  const conLower = toNullableNumber(tiers.conservative?.range?.lower)
  const balLower = toNullableNumber(tiers.balanced?.range?.lower)
  const balUpper = toNullableNumber(tiers.balanced?.range?.upper)
  const aggUpper = toNullableNumber(tiers.aggressive?.range?.upper)
  const stateKey = String(payload?.position_guidance?.state_key || '').trim().toLowerCase()

  switch (stateKey) {
    case 'below_conservative':
      return { upgradePrice: null, downgradePrice: conLower }
    case 'below_balanced':
      return { upgradePrice: conLower, downgradePrice: balLower }
    case 'within_balanced':
      return { upgradePrice: balLower, downgradePrice: balUpper }
    case 'within_aggressive':
      return { upgradePrice: balUpper, downgradePrice: aggUpper }
    case 'above_aggressive':
      return { upgradePrice: aggUpper, downgradePrice: null }
    default:
      return { upgradePrice: conLower, downgradePrice: aggUpper }
  }
}

function syncTraditionalTriggerLinesToStore() {
  const tsCode = toCanonicalTsCode(stockTradeStore.tsCode)
  if (!tsCode || !traditionalTieredTemplate.value) {
    stockTradeStore.clearPositionTriggerLines()
    return
  }
  const { upgradePrice, downgradePrice } = resolveTraditionalTriggerPrices(traditionalTieredTemplate.value)
  stockTradeStore.setPositionTriggerLines({
    tsCode,
    upgradePrice,
    downgradePrice,
  })
}

function formatPrice(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '-'
  return Number(value).toFixed(2)
}

function formatMultiplier(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '-'
  return Number(value).toFixed(4)
}

function formatGap(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '-'
  return Number(value).toFixed(2)
}

function resolveDisplayReturnPct(targetPrice: number | null | undefined, fallbackReturnPct: number | null | undefined) {
  return calculateDisplayReturnPct(targetPrice, currentPrice.value, stockTradeStore.close, fallbackReturnPct)
}

function formatScore(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '-'
  return Number(value).toFixed(1)
}

function formatDateOnly(value: string | null | undefined) {
  const text = String(value || '').trim()
  if (!text) return ''
  return text.length >= 10 ? text.slice(0, 10) : text
}

function formatAnchorDateSuffix(value: string | null | undefined) {
  const text = formatDateOnly(value)
  return text ? `(${text})` : ''
}

function formatTime(value: number | null | undefined) {
  if (!value || !Number.isFinite(Number(value))) return ''
  const date = new Date(Number(value))
  const hh = String(date.getHours()).padStart(2, '0')
  const mm = String(date.getMinutes()).padStart(2, '0')
  const ss = String(date.getSeconds()).padStart(2, '0')
  return `${hh}:${mm}:${ss}`
}

function anchorTrendSymbol(anchorPct: number | null | undefined, currentPct: number | null | undefined) {
  if (anchorPct === null || anchorPct === undefined || currentPct === null || currentPct === undefined) return ''
  return Number(anchorPct) >= Number(currentPct) ? '↑' : '↓'
}

function anchorTrendColor(anchorPct: number | null | undefined, currentPct: number | null | undefined) {
  if (anchorPct === null || anchorPct === undefined || currentPct === null || currentPct === undefined) return '#8c8c8c'
  return Number(anchorPct) >= Number(currentPct) ? '#dc2626' : '#16a34a'
}

function resolveAnchorSnapshotReturnPct(summaryPayload: ValuationSummary | null | undefined) {
  const anchorPrice = toNullableNumber(summaryPayload?.anchor_basis_price)
  const latestPrice = toNullableNumber(currentPrice.value ?? stockTradeStore.close)
  if (anchorPrice === null || latestPrice === null || anchorPrice <= 0) return null
  return ((latestPrice - anchorPrice) / anchorPrice) * 100
}

function anchorSnapshotTrendSymbol(returnPct: number | null | undefined) {
  if (returnPct === null || returnPct === undefined) return ''
  return Number(returnPct) >= 0 ? '↑' : '↓'
}

function anchorSnapshotTrendColor(returnPct: number | null | undefined) {
  if (returnPct === null || returnPct === undefined) return '#8c8c8c'
  return Number(returnPct) >= 0 ? '#dc2626' : '#16a34a'
}

function resolvePredictiveAnchorSnapshotReturnPct() {
  const anchorPrice = toNullableNumber(earningsSignal.value?.anchor_close_price)
  const latestPrice = toNullableNumber(currentPrice.value ?? stockTradeStore.close)
  if (anchorPrice === null || latestPrice === null || anchorPrice <= 0) return null
  return ((latestPrice - anchorPrice) / anchorPrice) * 100
}

function toNullableNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const num = Number(value)
  return Number.isFinite(num) ? num : null
}

function applyMarketOverallAdjustedPrice(price: number | null | undefined, multiplier: number | null | undefined) {
  const rawPrice = toNullableNumber(price)
  const factor = toNullableNumber(multiplier)
  if (rawPrice === null || factor === null) return null
  if (factor <= 0) return null
  return rawPrice * factor
}

function formatMarketCap(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '-'
  const numeric = Number(value)
  const absValue = Math.abs(numeric)
  // target_market_cap from BE is in 10k CNY (万元).
  if (absValue >= 1e4) {
    return `${(numeric / 1e4).toFixed(2)}亿`
  }
  return `${numeric.toFixed(2)}万`
}

function resolveDisplayMarketCap(
  targetMarketCap: number | null | undefined,
  targetPrice: number | null | undefined
) {
  const direct = toNullableNumber(targetMarketCap)
  if (direct !== null) {
    return direct
  }

  const inferredPrice = toNullableNumber(targetPrice)
  if (inferredPrice === null || inferredPrice <= 0) {
    return null
  }

  const sharesIn10k = toNullableNumber(currentTotalShare.value)
  if (sharesIn10k === null || sharesIn10k <= 0) {
    return null
  }

  // currentTotalShare is in 10k shares, so inferred market cap is in 10k CNY (万元).
  return inferredPrice * sharesIn10k
}

function resolveAnchorMarketCap(anchorClosePrice: number | null | undefined) {
  const anchorPrice = toNullableNumber(anchorClosePrice)
  if (anchorPrice === null || anchorPrice <= 0) {
    return null
  }

  const sharesIn10k = toNullableNumber(currentTotalShare.value)
  if (sharesIn10k === null || sharesIn10k <= 0) {
    return null
  }

  return anchorPrice * sharesIn10k
}

function toCanonicalTsCode(code: string) {
  const normalized = String(code || '').trim().toUpperCase()
  if (!normalized) return ''
  if (normalized.includes('.')) return normalized
  if (!/^\d{6}$/.test(normalized)) return normalized
  if (normalized.startsWith('6') || normalized.startsWith('5') || normalized.startsWith('9')) {
    return `${normalized}.SH`
  }
  if (normalized.startsWith('8') || normalized.startsWith('4')) {
    return `${normalized}.BJ`
  }
  return `${normalized}.SZ`
}

function isSameTsCode(requestTsCode: string, returnedTsCode: string) {
  if (!requestTsCode || !returnedTsCode) return false
  const req = String(requestTsCode).trim().toUpperCase()
  const ret = String(returnedTsCode).trim().toUpperCase()
  if (req === ret) return true
  return toCanonicalTsCode(req) === toCanonicalTsCode(ret)
}

function normalizeEarningsReportTypeForSignal(reportType: string) {
  const normalized = String(reportType || '').toUpperCase().trim()
  if (!normalized) return ''
  if (normalized === '快' || normalized === 'EXP' || normalized === 'EXPRESS') return 'EXP'
  if (normalized === 'ANNUAL' || normalized === 'FULL_YEAR' || normalized === 'A') return 'FY'
  if (normalized === 'Q1' || normalized === 'H1' || normalized === 'Q3' || normalized === 'FY' || normalized === 'FUSION') return normalized
  return ''
}

function normalizeQuickViewReportType(reportType: string | null | undefined) {
  const normalized = String(reportType || '').toUpperCase().trim()
  if (normalized === 'ANNUAL') return 'FY'
  if (normalized === 'Q1' || normalized === 'H1' || normalized === 'Q3' || normalized === 'FY' || normalized === 'FUSION' || normalized === '快') {
    return normalized
  }
  return ''
}

function inferExpectedEndDateForReportType(reportType: string, tradeDate: string | null | undefined) {
  const normalized = String(reportType || '').toUpperCase().trim()
  const tradeYear = Number(String(tradeDate || '').slice(0, 4))
  if (!Number.isFinite(tradeYear)) {
    return ''
  }
  if (normalized === 'Q1') return `${tradeYear}-03-31`
  if (normalized === 'H1') return `${tradeYear}-06-30`
  if (normalized === 'Q3') return `${tradeYear}-09-30`
  if (normalized === 'FY') return `${tradeYear - 1}-12-31`
  return ''
}

function isDefaultPredictivePlaceholder(data: any) {
  if (!data || typeof data !== 'object') return false
  const action = String(data.action || '').toUpperCase()
  const risk = String(data.risk_level || '').toUpperCase()
  const scoreMissing = data.signal_score === null || data.signal_score === undefined || data.signal_score === ''
  const noModel = !data.model_version
  const noAsOf = !data.asof_date
  return action === 'HOLD' && risk === 'MEDIUM' && scoreMissing && noModel && noAsOf
}

function shouldPinFinancialEndDate(
  reportType: string,
  valuationEndDate: string | null | undefined,
  currentTradeDateText: string | null | undefined,
) {
  const normalizedReportType = String(reportType || '').toUpperCase().trim()
  const normalizedEndDate = String(valuationEndDate || '').trim()
  if (!normalizedEndDate) return false

  // FY and FUSION should let backend resolve latest valid anchor by design.
  if (normalizedReportType === 'FY' || normalizedReportType === 'FUSION') {
    return false
  }

  if (!['Q1', 'H1', 'Q3'].includes(normalizedReportType)) {
    return true
  }

  const expectedEndDate = inferExpectedEndDateForReportType(normalizedReportType, currentTradeDateText)
  if (!expectedEndDate) {
    return true
  }

  // If valuation snapshot period is older than expected current period, do not pin it.
  return normalizedEndDate >= expectedEndDate
}

async function fetchEarningsSignalWithFallback(
  tsCodeCandidates: string[],
  requestSeq: number,
  reportType: string,
  modelSlot: string,
  anchorMode: string,
  financialEndDate?: string | null,
) {
  let degradedFallback: { candidate: string; payload: any } | null = null

  for (const candidate of tsCodeCandidates) {
    try {
      const payload = await fetchSinglePredictiveSignalWithCache(candidate, reportType, modelSlot, anchorMode, financialEndDate)
      const data = payload?.data
      if (data && typeof data === 'object') {
        const degradeReason = String(payload?.degrade?.reason || '')
        const degradedDefault = degradeReason === 'upstream_error_default' || isDefaultPredictivePlaceholder(data)
        if (degradedDefault) {
          if (!degradedFallback) {
            degradedFallback = { candidate, payload }
          }
          continue
        }
        return { candidate, payload }
      }
    } catch {
      continue
    }
  }
  return degradedFallback
}

function normalizeServingSlotForSignal(slot: string) {
  const normalized = String(slot || '').trim().toLowerCase()
  if (normalized === 'production' || normalized === 'candidate') return normalized
  return ''
}

async function fetchValuationMethodsWithCache(tsCode: string, band: string, reportType: string, preferredVariant = '') {
  return fetchValuationMethodsWithSharedCache(String(baseURL || ''), tsCode, band, reportType, preferredVariant)
}

function buildPredictiveSignalCacheKey(
  tsCode: string,
  reportType: string,
  modelSlot: string,
  anchorMode: string,
  financialEndDate?: string | null,
) {
  return [
    String(tsCode || '').trim().toUpperCase(),
    String(reportType || '').trim().toUpperCase(),
    String(modelSlot || '').trim().toLowerCase(),
    String(anchorMode || '').trim().toLowerCase(),
    String(financialEndDate || '').trim(),
  ].join('|')
}

async function fetchSinglePredictiveSignalWithCache(
  tsCode: string,
  reportType: string,
  modelSlot: string,
  anchorMode: string,
  financialEndDate?: string | null,
) {
  const key = buildPredictiveSignalCacheKey(tsCode, reportType, modelSlot, anchorMode, financialEndDate)
  if (predictiveSignalCache.has(key)) {
    return predictiveSignalCache.get(key)
  }
  const pending = predictiveSignalPending.get(key)
  if (pending) {
    return pending
  }

  const encoded = encodeURIComponent(tsCode)
  const normalizedReportType = normalizeEarningsReportTypeForSignal(reportType)
  const normalizedServingSlot = normalizeServingSlotForSignal(modelSlot)
  const reportTypeQuery = normalizedReportType
    ? `&report_type=${encodeURIComponent(normalizedReportType)}`
    : ''
  const servingSlotQuery = normalizedServingSlot
    ? `&serving_slot=${encodeURIComponent(normalizedServingSlot)}`
    : ''
  const normalizedAnchorMode = String(anchorMode || '').trim().toLowerCase() === 'live' ? 'live' : 'ann'
  const anchorModeQuery = `&anchor_mode=${encodeURIComponent(normalizedAnchorMode)}`
  const normalizedFinancialEndDate = String(financialEndDate || '').trim()
  const financialEndDateQuery = normalizedFinancialEndDate && normalizedReportType && normalizedReportType !== 'FUSION'
    ? `&financial_end_date=${encodeURIComponent(normalizedFinancialEndDate)}`
    : ''
  const url = `${baseURL}/earnings/signal/${encoded}/?ts_code=${encoded}${reportTypeQuery}${servingSlotQuery}${anchorModeQuery}${financialEndDateQuery}`

  const task = axios.get(url)
    .then((resp) => {
      const payload = resp?.data
      if (payload && typeof payload === 'object') {
        predictiveSignalCache.set(key, payload)
      }
      return payload
    })
    .finally(() => {
      predictiveSignalPending.delete(key)
    })
  predictiveSignalPending.set(key, task)
  return task
}

function applyEarningsSignalResponse(
  earningsResp: any,
  normalizedTsCode: string,
  canonicalTsCode: string,
  valuationTsCode: string,
) {
  const earningsData = earningsResp?.payload?.data
  if (earningsData && typeof earningsData === 'object') {
    const returnedTsCode = String(earningsData.ts_code || '').trim().toUpperCase()
    if (returnedTsCode && !isSameTsCode(valuationTsCode || canonicalTsCode || normalizedTsCode, returnedTsCode)) {
      earningsSignal.value = null
      earningsDegradeReason.value = 'ts_code_mismatch'
      return
    }
    earningsSignal.value = buildEarningsSignalModel(
      earningsData,
      normalizedTsCode,
      String(selectedEarningsReportType.value || 'UNKNOWN').toUpperCase(),
    )
    earningsDegradeReason.value = String(earningsResp?.payload?.degrade?.reason || '')
  } else {
    earningsSignal.value = null
    earningsDegradeReason.value = 'signal_unavailable'
  }
}

function buildEarningsSignalModel(earningsData: any, fallbackTsCode: string, fallbackReportType: string): EarningsSignal {
  return {
    ts_code: String(earningsData.ts_code || fallbackTsCode),
    report_type: String(earningsData.report_type || fallbackReportType || 'UNKNOWN').toUpperCase(),
    anchor_mode: earningsData.anchor_mode ? String(earningsData.anchor_mode).toUpperCase() : null,
    signal_score: toNullableNumber(earningsData.signal_score),
    action: String(earningsData.action || ''),
    risk_level: String(earningsData.risk_level || ''),
    target_price: toNullableNumber(earningsData.target_price),
    target_price_raw: toNullableNumber(earningsData.target_price_raw),
    target_price_optimized: toNullableNumber(earningsData.target_price_optimized),
    target_market_cap: toNullableNumber(earningsData.target_market_cap),
    target_market_cap_raw: toNullableNumber(earningsData.target_market_cap_raw),
    target_market_cap_optimized: toNullableNumber(earningsData.target_market_cap_optimized),
    target_return_pct: toNullableNumber(earningsData.target_return_pct),
    target_return_pct_raw: toNullableNumber(earningsData.target_return_pct_raw),
    target_return_pct_anchor: toNullableNumber(earningsData.target_return_pct_anchor),
    target_return_pct_anchor_optimized: toNullableNumber(earningsData.target_return_pct_anchor_optimized),
    target_return_pct_optimized: toNullableNumber(earningsData.target_return_pct_optimized),
    target_price_low: toNullableNumber(earningsData.target_price_low),
    target_price_high: toNullableNumber(earningsData.target_price_high),
    target_price_low_raw: toNullableNumber(earningsData.target_price_low_raw),
    target_price_high_raw: toNullableNumber(earningsData.target_price_high_raw),
    target_price_low_optimized: toNullableNumber(earningsData.target_price_low_optimized),
    target_price_high_optimized: toNullableNumber(earningsData.target_price_high_optimized),
    target_market_cap_low: toNullableNumber(earningsData.target_market_cap_low),
    target_market_cap_high: toNullableNumber(earningsData.target_market_cap_high),
    target_market_cap_low_raw: toNullableNumber(earningsData.target_market_cap_low_raw),
    target_market_cap_high_raw: toNullableNumber(earningsData.target_market_cap_high_raw),
    target_market_cap_low_optimized: toNullableNumber(earningsData.target_market_cap_low_optimized),
    target_market_cap_high_optimized: toNullableNumber(earningsData.target_market_cap_high_optimized),
    target_return_low_pct: toNullableNumber(earningsData.target_return_low_pct),
    target_return_high_pct: toNullableNumber(earningsData.target_return_high_pct),
    target_return_low_pct_raw: toNullableNumber(earningsData.target_return_low_pct_raw),
    target_return_high_pct_raw: toNullableNumber(earningsData.target_return_high_pct_raw),
    target_return_low_pct_anchor: toNullableNumber(earningsData.target_return_low_pct_anchor),
    target_return_high_pct_anchor: toNullableNumber(earningsData.target_return_high_pct_anchor),
    target_return_low_pct_anchor_optimized: toNullableNumber(earningsData.target_return_low_pct_anchor_optimized),
    target_return_high_pct_anchor_optimized: toNullableNumber(earningsData.target_return_high_pct_anchor_optimized),
    target_return_low_pct_optimized: toNullableNumber(earningsData.target_return_low_pct_optimized),
    target_return_high_pct_optimized: toNullableNumber(earningsData.target_return_high_pct_optimized),
    model_version: earningsData.model_version ? String(earningsData.model_version) : null,
    asof_date: earningsData.asof_date ? String(earningsData.asof_date) : null,
    anchor_trade_date: earningsData.anchor_trade_date ? String(earningsData.anchor_trade_date) : null,
    anchor_close_price: toNullableNumber(earningsData.anchor_close_price),
    financial_fiscal_year: toNullableNumber(earningsData.financial_fiscal_year),
    financial_ann_date: earningsData.financial_ann_date ? String(earningsData.financial_ann_date) : null,
    market_regime: earningsData.market_regime ? String(earningsData.market_regime).toUpperCase() : null,
    quantitative_target_components:
      earningsData.quantitative_target_components && typeof earningsData.quantitative_target_components === 'object'
        ? {
          base_return_pct: toNullableNumber(earningsData.quantitative_target_components.base_return_pct),
          prob_return_pct: toNullableNumber(earningsData.quantitative_target_components.prob_return_pct),
          earnings_return_pct: toNullableNumber(earningsData.quantitative_target_components.earnings_return_pct),
          industry_return_pct: toNullableNumber(earningsData.quantitative_target_components.industry_return_pct),
          max_abs_return_cap_pct: toNullableNumber(earningsData.quantitative_target_components.max_abs_return_cap_pct),
          market_regime: earningsData.quantitative_target_components.market_regime
            ? String(earningsData.quantitative_target_components.market_regime).toUpperCase()
            : null,
          market_overall_adjustment:
            earningsData.quantitative_target_components.market_overall_adjustment
              && typeof earningsData.quantitative_target_components.market_overall_adjustment === 'object'
              ? {
                enabled: Boolean(earningsData.quantitative_target_components.market_overall_adjustment.enabled),
                state: earningsData.quantitative_target_components.market_overall_adjustment.state
                  ? String(earningsData.quantitative_target_components.market_overall_adjustment.state)
                  : null,
                score: toNullableNumber(earningsData.quantitative_target_components.market_overall_adjustment.score),
                multiplier: toNullableNumber(earningsData.quantitative_target_components.market_overall_adjustment.multiplier),
                asof_trade_date: earningsData.quantitative_target_components.market_overall_adjustment.asof_trade_date
                  ? String(earningsData.quantitative_target_components.market_overall_adjustment.asof_trade_date)
                  : null,
              }
              : null,
        }
        : null,
    predictive_tiered_template:
      earningsData.predictive_tiered_template && typeof earningsData.predictive_tiered_template === 'object'
        ? {
          styleKey: String(earningsData.predictive_tiered_template.styleKey || 'balanced') as PredictiveTieredTemplate['styleKey'],
          styleLabel: String(earningsData.predictive_tiered_template.styleLabel || '均衡可信度'),
          reliabilityScore: Number(toNullableNumber(earningsData.predictive_tiered_template.reliabilityScore) ?? 50),
          reasons: Array.isArray(earningsData.predictive_tiered_template.reasons)
            ? earningsData.predictive_tiered_template.reasons.map((item: any) => String(item))
            : [],
          tiers: {
            conservative: {
              targetPrice: toNullableNumber(earningsData.predictive_tiered_template?.tiers?.conservative?.targetPrice),
              expectedReturnPct: toNullableNumber(earningsData.predictive_tiered_template?.tiers?.conservative?.expectedReturnPct),
              rangeLower: toNullableNumber(earningsData.predictive_tiered_template?.tiers?.conservative?.rangeLower),
              rangeUpper: toNullableNumber(earningsData.predictive_tiered_template?.tiers?.conservative?.rangeUpper),
            },
            balanced: {
              targetPrice: toNullableNumber(earningsData.predictive_tiered_template?.tiers?.balanced?.targetPrice),
              expectedReturnPct: toNullableNumber(earningsData.predictive_tiered_template?.tiers?.balanced?.expectedReturnPct),
              rangeLower: toNullableNumber(earningsData.predictive_tiered_template?.tiers?.balanced?.rangeLower),
              rangeUpper: toNullableNumber(earningsData.predictive_tiered_template?.tiers?.balanced?.rangeUpper),
            },
            aggressive: {
              targetPrice: toNullableNumber(earningsData.predictive_tiered_template?.tiers?.aggressive?.targetPrice),
              expectedReturnPct: toNullableNumber(earningsData.predictive_tiered_template?.tiers?.aggressive?.expectedReturnPct),
              rangeLower: toNullableNumber(earningsData.predictive_tiered_template?.tiers?.aggressive?.rangeLower),
              rangeUpper: toNullableNumber(earningsData.predictive_tiered_template?.tiers?.aggressive?.rangeUpper),
            },
          },
          positionRange: String(earningsData.predictive_tiered_template.positionRange || '35%-55%'),
          positionMessage: String(earningsData.predictive_tiered_template.positionMessage || '位于平衡区间，维持中性仓位。'),
        }
        : null,
  }
}

async function fetchPredictiveCompareSignal(
  tsCode: string,
  reportType: string,
  modelSlot: string,
  financialEndDate?: string | null,
) {
  const encoded = encodeURIComponent(tsCode)
  const normalizedReportType = normalizeEarningsReportTypeForSignal(reportType)
  const normalizedServingSlot = normalizeServingSlotForSignal(modelSlot)
  const reportTypeQuery = normalizedReportType
    ? `&report_type=${encodeURIComponent(normalizedReportType)}`
    : ''
  const servingSlotQuery = normalizedServingSlot
    ? `&serving_slot=${encodeURIComponent(normalizedServingSlot)}`
    : ''
  const normalizedFinancialEndDate = String(financialEndDate || '').trim()
  const financialEndDateQuery = normalizedFinancialEndDate && normalizedReportType && normalizedReportType !== 'FUSION'
    ? `&financial_end_date=${encodeURIComponent(normalizedFinancialEndDate)}`
    : ''

  const url = `${baseURL}/earnings/signal-compare/${encoded}/?ts_code=${encoded}${reportTypeQuery}${servingSlotQuery}&anchor_mode_latest=live&anchor_mode_report=ann${financialEndDateQuery}`
  const resp = await axios.get(url)
  const payload = resp?.data
  return payload && typeof payload === 'object' ? payload : null
}

async function fetchPredictiveSignalOnly(requestSeq = ++predictiveFetchSeq.value) {
  const normalizedTsCode = String(stockTradeStore.tsCode || '').trim().toUpperCase()
  const canonicalTsCode = toCanonicalTsCode(normalizedTsCode)
  if (!normalizedTsCode || !baseURL) {
    earningsSignal.value = null
    predictiveCompare.value = null
    earningsDegradeReason.value = ''
    predictiveFusionFallbackHit.value = false
    predictiveLoading.value = false
    return
  }

  predictiveLoading.value = true
  try {
    const valuationTsCode = ''
    const earningsTsCodeCandidates = canonicalTsCode
      ? [canonicalTsCode]
      : Array.from(new Set([normalizedTsCode, valuationTsCode].filter((code) => Boolean(code))))
    const normalizedSignalReportType = normalizeEarningsReportTypeForSignal(selectedEarningsReportType.value)
    const selectedValuationEndDateRaw = rows.value.find((item) => item.profit_report_end_date)?.profit_report_end_date || null
    const selectedValuationEndDate = shouldPinFinancialEndDate(
      normalizedSignalReportType,
      selectedValuationEndDateRaw,
      currentTradeDate.value,
    )
      ? selectedValuationEndDateRaw
      : null
    const earningsResp = await fetchEarningsSignalWithFallback(
      earningsTsCodeCandidates,
      requestSeq,
      selectedEarningsReportType.value,
      selectedPredictModelSlot.value,
      selectedPredictAnchorMode.value,
      selectedValuationEndDate,
    )
    const normalizedFusionSelection = String(selectedEarningsReportType.value || '').trim().toUpperCase()
    const fusionFallbackNeeded =
      normalizedFusionSelection === 'FUSION'
      && isDefaultPredictivePlaceholder(earningsResp?.payload?.data)
    predictiveFusionFallbackHit.value = fusionFallbackNeeded
    const effectiveEarningsResp = fusionFallbackNeeded
      ? await fetchEarningsSignalWithFallback(
        earningsTsCodeCandidates,
        requestSeq,
        'ALL',
        selectedPredictModelSlot.value,
        selectedPredictAnchorMode.value,
        null,
      )
      : earningsResp
    if (requestSeq !== predictiveFetchSeq.value || normalizedTsCode !== String(stockTradeStore.tsCode || '').trim().toUpperCase()) {
      return
    }

    applyEarningsSignalResponse(effectiveEarningsResp, normalizedTsCode, canonicalTsCode, valuationTsCode)

    try {
      const compareResp = await fetchPredictiveCompareSignal(
        canonicalTsCode || normalizedTsCode,
        selectedEarningsReportType.value,
        selectedPredictModelSlot.value,
        selectedValuationEndDate,
      )
      const compareData = compareResp?.data
      predictiveCompare.value = compareData && typeof compareData === 'object'
        ? (compareData as PredictiveComparePayload)
        : null
      const normalizedAnchorMode = String(selectedPredictAnchorMode.value || '').trim().toLowerCase()
      const comparePayloadAny = predictiveCompare.value as any
      const reportAnchorRaw = comparePayloadAny?.report_anchor_view || comparePayloadAny?.report_view
      const latestRaw = comparePayloadAny?.latest_view
      const preferredRaw = latestRaw || reportAnchorRaw
      // For ann mode, keep primary signal from /earnings/signal to avoid
      // compare payload accidentally downgrading to an older report period.
      if (normalizedAnchorMode === 'live' && preferredRaw && typeof preferredRaw === 'object') {
        earningsSignal.value = buildEarningsSignalModel(
          preferredRaw,
          normalizedTsCode,
          String(selectedEarningsReportType.value || 'UNKNOWN').toUpperCase(),
        )
      }
    } catch {
      predictiveCompare.value = null
    }

    predictiveLastRefreshAt.value = Date.now()
  } catch (error) {
    if (requestSeq !== predictiveFetchSeq.value || normalizedTsCode !== String(stockTradeStore.tsCode || '').trim().toUpperCase()) {
      return
    }
    earningsSignal.value = null
    predictiveCompare.value = null
    earningsDegradeReason.value = ''
    predictiveFusionFallbackHit.value = false
    console.error('Failed to fetch predictive valuation section:', error)
  } finally {
    if (requestSeq === predictiveFetchSeq.value) {
      predictiveLoading.value = false
    }
  }
}

function statusLabel(status: string) {
  if (status === 'under') return '低估'
  if (status === 'over') return '高估'
  if (status === 'fair') return '合理'
  return '-'
}

function statusTagType(status: string) {
  if (status === 'under') return 'danger'
  if (status === 'over') return 'success'
  return 'info'
}

function earningsActionTagType(action: string | undefined) {
  const normalized = String(action || '').toUpperCase()
  if (normalized === 'BUY' || normalized === 'B') return 'danger'
  if (normalized === 'SELL' || normalized === 'SELL_PART' || normalized === 'S') return 'success'
  return 'info'
}

function earningsActionLabel(action: string | undefined) {
  const normalized = String(action || '').toUpperCase()
  if (normalized === 'BUY' || normalized === 'B') return '买'
  if (normalized === 'SELL' || normalized === 'SELL_PART' || normalized === 'S') return '卖'
  if (normalized === 'HOLD' || normalized === 'H') return '持'
  return '-'
}

function earningsRiskTagType(riskLevel: string | undefined) {
  const normalized = String(riskLevel || '').toUpperCase()
  if (normalized === 'HIGH' || normalized === 'H') return 'danger'
  if (normalized === 'LOW' || normalized === 'L') return 'success'
  return 'warning'
}

function valuationRiskTagType(riskLevel: string | undefined) {
  const normalized = String(riskLevel || '').toUpperCase()
  if (normalized === 'HIGH' || normalized === 'H') return 'danger'
  if (normalized === 'LOW' || normalized === 'L') return 'success'
  return 'warning'
}

function riskLevelLabel(riskLevel: string | undefined) {
  const normalized = String(riskLevel || '').toUpperCase()
  if (normalized === 'LOW' || normalized === 'L') return '低'
  if (normalized === 'MEDIUM' || normalized === 'M') return '中'
  if (normalized === 'HIGH' || normalized === 'H') return '高'
  return '-'
}

const earningsSignalMeta = computed(() => {
  if (!earningsSignal.value) {
    return '-'
  }
  const parts: string[] = []
  if (earningsSignal.value.model_version) {
    parts.push(`模型 ${earningsSignal.value.model_version}`)
  }
  if (earningsSignal.value.report_type) {
    parts.push(`报告 ${earningsSignal.value.report_type}`)
  }
  if (earningsSignal.value.financial_fiscal_year) {
    parts.push(`信号财年 ${earningsSignal.value.financial_fiscal_year}`)
  }
  if (earningsSignal.value.financial_ann_date) {
    parts.push(`信号公告日 ${formatDateOnly(earningsSignal.value.financial_ann_date)}`)
  }
  if (earningsSignal.value.asof_date) {
    parts.push(`信号截面 ${earningsSignal.value.asof_date}`)
  }
  if (earningsDegradeReason.value) {
    parts.push(`降级 ${earningsDegradeReason.value}`)
  }
  return parts.join(' | ') || '-'
})

const earningsSignalQuantMeta = computed(() => {
  const signal = earningsSignal.value
  if (!signal) {
    return '-'
  }
  const components = signal.quantitative_target_components || {}
  const regime = String(signal.market_regime || components.market_regime || '').toUpperCase()
  const capPct = toNullableNumber(components.max_abs_return_cap_pct)
  const basePct = toNullableNumber(components.base_return_pct)
  const probPct = toNullableNumber(components.prob_return_pct)
  const earnPct = toNullableNumber(components.earnings_return_pct)
  const industryPct = toNullableNumber(components.industry_return_pct)

  const parts: string[] = []
  if (regime) {
    parts.push(`市场 ${regime}`)
  }
  if (capPct !== null) {
    parts.push(`上限 ${formatGap(capPct)}%`)
  }

  const detailParts: string[] = []
  if (basePct !== null) detailParts.push(`base ${formatGap(basePct)}%`)
  if (probPct !== null) detailParts.push(`prob ${formatGap(probPct)}%`)
  if (earnPct !== null) detailParts.push(`earn ${formatGap(earnPct)}%`)
  if (industryPct !== null) detailParts.push(`industry ${formatGap(industryPct)}%`)
  const marketOverallAdjustment = components.market_overall_adjustment
  if (marketOverallAdjustment && typeof marketOverallAdjustment === 'object') {
    const stateText = String(marketOverallAdjustment.state || '').trim().toLowerCase()
    const multiplier = toNullableNumber(marketOverallAdjustment.multiplier)
    if (stateText) detailParts.push(`market ${stateText}`)
    if (multiplier !== null) detailParts.push(`x${formatMultiplier(multiplier)}`)
  }
  if (detailParts.length) {
    parts.push(detailParts.join(' / '))
  }

  return parts.join(' | ') || '-'
})

const predictiveRefreshMeta = computed(() => {
  if (predictiveLoading.value) {
    return '刷新中...'
  }
  if (!predictiveLastRefreshAt.value) {
    return '未刷新'
  }
  const suffix = predictiveFusionFallbackHit.value ? ' | Fusion回退' : ''
  return `更新于 ${formatTime(predictiveLastRefreshAt.value)}${suffix}`
})

const predictiveContextLabel = computed(() => {
  const reportTypeRaw = String(effectiveValuationReportType.value || selectedEarningsReportType.value || 'Q1').toUpperCase()
  const reportType = reportTypeRaw === 'ANNUAL' ? 'FY' : reportTypeRaw
  const anchorModeRaw = String(earningsSignal.value?.anchor_mode || selectedPredictAnchorMode.value || 'ann').trim().toUpperCase()
  const anchorLabel = anchorModeRaw === 'LIVE' ? '最新时点' : '公告时点'
  const slotRaw = String(selectedPredictModelSlot.value || 'production').trim().toLowerCase()
  let sourceLabel = '生产模型'
  if (slotRaw === 'production') {
    sourceLabel = '生产模型'
  } else if (slotRaw === 'candidate') {
    sourceLabel = '候选模型'
  }
  return `预测口径 ${reportType} | ${anchorLabel} | ${sourceLabel}`
})

const predictiveLatestView = computed<EarningsSignal | null>(() => {
  const anchorMode = String(selectedPredictAnchorMode.value || '').trim().toLowerCase()
  if (anchorMode === 'ann') {
    return earningsSignal.value
  }
  const latestRaw = predictiveCompare.value?.latest_view
  if (latestRaw && typeof latestRaw === 'object') {
    return buildEarningsSignalModel(
      latestRaw,
      String(stockTradeStore.tsCode || '').trim().toUpperCase(),
      String(selectedEarningsReportType.value || 'UNKNOWN').toUpperCase(),
    )
  }
  return earningsSignal.value
})

const predictiveReportAnchorView = computed<EarningsSignal | null>(() => {
  const anchorMode = String(selectedPredictAnchorMode.value || '').trim().toLowerCase()
  if (anchorMode === 'ann') {
    return earningsSignal.value
  }
  const anchorRaw = predictiveCompare.value?.report_anchor_view
  if (anchorRaw && typeof anchorRaw === 'object') {
    return buildEarningsSignalModel(
      anchorRaw,
      String(stockTradeStore.tsCode || '').trim().toUpperCase(),
      String(selectedEarningsReportType.value || 'UNKNOWN').toUpperCase(),
    )
  }
  return earningsSignal.value
})

const predictiveCompareSummary = computed<PredictiveCompareSummary | null>(() => {
  const summary = predictiveCompare.value?.compare_summary
  if (summary && typeof summary === 'object') {
    return {
      score_delta: toNullableNumber((summary as any).score_delta),
      target_price_delta_pct: toNullableNumber((summary as any).target_price_delta_pct),
      action_changed: Boolean((summary as any).action_changed),
      confidence_hint: String((summary as any).confidence_hint || 'stable'),
    }
  }
  return null
})

function resolvePredictiveCoreTargetPrice(signal: EarningsSignal | null | undefined) {
  return toNullableNumber(signal?.target_price_raw ?? signal?.target_price)
}

function resolvePredictiveCoreTargetLow(signal: EarningsSignal | null | undefined) {
  return toNullableNumber(signal?.target_price_low_raw ?? signal?.target_price_low ?? signal?.target_price_raw ?? signal?.target_price)
}

function resolvePredictiveCoreTargetHigh(signal: EarningsSignal | null | undefined) {
  return toNullableNumber(signal?.target_price_high_raw ?? signal?.target_price_high ?? signal?.target_price_raw ?? signal?.target_price)
}

function resolvePredictiveCoreReturnPct(signal: EarningsSignal | null | undefined) {
  return toNullableNumber(signal?.target_return_pct_raw ?? signal?.target_return_pct)
}

const predictiveTieredTemplate = computed<PredictiveTieredTemplate | null>(() => {
  const signal = earningsSignal.value
  const backendTemplate = signal?.predictive_tiered_template
  if (backendTemplate && backendTemplate.tiers) {
    return backendTemplate
  }

  const cp = toNullableNumber(currentPrice.value)
  const low = toNullableNumber(signal?.target_price_low_raw ?? signal?.target_price_low ?? signal?.target_price_raw ?? signal?.target_price)
  const high = toNullableNumber(signal?.target_price_high_raw ?? signal?.target_price_high ?? signal?.target_price_raw ?? signal?.target_price)
  if (!signal || cp === null || cp <= 0 || low === null || high === null || high <= 0 || low <= 0) {
    return null
  }

  const lo = Math.min(low, high)
  const hi = Math.max(low, high)
  const signalScore = Math.max(0, Math.min(100, toNullableNumber(signal.signal_score) ?? 50))
  const riskNormalized = String(signal.risk_level || '').trim().toUpperCase()
  const riskPenalty = riskNormalized === 'HIGH' || riskNormalized === 'H' ? 18 : riskNormalized === 'MEDIUM' || riskNormalized === 'M' ? 8 : 0
  const dispersion = (hi - lo) / cp
  const dispersionPenalty = Math.max(0, Math.min(25, dispersion * 60))

  const asofText = String(signal.asof_date || signal.anchor_trade_date || '').trim()
  const refText = String(currentTradeDate.value || asofText).trim()
  const asofDate = asofText ? new Date(asofText) : null
  const refDate = refText ? new Date(refText) : null
  let freshnessPenalty = 0
  if (asofDate && refDate && Number.isFinite(asofDate.getTime()) && Number.isFinite(refDate.getTime())) {
    const staleDays = Math.max(0, Math.floor((refDate.getTime() - asofDate.getTime()) / 86400000))
    freshnessPenalty = Math.max(0, Math.min(20, staleDays / 8))
  }

  const reliabilityScore = Math.max(5, Math.min(95, signalScore - riskPenalty - dispersionPenalty - freshnessPenalty))
  let styleKey: 'high_confidence' | 'balanced' | 'low_confidence' = 'balanced'
  let styleLabel = '均衡可信度'

  const industryCodeCandidates = _resolvePredictiveIndustryCodeCandidates()
  const resolvedIndustryCode = industryCodeCandidates[0] || ''
  const hasIndustryCode = Boolean(resolvedIndustryCode)
  const traditionalStyleKey = String(traditionalTieredTemplate.value?.style_key || '').trim().toLowerCase()
  let industryRegime = _resolvePredictiveRegimeFromTraditionalStyleKey(traditionalStyleKey)
  let industryRegimeReason = ''
  if (industryRegime) {
    industryRegimeReason = `traditional_style_key=${traditionalStyleKey}`
  } else {
    industryRegime = _resolvePredictiveIndustryRegime(resolvedIndustryCode)
    industryRegimeReason = industryRegime ? `industry_code=${resolvedIndustryCode}` : (hasIndustryCode ? 'fallback_balanced' : 'none')
  }

  if (industryRegime === 'growth') {
    styleKey = 'high_confidence'
    styleLabel = '成长景气'
  } else if (industryRegime === 'cyclical') {
    styleKey = 'balanced'
    styleLabel = '周期风格'
  } else if (industryRegime === 'defensive') {
    styleKey = 'low_confidence'
    styleLabel = '稳健防守'
  } else if (hasIndustryCode) {
    // 有行业编码但未命中时不返回none，统一回落到balanced。
    styleKey = 'balanced'
    styleLabel = '均衡可信度'
  } else if (reliabilityScore >= 75) {
    styleKey = 'high_confidence'
    styleLabel = '高可信度'
  } else if (reliabilityScore < 50) {
    styleKey = 'low_confidence'
    styleLabel = '谨慎可信度'
  }

  const mix = styleKey === 'high_confidence' ? 0.62 : styleKey === 'low_confidence' ? 0.38 : 0.5
  const conservativeTarget = lo * 0.86 + hi * 0.14
  const balancedTarget = lo * (1 - mix) + hi * mix
  const aggressiveTarget = lo * 0.2 + hi * 0.8

  const buildTier = (targetPrice: number, lowerMul: number, upperMul: number): PredictiveTierItem => ({
    targetPrice: Number(targetPrice.toFixed(4)),
    expectedReturnPct: Number((((targetPrice / cp) - 1.0) * 100.0).toFixed(2)),
    rangeLower: Number((targetPrice * lowerMul).toFixed(4)),
    rangeUpper: Number((targetPrice * upperMul).toFixed(4)),
  })

  const tiers = {
    conservative: buildTier(conservativeTarget, 0.95, 1.04),
    balanced: buildTier(balancedTarget, 0.95, 1.08),
    aggressive: buildTier(aggressiveTarget, 0.95, 1.15),
  }

  let positionRange = '35%-55%'
  let positionMessage = '位于平衡区间，维持中性仓位。'
  if (cp < tiers.conservative.rangeLower) {
    positionRange = styleKey === 'high_confidence' ? '65%-80%' : '55%-70%'
    positionMessage = '低于风控区间下沿，可分批提高仓位。'
  } else if (cp < tiers.balanced.rangeLower) {
    positionRange = styleKey === 'low_confidence' ? '40%-55%' : '45%-65%'
    positionMessage = '低于平衡区间，可逐步加仓。'
  } else if (cp > tiers.aggressive.rangeUpper) {
    positionRange = styleKey === 'high_confidence' ? '20%-35%' : '15%-30%'
    positionMessage = '高于进攻区间上沿，建议偏防守仓位。'
  } else if (cp > tiers.balanced.rangeUpper) {
    positionRange = '25%-40%'
    positionMessage = '处于偏高区间，可逐步降低仓位。'
  }

  return {
    styleKey,
    styleLabel,
    reliabilityScore: Number(reliabilityScore.toFixed(2)),
    reasons: [
      industryRegime ? `industry_regime=${industryRegime}` : (hasIndustryCode ? 'industry_regime=fallback_balanced' : 'industry_regime=none'),
      `industry_regime_reason=${industryRegimeReason}`,
      resolvedIndustryCode ? `industry_code=${resolvedIndustryCode}` : 'industry_code=-',
      `signal=${signalScore.toFixed(1)}`,
      `risk=${riskNormalized || '-'}`,
      `dispersion=${(dispersion * 100).toFixed(2)}%`,
      `fresh_penalty=${freshnessPenalty.toFixed(1)}`,
    ],
    tiers,
    positionRange,
    positionMessage,
  }
})

const predictiveTierSummaryText = computed(() => {
  const payload = predictiveTieredTemplate.value
  if (!payload) {
    return '预测三档模板暂不可用'
  }
  return `${payload.styleLabel} | 平衡目标 ${formatPrice(payload.tiers.balanced.targetPrice)} | 建议仓位 ${payload.positionRange}`
})

const marketOverallMultiplierForDisplay = computed(() => {
  const components = earningsSignal.value?.quantitative_target_components
  const adjustment = components?.market_overall_adjustment
  return toNullableNumber(adjustment?.multiplier)
})

const valuationReportMeta = computed(() => {
  const row = rows.value.find((item) => item.profit_report_end_date || item.profit_report_ann_date || item.profit_report_type)
  if (!row) {
    return '-'
  }
  const parts: string[] = []
  const profitSource = String(row.profit_data_source || '').toLowerCase()
  if (profitSource.startsWith('express')) {
    parts.push('口径 快报')
  }
  const reportType = String(row.profit_report_type || '').toUpperCase()
  if (reportType) {
    parts.push(`报告 ${reportType === 'ANNUAL' ? 'FY' : reportType}`)
  }
  if (row.profit_report_end_date) {
    parts.push(`财报期 ${row.profit_report_end_date}`)
  }
  if (row.profit_report_ann_date) {
    parts.push(`公告日 ${row.profit_report_ann_date}`)
  }
  return parts.join(' | ') || '-'
})

const traditionalOptimizationMetaText = computed(() => {
  const meta = summaryOptimized.value?.traditional_optimization_meta
  if (!meta?.enabled) {
    return ''
  }
  const parts: string[] = []
  if (Number.isFinite(Number(meta.method_count))) {
    parts.push(`方法数 ${Number(meta.method_count)}`)
  }
  if (Number.isFinite(Number(meta.dispersion_ratio))) {
    parts.push(`分歧 ${Number(meta.dispersion_ratio).toFixed(2)}`)
  }
  if (Number.isFinite(Number(meta.reliability_weight))) {
    parts.push(`可靠度 ${Number(meta.reliability_weight).toFixed(2)}`)
  }
  return parts.join(' | ')
})

const effectiveValuationReportType = computed(() => {
  const selected = String(selectedEarningsReportType.value || '').toUpperCase()
  if (selected === 'FUSION') {
    return String(lastValuationReportType.value || 'FY').toUpperCase()
  }
  return selected
})

const activeCorporateActionImpact = computed<CorporateActionImpact | null>(() => {
  const impacted = rows.value.find((item) => item.corporate_action_impact?.impact_detected)
  return impacted?.corporate_action_impact || null
})

const corporateActionMeta = computed(() => {
  const impact = activeCorporateActionImpact.value
  if (!impact) return '-'
  const evt = impact.latest_dividend_event || {}
  const parts: string[] = []
  if (evt.ex_date) parts.push(`除权日 ${evt.ex_date}`)
  if (evt.record_date) parts.push(`股权登记日 ${evt.record_date}`)
  if (Number.isFinite(Number(evt.stock_distribution_ratio))) {
    parts.push(`送转比例 ${Number(evt.stock_distribution_ratio).toFixed(2)}`)
  }
  if (Number.isFinite(Number(currentTotalShare.value))) {
    parts.push(`当前总股本 ${Number(currentTotalShare.value).toFixed(2)}万股`)
  }
  return parts.join(' | ') || '-'
})

const traditionalFiscalStaleHint = computed(() => {
  if (loading.value) return ''
  const reportType = String(effectiveValuationReportType.value || '').toUpperCase()
  if (reportType !== 'FY' && reportType !== 'ANNUAL') return ''

  const reportRow = rows.value.find((item) => item.profit_report_end_date)
  const reportEndDate = String(reportRow?.profit_report_end_date || '').trim()
  const reportYear = Number(reportEndDate.slice(0, 4))
  if (!Number.isFinite(reportYear)) return ''

  const tradeYear = Number(String(currentTradeDate.value || '').slice(0, 4))
  const expectedFyYear = Number.isFinite(tradeYear) ? tradeYear - 1 : new Date().getFullYear() - 1
  if (reportYear >= expectedFyYear) return ''

  return `FY 口径提示：最新可用 FY 为 ${reportYear}，${expectedFyYear}FY 待正式披露。`
})

function isThresholdSensitive(gapPct: number | null | undefined) {
  const absGap = Math.abs(Number(gapPct ?? NaN))
  if (!Number.isFinite(absGap)) return false
  return absGap > 5 && absGap <= 15
}

async function fetchValuationRows(includePredictive = true) {
  const tsCode = stockTradeStore.tsCode
  const normalizedTsCode = String(tsCode || '').trim().toUpperCase()
  const canonicalTsCode = toCanonicalTsCode(normalizedTsCode)
  const requestSeq = ++fetchSeq.value
  if (!normalizedTsCode || !baseURL) {
    rows.value = []
    currentPrice.value = null
    currentTradeDate.value = ''
    currentTotalShare.value = null
    earningsSignal.value = null
    predictiveCompare.value = null
    valuationRisk.value = null
    earningsDegradeReason.value = ''
    summaryNormalized.value = emptySummary()
    summaryOptimized.value = emptySummary()
    summaryNormalizedOptimized.value = emptySummary()
    return
  }

  loading.value = true
  try {
    // Keep valuation snapshot anchor on daily data so chart timeframe switch (e.g. W) does not downgrade report period.
    const freq = 'D'
    const selectedReportType = String(selectedEarningsReportType.value || '').toUpperCase()
    const valuationReportType = userPinnedReportType.value
      ? (selectedReportType === 'FUSION'
        ? String(lastValuationReportType.value || 'FY').toUpperCase()
        : selectedReportType)
      : ''
    if (selectedReportType && selectedReportType !== 'FUSION' && selectedReportType !== '快') {
      lastValuationReportType.value = selectedReportType
    }
    const valuationTsCodeCandidates = Array.from(
      new Set([normalizedTsCode, canonicalTsCode].filter((code) => Boolean(code)))
    )
    const preferredVariant = String(stockTradeStore.preferredValuationVariant || '').trim()
    let res: any = null
    let valuationFetchError: unknown = null
    for (const candidate of valuationTsCodeCandidates) {
      try {
        const payload = await fetchValuationMethodsWithCache(candidate, bandPct.value, valuationReportType, preferredVariant)
        if (payload && typeof payload === 'object') {
          res = { data: payload }
          break
        }
      } catch (error) {
        valuationFetchError = error
      }
    }
    if (!res?.data || typeof res.data !== 'object') {
      throw valuationFetchError || new Error('valuation_methods_unavailable')
    }
    if (requestSeq !== fetchSeq.value || normalizedTsCode !== String(stockTradeStore.tsCode || '').trim().toUpperCase()) {
      return
    }
    const latestFormalReportType = normalizeQuickViewReportType(res.data?.latest_formal_report_type)
    if (!userPinnedReportType.value && latestFormalReportType && selectedEarningsReportType.value !== latestFormalReportType) {
      skipNextValuationFetch.value = true
      programmaticReportTypeSync.value = true
      selectedEarningsReportType.value = latestFormalReportType
      if (latestFormalReportType !== 'FUSION' && latestFormalReportType !== '快') {
        lastValuationReportType.value = latestFormalReportType
      }
      programmaticReportTypeSync.value = false
    }
    const variantList = Array.isArray(res.data?.valuation_variants)
      ? (res.data.valuation_variants as ValuationVariantTab[])
      : []
    const variantPayload =
      res.data?.data_by_variant && typeof res.data.data_by_variant === 'object'
        ? (res.data.data_by_variant as Record<string, ValuationMethodRow[]>)
        : {}
    const summaryPayload =
      res.data?.summary_by_variant && typeof res.data.summary_by_variant === 'object'
        ? Object.fromEntries(
          Object.entries(res.data.summary_by_variant as Record<string, unknown>).map(([variant, payload]) => [
            variant,
            resolveSummary(payload),
          ])
        )
        : {}
    const summaryPayloadNormalized =
      res.data?.summary_by_variant_normalized_to_latest_share && typeof res.data.summary_by_variant_normalized_to_latest_share === 'object'
        ? Object.fromEntries(
          Object.entries(res.data.summary_by_variant_normalized_to_latest_share as Record<string, unknown>).map(([variant, payload]) => [
            variant,
            resolveSummary(payload),
          ])
        )
        : {}
    const riskByVariant =
      res.data?.valuation_risk_by_variant && typeof res.data.valuation_risk_by_variant === 'object'
        ? (res.data.valuation_risk_by_variant as Record<string, any>)
        : {}

    variantTabs.value = variantList
    dataByVariant.value = variantPayload
    summaryByVariant.value = summaryPayload
    summaryByVariantNormalized.value = summaryPayloadNormalized
    summaryByVariantOptimized.value =
      res.data?.summary_by_variant_optimized && typeof res.data.summary_by_variant_optimized === 'object'
        ? Object.fromEntries(
          Object.entries(res.data.summary_by_variant_optimized as Record<string, unknown>).map(([variant, payload]) => [
            variant,
            resolveSummary(payload),
          ])
        )
        : {}
    summaryByVariantNormalizedOptimized.value =
      res.data?.summary_by_variant_normalized_to_latest_share_optimized && typeof res.data.summary_by_variant_normalized_to_latest_share_optimized === 'object'
        ? Object.fromEntries(
          Object.entries(res.data.summary_by_variant_normalized_to_latest_share_optimized as Record<string, unknown>).map(([variant, payload]) => [
            variant,
            resolveSummary(payload),
          ])
        )
        : {}
    traditionalTieredTemplateByVariant.value =
      res.data?.traditional_tiered_template_by_variant && typeof res.data.traditional_tiered_template_by_variant === 'object'
        ? (res.data.traditional_tiered_template_by_variant as Record<string, TraditionalTieredTemplate>)
        : {}

    const resolvedActive = String(
      res.data?.active_valuation_variant ||
      variantList?.[0]?.valuation_variant ||
      'default'
    )
    activeVariant.value = resolvedActive

    const resolvedRows = variantPayload[resolvedActive]
    rows.value = Array.isArray(resolvedRows)
      ? resolvedRows
      : ((res.data?.data || []) as ValuationMethodRow[])
    const fetchedCurrentPrice = toNullableNumber(res.data?.current_price)
    currentPrice.value = fetchedCurrentPrice
    currentTradeDate.value = String(res.data?.current_trade_date || '')
    currentTotalShare.value = Number.isFinite(Number(res.data?.current_total_share)) ? Number(res.data?.current_total_share) : null
    if (fetchedCurrentPrice !== null) {
      // Keep top header price in sync even when trend chart has not populated store.close yet.
      stockTradeStore.setClose(fetchedCurrentPrice)
    }
    summary.value = summaryPayload[resolvedActive] || resolveSummary(res.data?.summary)
    summaryNormalized.value = summaryPayloadNormalized[resolvedActive] || resolveSummary(res.data?.summary_normalized_to_latest_share)
    summaryOptimized.value = summaryByVariantOptimized.value[resolvedActive] || resolveSummary(res.data?.summary_optimized)
    summaryNormalizedOptimized.value = summaryByVariantNormalizedOptimized.value[resolvedActive] || resolveSummary(res.data?.summary_normalized_to_latest_share_optimized)
    const resolvedVariantRows = Array.isArray(resolvedRows)
      ? (resolvedRows as ValuationMethodRow[])
      : ((res.data?.data || []) as ValuationMethodRow[])
    topTraditionalTieredTemplate.value =
      (res.data?.traditional_tiered_template as TraditionalTieredTemplate) || null
    traditionalTieredTemplate.value = resolveTraditionalTemplatePriority(
      topTraditionalTieredTemplate.value,
      traditionalTieredTemplateByVariant.value,
      resolvedActive,
      resolvedVariantRows,
      summaryPayload[resolvedActive] || resolveSummary(res.data?.summary),
      fetchedCurrentPrice ?? stockTradeStore.close,
    )
    const activeRisk = riskByVariant[resolvedActive] || res.data?.valuation_risk || null
    valuationRisk.value = activeRisk
      ? {
        risk_level: String(activeRisk.risk_level || ''),
        risk_score: Number.isFinite(Number(activeRisk.risk_score)) ? Number(activeRisk.risk_score) : null,
        summary: activeRisk.summary ? String(activeRisk.summary) : null,
      }
      : null

    if (includePredictive) {
      // Trigger predictive fetch asynchronously so traditional valuation can render immediately.
      fetchPredictiveSignalOnly()
    }
  } catch (error) {
    if (requestSeq !== fetchSeq.value || tsCode !== stockTradeStore.tsCode) {
      return
    }
    rows.value = []
    dataByVariant.value = {}
    summaryByVariant.value = {}
    summaryByVariantNormalized.value = {}
    summaryByVariantOptimized.value = {}
    summaryByVariantNormalizedOptimized.value = {}
    traditionalTieredTemplateByVariant.value = {}
    variantTabs.value = []
    activeVariant.value = 'default'
    currentPrice.value = null
    currentTradeDate.value = ''
    currentTotalShare.value = null
    summary.value = emptySummary()
    summaryNormalized.value = emptySummary()
    summaryOptimized.value = emptySummary()
    summaryNormalizedOptimized.value = emptySummary()
    topTraditionalTieredTemplate.value = null
    traditionalTieredTemplate.value = null
    earningsSignal.value = null
    predictiveCompare.value = null
    valuationRisk.value = null
    earningsDegradeReason.value = ''
    console.error('Failed to fetch valuation quick view:', error)
  } finally {
    if (requestSeq === fetchSeq.value) {
      loading.value = false
    }
  }
}

function onUserReportTypeChange() {
  if (programmaticReportTypeSync.value) {
    return
  }
  userPinnedReportType.value = true
  // Guard against stale auto-sync skip flag swallowing the first manual switch.
  skipNextValuationFetch.value = false
}

watch(
  [() => stockTradeStore.tsCode, () => selectedEarningsReportType.value],
  ([newTsCode, newReportType], [oldTsCode, oldReportType]) => {
    const normalizedNewTsCode = String(newTsCode || '').trim().toUpperCase()
    const normalizedOldTsCode = String(oldTsCode || '').trim().toUpperCase()
    const normalizedNewReportType = String(newReportType || '').trim().toUpperCase()
    const normalizedOldReportType = String(oldReportType || '').trim().toUpperCase()

    if (normalizedNewTsCode !== normalizedOldTsCode) {
      // Reset pin state before fetching for a newly selected stock.
      userPinnedReportType.value = false
    }

    if (
      normalizedNewReportType !== normalizedOldReportType
      && !programmaticReportTypeSync.value
    ) {
      // Ensure the first manual report-type switch uses explicit report_type.
      userPinnedReportType.value = true
      skipNextValuationFetch.value = false
    }

    if (skipNextValuationFetch.value) {
      skipNextValuationFetch.value = false
      return
    }
    fetchValuationRows()
  }
)

watch(
  () => bandPct.value,
  () => {
    fetchValuationRows(false)
  }
)

watch(
  () => stockTradeStore.preferredValuationVariant,
  () => {
    if (!stockTradeStore.tsCode) {
      return
    }
    fetchValuationRows(false)
  }
)

watch(
  () => selectedPredictModelSlot.value,
  () => {
    fetchPredictiveSignalOnly()
  }
)

watch(
  () => variantTabs.value.length,
  (length) => {
    // Multi-variant mode defaults to collapsed; single/default mode keeps table expanded.
    variantTableExpanded.value = length > 1 ? false : true
  },
  { immediate: true }
)

watch(
  [() => stockTradeStore.tsCode, () => traditionalTieredTemplate.value],
  () => {
    syncTraditionalTriggerLinesToStore()
  },
  { immediate: true }
)

onMounted(() => {
  selectedPredictAnchorMode.value = 'ann'
  fetchValuationRows()
})
</script>

<style scoped>
:deep(.embedded-valuation-card .el-card__header) {
  padding: 10px 12px 8px;
}

:deep(.embedded-valuation-card .el-card__body) {
  padding: 0 0 2px;
}

.valuation-block {
  padding: 10px;
  border-radius: 8px;
  font-size: 12px;
  margin-bottom: 10px;
  border: 1px solid #dbeafe;
}

.valuation-block-traditional {
  background: linear-gradient(180deg, #f8fbff 0%, #f3f7ff 100%);
}

.valuation-block-predictive {
  background: linear-gradient(180deg, #f6fef9 0%, #eefcf3 100%);
  border-color: #ccebd8;
}

.holding-summary-card {
  margin-bottom: 10px;
  border: 1px solid #c7d2fe;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(255, 251, 235, 0.95) 0%, rgba(239, 246, 255, 0.98) 100%);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
}

.holding-summary-card :deep(.el-card__header) {
  padding: 10px 12px 8px;
  border-bottom: 1px solid rgba(191, 219, 254, 0.8);
}

.holding-summary-card :deep(.el-card__body) {
  padding: 12px;
}

.holding-summary-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.holding-summary-card-title {
  font-weight: 700;
  color: #1f2937;
  letter-spacing: 0.4px;
}

.holding-summary-card-badges {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.holding-summary-card-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.holding-summary-card-text {
  color: #1f2937;
  font-size: 13px;
  line-height: 1.65;
  font-weight: 600;
}

.holding-summary-card-footer {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  color: #64748b;
  font-size: 12px;
}

.holding-trigger-board {
  display: grid;
  grid-template-columns: 1fr;
  gap: 4px;
  padding: 8px 10px;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  background: rgba(248, 250, 252, 0.85);
}

.holding-trigger-switch {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.holding-trigger-switch-label {
  color: #475569;
  font-size: 12px;
}

.holding-trigger-line {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
}

.holding-trigger-label {
  color: #475569;
  min-width: 54px;
}

.holding-trigger-value {
  color: #1f2937;
  font-weight: 600;
}

.valuation-block-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding-bottom: 6px;
  margin-bottom: 8px;
  border-bottom: 1px dashed #dbeafe;
}

.valuation-block-title {
  font-weight: 700;
  color: #1f2937;
  letter-spacing: 0.5px;
}

.valuation-block-subtitle {
  color: #64748b;
  font-size: 11px;
}

.valuation-side-card {
  padding: 8px;
  background: #ffffff;
  border-radius: 8px;
  color: #606266;
  border: 1px solid #e5e7eb;
  min-height: 112px;
}

.valuation-side-card-primary {
  border-left: 4px solid #3b82f6;
}

.valuation-side-card-secondary {
  border-left: 4px solid #10b981;
}

.section-toggle {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 8px 0;
  padding: 6px 10px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: #f9fafb;
  color: #334155;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  user-select: none;
}
</style>
