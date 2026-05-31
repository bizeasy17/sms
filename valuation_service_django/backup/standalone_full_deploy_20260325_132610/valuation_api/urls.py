from django.urls import path
from . import views

urlpatterns = [
    path("health/", views.health_check, name="health-check"),
    path("stocks/<str:ts_code>/valuation/methods/", views.get_stock_valuation_methods, name="stock-valuation-methods"),
    path("stocks/<str:ts_code>/valuation/full/", views.get_stock_valuation_full, name="stock-valuation-full"),
    path("openclaw/valuation/chat/", views.openclaw_valuation_chat, name="openclaw-valuation-chat"),
]
