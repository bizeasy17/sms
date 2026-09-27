from django.urls import path

from .views import (
    classify,
    health_report,
    index_cards,
    return_spread,
    score,
    search_history,
    search_history_delete,
    search_suggest,
)

urlpatterns = [
    path('index-cards/', index_cards),
    path('search/suggest/', search_suggest),
    path('search/history/', search_history),
    path('search/history/<str:history_id>/', search_history_delete),
    path('classify/', classify),
    path('score/', score),
    path('return-spread/', return_spread),
    path('report/<str:ts_code>/', health_report),
]
