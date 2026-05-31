from django.urls import path
from . import views

urlpatterns = [
    path(
        "stocks/<str:ts_code>/trades/<freq>/<date_from>/limit/<int:limit>/",
        views.get_stock_trading_history,
        name="stock-trade-list",
    ),
    path(
        "stocks/trades/<freq>/all-not-pulled/",
        views.get_all_trading_history_not_pulled,
        name="stock-trade-list",
    ),
    path(
        "stocks/trades/pull-status/update/<freq>/",
        views.update_trading_history_pull_status,
        name="update-trade-pull-status",
    ),
    path(
        "stocks/fundamentals/pull-status/update/<freq>/",
        views.update_fundamental_history_pull_status,
        name="update-fundamental-pull-status",
    ),
    path(
        "stocks/<str:ts_code>/trades/<freq>/<date_from>/",
        views.get_trading_history_from,
        name="stock-trade-list",
    ),
    path(
        "stocks/<str:ts_code>/fundamentals/<freq>/<date_from>/limit/<int:limit>/",
        views.get_stock_fundamental_history,
        name="stock-fundamental-data",
    ),
    path(
        "stocks/fundamentals/<freq>/all-not-pulled/",
        views.get_all_fundamental_history_not_pulled,
        name="stock-fundamental-data",
    ),
    path(
        "stocks/<str:ts_code>/fundamentals/<freq>/<date_from>/",
        views.get_fundamental_history_from,
        name="stock-fundamental-data",
    ),
    path(
        "stocks/<str:ts_code>/cost/<freq>/<date_from>/limit/<int:limit>/",
        views.get_stock_cost_history,
        name="stock-cost-list",
    ),
    path(
        "stocks/cost/<freq>/all-not-pulled/",
        views.get_all_cost_history_not_pulled,
        name="stock-cost-list",
    ),
    path(
        "stocks/<str:ts_code>/cost/<freq>/<date_from>/",
        views.get_cost_history_from,
        name="stock-cost-data",
    ),
    path(
        "stocks/cost/pull-status/update/<freq>/",
        views.update_cost_history_pull_status,
        name="update-cost-pull-status",
    ),
    # 返回技术面，基本面数据拼接成的特征数据
    # path(
    #     "stock-features/<str:ts_code>/<str:freq>/<str:feature_type>/",
    #     views.get_stock_features,
    #     name="stock-features",
    # ),
    # path(
    #     "all-stock-features/<str:freq>/<str:feature_type>/<int:from_index>/<int:to_index>/",
    #     views.get_all_stock_features,
    #     name="all-stock-features",
    # ),
]
