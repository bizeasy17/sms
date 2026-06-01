from django.urls import path
from . import views

urlpatterns = [
    # features endpoints
    path('features/<str:model>/<str:version>/', views.get_feature_list, name='feature_list'),
]