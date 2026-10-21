from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from apps.customers.views import trace_report
from apps.farms.views import supply_report
from apps.operations.views import stock_report

urlpatterns = [
    path("admin/reports/supply/", supply_report, name="supply_report"),
    path("admin/reports/stock/", stock_report, name="stock_report"),
    path("admin/reports/trace/", trace_report, name="trace_report"),
    path("admin/", admin.site.urls),
    path("mitra/", include("apps.field.urls")),
    path("i18n/", include("django.conf.urls.i18n")),
    path("customer/", include("apps.customers.urls")),
    path("", RedirectView.as_view(pattern_name="field:dashboard", permanent=False)),
]
