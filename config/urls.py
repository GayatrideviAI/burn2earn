from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("mitra/", include("apps.field.urls")),
    path("", RedirectView.as_view(pattern_name="field:dashboard", permanent=False)),
]
