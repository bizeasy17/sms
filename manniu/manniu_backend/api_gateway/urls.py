from django.urls import path

from . import views


urlpatterns = [
	path('securities', views.securities, name='market-analysis-securities'),
	path('securities/<str:ts_code>', views.security_detail, name='market-analysis-security-detail'),
	path('securities/<str:ts_code>/bars', views.security_bars, name='market-analysis-security-bars'),
	path('securities/<str:ts_code>/fundamentals', views.security_fundamentals, name='market-analysis-security-fundamentals'),
	path('market/regime', views.market_regime, name='market-analysis-market-regime'),
	path('securities/<str:ts_code>/regime', views.security_regime, name='market-analysis-security-regime'),
]
