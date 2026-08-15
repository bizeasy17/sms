from django.urls import path

from .views import screen

urlpatterns = [path("screen", screen, name="financial-screen")]