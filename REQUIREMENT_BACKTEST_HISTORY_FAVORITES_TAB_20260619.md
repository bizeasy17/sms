# REQUIREMENT: Backtest History Dialog Add Favorites Tab (2026-06-19)

## 1. Background

In Backtest Execute page history dialog, there are currently two tabs:

- 手动回测 (manual)
- 网格搜索 (scan)

When run count becomes large, users need a fast way to view only favorited runs.

## 2. Objective

Add a new tab in history dialog:

- 已收藏 (favorites)

This tab should show all favorited backtest runs across manual/scan sources to reduce browsing effort.

## 3. Service Ownership

Owner service for this change:

- `web/UAT/smartinvestor_fe` (frontend only)

No backend API contract change is required.

## 4. Functional Requirements

1. Add `已收藏` tab to history dialog tabs.
2. In favorites tab, data source is local favorite run ids (`favoriteRunIds`) and existing run list API:
   - reuse `/backtest/traditional/runs/` endpoint
   - collect rows containing run ids in `favoriteRunIds`
3. Favorites list should include both kinds:
   - manual
   - scan
4. Display fields should keep parity with existing history rows (run_id, run_key, mode, date range, metrics, params summary).
5. Keep existing row interactions:
   - double-click row to load run detail
   - toggle favorite from row action
6. Pagination behavior:
   - favorites tab can paginate independently (recommended)
   - if implementation cost is high, allow first version to show all favorites without pagination
7. Empty state:
   - show clear message when no favorites exist.

## 5. Non-Goals

- No backend schema/API changes.
- No change to backtest execution strategy logic.
- No change to favorite persistence key format.

## 6. UX Notes

1. Tab order recommendation:
   - 手动回测 / 网格搜索 / 已收藏
2. Toolbar count display example:
   - 已收藏共 N 条
3. If favorite run id no longer exists in backend list, ignore silently.

## 7. Validation Plan

1. Open history dialog and verify 3 tabs render.
2. Add/remove favorites in manual/scan tabs, switch to favorites tab and verify list updates correctly.
3. Favorites tab contains mixed source rows when applicable.
4. Double-click in favorites tab loads run detail and stock tables normally.
5. No console/runtime error after tab switching and pagination.

## 8. Acceptance Criteria

- New `已收藏` tab is visible and functional.
- Favorites tab shows only favorited runs across manual/scan.
- Existing manual/scan tabs behavior remains unchanged.
- No new compile/type errors in touched frontend file.
