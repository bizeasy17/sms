from django.urls import path

from . import views

urlpatterns = [
    path("stock-observation/", views.get_stock_observation_v1, name="opt-stock-observation-v1"),
]
