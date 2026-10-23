from decimal import Decimal

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import apps.weightphotos.models

STATUS_CHOICES = [("active", "Active"), ("inactive", "Inactive")]
PROTECT = django.db.models.deletion.PROTECT


def base_fields():
    import uuid

    return [
        ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
        ("status", models.CharField(choices=STATUS_CHOICES, default="active", max_length=10)),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("updated_at", models.DateTimeField(auto_now=True)),
        (
            "created_by",
            models.ForeignKey(
                blank=True, editable=False, null=True, on_delete=PROTECT, related_name="+", to=settings.AUTH_USER_MODEL
            ),
        ),
        (
            "updated_by",
            models.ForeignKey(
                blank=True, editable=False, null=True, on_delete=PROTECT, related_name="+", to=settings.AUTH_USER_MODEL
            ),
        ),
    ]


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("customers", "0004_pile_dimensions"),
    ]

    operations = [
        migrations.CreateModel(
            name="WeightPhoto",
            fields=base_fields()
            + [
                ("code", models.CharField(editable=False, max_length=20, unique=True)),
                (
                    "subject",
                    models.CharField(choices=[("stack", "A stack"), ("load", "A loaded vehicle")], max_length=10),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[("yard", "Yard app"), ("mitra", "Mitra app")], editable=False, max_length=10
                    ),
                ),
                (
                    "place_note",
                    models.CharField(blank=True, help_text="Where it is, if it is not a pile in a yard", max_length=120),
                ),
                (
                    "vehicle_type",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("tractor_trolley", "Tractor trolley"),
                            ("truck", "Truck"),
                            ("mini_truck", "Mini truck or pickup"),
                            ("other", "Other"),
                        ],
                        max_length=20,
                    ),
                ),
                ("vehicle_ref", models.CharField(blank=True, help_text="Vehicle number or driver", max_length=50)),
                ("taken_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("taken_by", models.CharField(blank=True, max_length=200)),
                (
                    "image",
                    models.ImageField(
                        editable=False, max_length=200, upload_to=apps.weightphotos.models.photo_path
                    ),
                ),
                ("sha256", models.CharField(db_index=True, editable=False, max_length=64)),
                ("width", models.PositiveIntegerField(editable=False)),
                ("height", models.PositiveIntegerField(editable=False)),
                (
                    "bale_count",
                    models.PositiveIntegerField(
                        blank=True,
                        help_text="Bales visible or loaded, if counted",
                        null=True,
                        validators=[django.core.validators.MaxValueValidator(100000)],
                    ),
                ),
                (
                    "reference_note",
                    models.CharField(
                        blank=True,
                        help_text="Anything in the photo that shows size, such as a 2 m pole or a person",
                        max_length=200,
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                (
                    "weighed_tonnes",
                    models.DecimalField(
                        blank=True,
                        decimal_places=3,
                        max_digits=10,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.001"))],
                    ),
                ),
                ("slip_number", models.CharField(blank=True, max_length=50)),
                ("weighed_on", models.DateField(blank=True, null=True)),
                ("ledger_seq", models.PositiveBigIntegerField(blank=True, editable=False, null=True)),
                (
                    "pile",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=PROTECT,
                        related_name="weight_photos",
                        to="customers.pile",
                    ),
                ),
                (
                    "taken_by_user",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-taken_at"]},
        ),
        migrations.AddConstraint(
            model_name="weightphoto",
            constraint=models.CheckConstraint(
                condition=models.Q(("weighed_tonnes__isnull", True), ("weighed_tonnes__gt", 0), _connector="OR"),
                name="weightphoto_weight_positive",
            ),
        ),
    ]
