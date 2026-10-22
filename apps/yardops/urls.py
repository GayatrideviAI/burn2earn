from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "yardops"

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="yardops/login.html", redirect_authenticated_user=True, next_page="yardops:home"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="yardops:login"), name="logout"),
    path("", views.home, name="home"),
    path("piles/<uuid:pk>/", views.pile_detail, name="pile"),
    path("alerts/<uuid:pk>/acknowledge/", views.acknowledge, name="acknowledge"),
]
