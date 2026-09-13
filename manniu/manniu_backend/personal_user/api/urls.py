from django.urls import path

from personal_user.api import views


urlpatterns = [
    path('me/profile', views.profile),
    path('me/watchlist', views.watchlist),
    path('me/watchlist/<int:item_id>', views.watchlist_item),
    path('me/watchlist/reorder', views.watchlist_reorder),
    path('me/observations', views.observations),
    path('me/observations/<int:item_id>', views.observation_item),
    path('me/observations/reorder', views.observation_reorder),
    path('me/portfolios', views.portfolios),
    path('me/portfolios/<int:portfolio_id>', views.portfolio_detail),
    path('me/portfolios/reorder', views.portfolio_reorder),
    path('me/portfolios/<int:portfolio_id>/positions', views.positions),
    path('me/portfolios/<int:portfolio_id>/positions/<int:position_id>', views.position_detail),
]