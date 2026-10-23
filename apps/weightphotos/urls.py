from django.urls import path

from . import api

app_name = "weightphotos"

urlpatterns = [
    path("<uuid:pk>/image/", api.image, name="image"),
]
