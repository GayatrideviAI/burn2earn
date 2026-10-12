import uuid

from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models


class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    MITRA = "mitra", "Biomass Mitra"
    FARMER = "farmer", "Farmer"
    BUYER = "buyer", "Buyer"


class UserManager(DjangoUserManager):
    use_in_migrations = False

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", Role.ADMIN)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """Login account. Kept separate from the Farmer, Mitra or Buyer record it belongs to.

    In V1 only Admin and Mitra accounts are used; the Farmer and Buyer roles exist
    so the data model does not need to change when those logins are switched on.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(max_length=10, choices=Role.choices)
    mobile = models.CharField(max_length=15, blank=True)

    objects = UserManager()

    @property
    def is_admin_role(self):
        return self.role == Role.ADMIN
