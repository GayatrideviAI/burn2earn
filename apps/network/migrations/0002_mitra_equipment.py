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
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("territory", "0001_initial"),
        ("network", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="EquipmentType",
            fields=base_fields() + [("name", models.CharField(max_length=100, unique=True))],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Mitra",
            fields=base_fields()
            + [
                (
                    "code",
                    models.CharField(
                        help_text="For example MITRA-HR-AMB-001", max_length=32, unique=True
                    ),
                ),
                (
                    "name",
                    models.CharField(help_text="Person or organisation", max_length=200),
                ),
                (
                    "mobile",
                    models.CharField(
                        max_length=16,
                        validators=[
                            django.core.validators.RegexValidator(
                                message="Enter a mobile number with 10 to 15 digits, optionally starting with +.",
                                regex="^\\+?\\d{10,15}$",
                            )
                        ],
                    ),
                ),
                ("address", models.TextField()),
                (
                    "onboarding_status",
                    models.CharField(
                        choices=[
                            ("invited", "Invited"),
                            ("agreement_pending", "Agreement pending"),
                            ("agreement_signed", "Agreement signed"),
                            ("verified", "Verified"),
                        ],
                        default="invited",
                        max_length=20,
                    ),
                ),
                (
                    "operating_status",
                    models.CharField(
                        choices=[
                            ("pending", "Not started yet"),
                            ("active", "Active"),
                            ("suspended", "Suspended"),
                            ("exited", "Exited"),
                        ],
                        default="pending",
                        max_length=10,
                    ),
                ),
                ("activated_on", models.DateField(blank=True, null=True)),
                (
                    "region",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="mitras",
                        to="territory.region",
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        blank=True,
                        limit_choices_to={"role": "mitra"},
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="mitra",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="MitraGridAssignment",
            fields=base_fields()
            + [
                ("from_date", models.DateField()),
                (
                    "to_date",
                    models.DateField(
                        blank=True,
                        help_text="Leave empty for the current assignment",
                        null=True,
                    ),
                ),
                (
                    "grid",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="mitra_assignments",
                        to="network.grid",
                    ),
                ),
                (
                    "mitra",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="grid_assignments",
                        to="network.mitra",
                    ),
                ),
            ],
            options={
                "ordering": ["-from_date"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("status", "active"), ("to_date__isnull", True)),
                        fields=("grid",),
                        name="uniq_current_mitra_per_grid",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("status", "active"), ("to_date__isnull", True)),
                        fields=("mitra",),
                        name="uniq_current_grid_per_mitra",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("to_date__isnull", True),
                            ("to_date__gte", models.F("from_date")),
                            _connector="OR",
                        ),
                        name="assignment_end_not_before_start",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="Equipment",
            fields=base_fields()
            + [
                (
                    "code",
                    models.CharField(
                        help_text="Asset tag or internal ID", max_length=32, unique=True
                    ),
                ),
                ("serial_number", models.CharField(blank=True, max_length=100)),
                ("manufacturer", models.CharField(blank=True, max_length=100)),
                (
                    "capacity",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=10, null=True
                    ),
                ),
                (
                    "capacity_unit",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("t_per_hour", "Tonnes per hour"),
                            ("t_per_day", "Tonnes per day"),
                            ("kg_per_hour", "Kilograms per hour"),
                            ("tonnes", "Tonnes (load)"),
                        ],
                        max_length=12,
                    ),
                ),
                ("installation_date", models.DateField(blank=True, null=True)),
                ("last_maintenance", models.DateField(blank=True, null=True)),
                ("next_maintenance", models.DateField(blank=True, null=True)),
                (
                    "operating_status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("under_maintenance", "Under maintenance"),
                            ("retired", "Retired"),
                        ],
                        default="active",
                        max_length=20,
                    ),
                ),
                (
                    "equipment_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="equipment",
                        to="network.equipmenttype",
                    ),
                ),
                (
                    "grid",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="equipment",
                        to="network.grid",
                    ),
                ),
                (
                    "hub",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="equipment",
                        to="network.hub",
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "equipment",
                "ordering": ["code"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("grid__isnull", False), ("hub__isnull", True)),
                            models.Q(("grid__isnull", True), ("hub__isnull", False)),
                            _connector="OR",
                        ),
                        name="equipment_at_exactly_one_site",
                    ),
                ],
            },
        ),
    ]
