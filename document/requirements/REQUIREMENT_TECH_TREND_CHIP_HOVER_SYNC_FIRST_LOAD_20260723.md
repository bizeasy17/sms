# REQUIREMENT: Technical Trend Chip Hover Sync on First Load (UAT)

Date: 2026-07-23
Owner Service: smartinvestor_fe

## Goal
Fix the technical trend tab so the chip chart follows mouse hover correctly on the first page load.

## Scope
- Component: `smartinvestor_fe/src/components/StockChart.vue`
- Keep existing chart data contracts unchanged.
- Do not change backend APIs.

## Observed Issue
- On first load of the valuation overview technical trend tab, the chip panel stays on the latest day and does not follow mouse movement.
- After switching to another stock, hover sync works again.

## Hypothesis
- Hover binding is established before the ECharts instances are fully mounted/ready during the first load.
- A later stock switch re-renders the chart and rebinds the listener successfully.

## Fix Strategy
- Bind trend hover sync after the loading state transitions to ready and the chart instances are mounted.
- Preserve current chip rendering logic and cache behavior.

## Acceptance
1. First load hover on the technical trend tab updates the chip chart as the mouse moves.
2. Switching stocks continues to work normally.
3. No backend contract changes are introduced.
