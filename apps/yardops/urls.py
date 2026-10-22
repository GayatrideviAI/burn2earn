from django.contrib.auth import views as auth_views
from django.urls import path

from . import api, views

app_name = "yardops"

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="yardops/login.html", redirect_authenticated_user=True, next_page="yardops:home"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="yardops:login"), name="logout"),
    path("", views.home, name="home"),
    path("app/", views.offline_app, name="app"),
    path("sw.js", views.service_worker, name="service_worker"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("api/bootstrap/", api.bootstrap, name="api_bootstrap"),
    path("api/sync/", api.sync, name="api_sync"),
    path("piles/<uuid:pk>/", views.pile_detail, name="pile"),
    path("alerts/<uuid:pk>/acknowledge/", views.acknowledge, name="acknowledge"),
]
