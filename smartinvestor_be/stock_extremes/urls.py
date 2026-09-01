from django.urls import path

from stock_extremes.views import get_stock_extremes


urlpatterns = [
    path("extremes/", get_stock_extremes, name="stock-extremes"),
]
