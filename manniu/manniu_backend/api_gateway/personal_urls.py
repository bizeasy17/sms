"""Gateway-owned route registration for current-user resources."""

from django.urls import include, path


urlpatterns = [
    path('', include('personal_user.api.urls')),
]