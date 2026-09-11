from django.urls import path

from . import views


urlpatterns = [
	path('securities', views.securities, name='market-analysis-securities'),
	path('securities/<str:ts_code>', views.security_detail, name='market-analysis-security-detail'),
	path('securities/<str:ts_code>/bars', views.security_bars, name='market-analysis-security-bars'),
	path('securities/<str:ts_code>/fundamentals', views.security_fundamentals, name='market-analysis-security-fundamentals'),
	path('securities/<str:ts_code>/financials', views.security_financials, name='market-analysis-security-financials'),
	path('securities/<str:ts_code>/disclosures', views.security_disclosures, name='market-analysis-security-disclosures'),
	path('securities/<str:ts_code>/valuations/traditional', views.security_traditional_valuation, name='market-analysis-traditional-valuation'),
	path('securities/<str:ts_code>/valuations/traditional/history', views.security_traditional_valuation_history, name='market-analysis-traditional-valuation-history'),
	path('securities/<str:ts_code>/valuations/traditional/compare', views.security_traditional_valuation_compare, name='market-analysis-traditional-valuation-compare'),
	path('securities/<str:ts_code>/valuations/predictive', views.security_predictive_valuation, name='market-analysis-predictive-valuation'),
	path('securities/<str:ts_code>/valuations/predictive/history', views.security_predictive_valuation_history, name='market-analysis-predictive-valuation-history'),
	path('securities/<str:ts_code>/valuations/predictive/fusion', views.security_predictive_valuation_fusion, name='market-analysis-predictive-valuation-fusion'),
	path('valuations/predictive/status', views.predictive_valuation_status, name='market-analysis-predictive-valuation-status'),
	path('market/regime', views.market_regime, name='market-analysis-market-regime'),
	path('securities/<str:ts_code>/regime', views.security_regime, name='market-analysis-security-regime'),
	path('sentiment/market', views.sentiment_market, name='market-analysis-sentiment-market'),
	path('sentiment/market/history', views.sentiment_market_history, name='market-analysis-sentiment-market-history'),
	path('sentiment/stocks/ranking', views.sentiment_stock_ranking, name='market-analysis-sentiment-stock-ranking'),
	path('sentiment/stocks/<str:ts_code>/history', views.sentiment_stock_history, name='market-analysis-sentiment-stock-history'),
	path('sentiment/stocks/<str:ts_code>', views.sentiment_stock, name='market-analysis-sentiment-stock'),
	path('indices/catalog', views.indices_catalog, name='market-analysis-indices-catalog'),
	path('indices/<str:index_key>/valuation', views.index_valuation, name='market-analysis-index-valuation'),
	path('indices/health', views.indices_health, name='market-analysis-indices-health'),
	path('indices/equity-bond', views.indices_equity_bond, name='market-analysis-indices-equity-bond'),
	path('indices/health/history', views.indices_health_history, name='market-analysis-indices-health-history'),
	path('indices/health/events', views.indices_health_events, name='market-analysis-indices-health-events'),
]
