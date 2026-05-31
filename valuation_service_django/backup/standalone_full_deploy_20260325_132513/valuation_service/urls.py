from django.urls import path, include

urlpatterns = [
    path("api/", include("valuation_api.urls")),
]
