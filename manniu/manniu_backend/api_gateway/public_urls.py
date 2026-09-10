from django.urls import path

from . import views


urlpatterns = [
    path('catalog', views.public_api_catalog_view, name='public-api-catalog'),
]