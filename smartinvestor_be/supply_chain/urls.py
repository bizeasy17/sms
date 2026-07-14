from django.urls import path

from supply_chain import views

urlpatterns = [
    path("graph/", views.get_supply_chain_graph, name="supply-chain-graph"),
]
