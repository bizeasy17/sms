from django.urls import path

from . import views


urlpatterns = [
    path('login', views.login, name='auth-login'),
    path('token/refresh', views.refresh, name='auth-token-refresh'),
    path('me', views.me, name='auth-me'),
    path('sessions', views.sessions, name='auth-sessions'),
    path('sessions/<uuid:session_id>', views.revoke_session, name='auth-session-revoke'),
    path('logout', views.logout, name='auth-logout'),
    path('password/change', views.change_password, name='auth-password-change'),
]
