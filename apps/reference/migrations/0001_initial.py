import uuid

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

STATUS_CHOICES = [("active", "Active"), ("inactive", "Inactive")]


def base_fields():
    """The fields every BaseModel adds, in declaration order."""
    return [
        (
            "id",
            models.UUIDField(
                default=uuid.uuid4, editable=False, primary_key=True, serialize=False
            ),
        ),
        (
            "status",
            models.CharField(choices=STATUS_CHOICES, default="active", max_length=10),
        ),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("updated_at", models.DateTimeField(auto_now=True)),
        (
            "created_by",
            models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        (
            "updated_by",
            models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Crop",
            fields=base_fields() + [("name", models.CharField(max_length=100, unique=True))],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Season",
            fields=base_fields()
            + [
                ("name", models.CharField(max_length=50, unique=True)),
                (
                    "start_month",
                    models.PositiveSmallIntegerField(
                        help_text="1 = January",
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(12),
                        ],
                    ),
                ),
                (
                    "end_month",
                    models.PositiveSmallIntegerField(
                        help_text="12 = December. May be earlier than the start month if the season crosses the new year.",
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(12),
                        ],
                    ),
                ),
            ],
            options={"ordering": ["start_month"]},
        ),
    ]
