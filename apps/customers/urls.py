from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "customers"

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="customers/login.html", redirect_authenticated_user=True, next_page="customers:dashboard"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="customers:login"), name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("yards/<uuid:pk>/", views.yard_detail, name="yard"),
    path("batches/<uuid:pk>/", views.batch_detail, name="batch"),
    path("contracts/", views.contract_list, name="contracts"),
    path("contracts/<uuid:pk>/", views.contract_detail, name="contract"),
    path("orders/<uuid:pk>/", views.order_detail, name="order"),
]
