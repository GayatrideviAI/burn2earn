from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "field"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="field/login.html", redirect_authenticated_user=True),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("farmers/", views.farmer_list, name="farmer_list"),
    path("farmers/new/", views.farmer_new, name="farmer_new"),
    path("farmers/<uuid:pk>/", views.farmer_detail, name="farmer_detail"),
    path("farmers/<uuid:pk>/collect/", views.collection_new, name="collection_new"),
    path("stock/", views.stock, name="stock"),
    path("stock/output/new/", views.output_new, name="output_new"),
    path("farmers/<uuid:pk>/plots/new/", views.plot_new, name="plot_new"),
    path("farmers/<uuid:pk>/plots/<uuid:plot_pk>/crops/new/", views.season_new, name="season_new"),
]
