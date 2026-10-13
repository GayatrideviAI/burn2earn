from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm as DjangoUserChangeForm
from django.contrib.auth.forms import AdminUserCreationForm

from .models import User


class UserCreationForm(AdminUserCreationForm):
    """The admin's own add-user form (Django 5.1+), which has the "usable password" choice."""

    class Meta(AdminUserCreationForm.Meta):
        model = User
        fields = ("username", "role", "mobile")


class UserChangeForm(DjangoUserChangeForm):
    class Meta(DjangoUserChangeForm.Meta):
        model = User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    fieldsets = DjangoUserAdmin.fieldsets + (("Regenerix", {"fields": ("role", "mobile")}),)
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ("Regenerix", {"fields": ("role", "mobile")}),
    )
    list_display = ("username", "get_full_name", "role", "mobile", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("username", "first_name", "last_name", "mobile")
