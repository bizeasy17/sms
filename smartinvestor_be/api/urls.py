from django.urls import path
from . import views

urlpatterns = [
    # Stock-related endpoints (RESTful format, optimized with freq and adj params)
    path(
        "stocks/<int:from_index>/<int:to_index>/",
        views.get_stock_list,
        name="stock-list",
    ),
    path("stocks/<str:ts_code>/", views.get_stock_basic, name="stock-basic"),
    path(
        "stocks/<str:ts_code>/trading-history/<str:freq>/<str:adj>/<int:count>/",
        views.get_stock_trading_history,
        name="stock-trading-history",
    ),
    path(
        "stocks/<str:ts_code>/fundamental-history/<str:freq>/<int:count>/",
        views.get_stock_fundamental_history,
        name="stock-fundamental-history",
    ),
    path(
        "stocks/<str:ts_code>/gain-loss-statistic/<str:freq>/<int:period>/",
        views.get_stock_gain_loss_statistic,
        name="stock-gain-loss-statistic",
    ),
    path(
        "corporations/<str:input_text>/",
        views.get_stock_corporation,
        name="corporation-list",
    ),
    # Watchlist endpoints
    path(
        "watchlist/<int:from_index>/<int:to_index>/",
        views.get_watch_list,
        name="watch-list",
    ),
    path("watchlist/add/<str:ts_code>/", views.add_stock_to_watchlist, name="add-stock-to-watchlist"),
    path(
        "watchlist/delete/<str:ts_code>/",
        views.soft_delete_stock_from_watchlist,
        name="soft-delete-stock-from-watchlist",
    ),
    path(
        "watchlist/hold/<str:ts_code>/",
        views.mark_stock_as_hold,
        name="mark-stock-as-hold",
    ),
    path(
        "watchlist/unhold/<str:ts_code>/",
        views.unmark_stock_as_hold,
        name="unmark-stock-as-hold",
    ),
    path(
        "watchlist/observe/<str:ts_code>/",
        getattr(views, "mark_stock_as_observe", views.add_stock_to_watchlist),
        name="mark-stock-as-observe",
    ),
    path(
        "watchlist/unobserve/<str:ts_code>/",
        getattr(views, "unmark_stock_as_observe", views.unmark_stock_as_hold),
        name="unmark-stock-as-observe",
    ),
    path(
        "watchlist/check/<str:ts_code>/",
        views.check_watchlist_or_hold,
        name="check-watchlist-or-hold",
    ),
    path(
        "recent-financial-updates/",
        views.get_recent_financial_updates,
        name="recent-financial-updates",
    ),
    # tag endpoints
    path(
        "tags/<str:ts_code>/",
        views.get_stock_tags,
        name="user-stock-tags",
    ),
    path("tags/add/<str:ts_code>/<str:tag>/", views.add_stock_tag, name="add-stock-tag"),
    path("tags/delete/<str:ts_code>/<str:tag>/", views.delete_stock_tag, name="delete-stock-tag"),
    path(
        "tags/similar/<str:ts_code>/",
        views.get_stocks_with_same_tag,
        name="stocks-with-same-tag",
    ),
    # stock prediction
    path(
        "stocks/<str:ts_code>/prediction/<str:model>/<str:volatility>/<int:period>/<str:freq>/<str:version>/",
        views.get_stock_prediction_result,
        name="stock-prediction-result",
    ),
    path(
        "trading/latest-date/<str:freq>/",
        views.get_latest_trade_date,
        name="latest-trade-date",
    ),
    path(
        "stocks/prediction/<str:model>/<str:volatility>/<str:trade_date>/<str:freq>/<int:from_index>/<int:to_index>/",
        views.get_all_stocks_prediction_result,
        name="all-stocks-prediction-result",
    ),
    path(
        "stock-pick/<str:trade_date>/<str:scope>/<str:model>/<str:model_version>/<str:top_bottom>/<str:freq>/<int:period>/<str:params>/<int:from_index>/<int:to_index>/",
        views.pick_stocks_by_params,
        name="pick-stocks-by-params",
    ),
    path(
        "stock-pick-valuation/sw-industries/",
        views.get_sw_industry_options,
        name="sw-industry-options",
    ),
    path(
        "stock-pick-financial/<str:trade_date>/<str:scope>/",
        views.pick_stocks_by_financial_performance,
        name="pick-stocks-by-financial-performance",
    ),
    path(
        "sw-industries/",
        getattr(views, "get_sw_industry_list", views.get_sw_industry_options),
        name="sw-industry-list",
    ),
    path(
        "sw-industries/<str:industry_code>/history/",
        getattr(views, "get_sw_industry_history", views.get_sw_industry_options),
        name="sw-industry-history",
    ),
    path(
        "sw-industries/<str:industry_code>/constituents/<int:from_index>/<int:to_index>/",
        getattr(views, "get_sw_industry_constituents", views.get_sw_industry_options),
        name="sw-industry-constituents",
    ),
    path(
        "industry-universe/types/",
        getattr(views, "get_industry_universe_types", views.get_sw_industry_options),
        name="industry-universe-types",
    ),
    path(
        "industry-universe/list/",
        getattr(views, "get_industry_universe_list", views.get_sw_industry_options),
        name="industry-universe-list",
    ),
    path(
        "industry-universe/history/",
        getattr(views, "get_industry_universe_history", views.get_sw_industry_options),
        name="industry-universe-history",
    ),
    path(
        "industry-universe/constituents/",
        getattr(views, "get_industry_universe_constituents", views.get_sw_industry_options),
        name="industry-universe-constituents",
    ),
    path(
        "industry-universe/rotation/latest/",
        getattr(views, "get_industry_universe_rotation_latest", views.get_sw_industry_options),
        name="industry-universe-rotation-latest",
    ),
    path(
        "industry-universe/moneyflow/latest/",
        getattr(views, "get_industry_universe_moneyflow_latest", views.get_sw_industry_options),
        name="industry-universe-moneyflow-latest",
    ),
    path(
        "industry-universe/rotation/recompute/",
        getattr(views, "recompute_industry_universe_rotation", views.get_sw_industry_options),
        name="industry-universe-rotation-recompute",
    ),
    path(
        "industry-universe/rotation/runs/",
        getattr(views, "get_industry_universe_rotation_runs", views.get_sw_industry_options),
        name="industry-universe-rotation-runs",
    ),
    path(
        "industry-universe/rotation/runs/<str:run_id>/",
        getattr(views, "get_industry_universe_rotation_run_detail", views.get_sw_industry_options),
        name="industry-universe-rotation-run-detail",
    ),
    path(
        "industry-universe/rotation/runs/<str:run_id>/delete/",
        getattr(views, "delete_industry_universe_rotation_run", views.get_sw_industry_options),
        name="industry-universe-rotation-run-delete",
    ),
    path(
        "market-index/valuation-simple/",
        views.get_market_index_simple_valuation,
        name="market-index-valuation-simple",
    ),
    path(
        "stock-pick-valuation/weekly-downloads/",
        views.get_weekly_undervalued_downloads,
        name="weekly-undervalued-downloads",
    ),
    path(
        "stock-pick-valuation/weekly-downloads/<str:kind>/",
        views.download_weekly_undervalued_file,
        name="weekly-undervalued-download-file",
    ),
    path(
        "stock-pick-valuation/job-strategy-config/",
        views.get_or_update_weekly_job_strategy_config,
        name="weekly-job-strategy-config",
    ),
    path(
        "stock-pick-valuation/jobs/",
        views.create_stock_pick_valuation_job,
        name="stock-pick-valuation-job-create",
    ),
    path(
        "stock-pick-valuation/jobs/<str:job_id>/",
        views.get_stock_pick_valuation_job,
        name="stock-pick-valuation-job-detail",
    ),
    path(
        "stock-pick-valuation/<str:trade_date>/<str:scope>/",
        views.pick_stocks_by_valuation_simple,
        name="pick-stocks-by-valuation-simple",
    ),
    path(
        "stock-pick-valuation/<str:trade_date>/<str:scope>/<str:model>/<str:model_version>/<str:top_bottom>/<str:freq>/<int:period>/<str:params>/<int:from_index>/<int:to_index>/",
        views.pick_stocks_by_valuation,
        name="pick-stocks-by-valuation",
    ),
    # tushare在线实时抓取的筹码，财务，基金持仓等的数据
    path(
        "tushare/<str:ts_code>/<str:data_type>/",
        views.get_tushare_data,
        name="tushare-data",
    ),
    path(
        "stocks/<str:ts_code>/valuation/demo/",
        views.get_stock_demo_valuation,
        name="stock-demo-valuation",
    ),
    path(
        "stocks/<str:ts_code>/valuation/methods/",
        views.get_stock_valuation_methods,
        name="stock-valuation-methods",
    ),
    path(
        "stocks/<str:ts_code>/valuation/snapshot-history/",
        views.get_stock_valuation_snapshot_history,
        name="stock-valuation-snapshot-history",
    ),
    path(
        "openclaw/valuation/chat/",
        views.openclaw_valuation_chat,
        name="openclaw-valuation-chat",
    ),
    path(
        "earnings/signal/<str:ts_code>/",
        views.get_earnings_signal,
        name="earnings-signal",
    ),
    path(
        "earnings/signal-persisted/<str:ts_code>/",
        views.get_earnings_signal_persisted,
        name="earnings-signal-persisted",
    ),
    path(
        "earnings/signal-history/<str:ts_code>/",
        views.get_earnings_signal_history,
        name="earnings-signal-history",
    ),
    path(
        "earnings/signal-compare/<str:ts_code>/",
        views.get_earnings_signal_compare,
        name="earnings-signal-compare",
    ),
]
