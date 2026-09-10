from django.urls import path

from . import views


urlpatterns = [
    path('live', views.live, name='api-gateway-health-live'),
    path('ready', views.ready, name='api-gateway-health-ready'),
]
