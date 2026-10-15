import uuid

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

STATUS_CHOICES = [("active", "Active"), ("inactive", "Inactive")]


def base_fields():
    return [
        (
            "id",
            models.UUIDField(
                default=uuid.uuid4, editable=False, primary_key=True, serialize=False
            ),
        ),
        ("status", models.CharField(choices=STATUS_CHOICES, default="active", max_length=10)),
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
        ("reference", "0006_statebiomassfactor"),
    ]

    operations = [
        migrations.AddField(
            model_name="biomasstype",
            name="gcv_min",
            field=models.DecimalField(
                blank=True,
                decimal_places=0,
                max_digits=7,
                null=True,
                validators=[django.core.validators.MinValueValidator(0)],
                verbose_name="GCV minimum (kcal/kg)",
            ),
        ),
        migrations.AddField(
            model_name="biomasstype",
            name="gcv_max",
            field=models.DecimalField(
                blank=True,
                decimal_places=0,
                max_digits=7,
                null=True,
                validators=[django.core.validators.MinValueValidator(0)],
                verbose_name="GCV maximum (kcal/kg)",
            ),
        ),
        migrations.AddField(
            model_name="biomasstype",
            name="processing_requirement",
            field=models.TextField(
                blank=True,
                help_text="What this biomass needs before it can be sold, for example drying",
            ),
        ),
        migrations.CreateModel(
            name="ProcessingType",
            fields=base_fields()
            + [
                ("name", models.CharField(max_length=100, unique=True)),
                ("description", models.TextField(blank=True)),
                (
                    "input_biomass_types",
                    models.ManyToManyField(
                        blank=True,
                        help_text="Biomass this process can take in. Empty = not restricted yet.",
                        related_name="processing_types",
                        to="reference.biomasstype",
                    ),
                ),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Product",
            fields=base_fields()
            + [
                ("name", models.CharField(max_length=150)),
                (
                    "form",
                    models.CharField(
                        choices=[("raw", "Raw"), ("processed", "Processed")], max_length=10
                    ),
                ),
                (
                    "grade",
                    models.CharField(
                        blank=True, help_text="For example A, B or Premium", max_length=50
                    ),
                ),
                (
                    "minimum_gcv",
                    models.DecimalField(
                        blank=True,
                        decimal_places=0,
                        max_digits=7,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                        verbose_name="Minimum GCV (kcal/kg)",
                    ),
                ),
                (
                    "biomass_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="products",
                        to="reference.biomasstype",
                    ),
                ),
                (
                    "processing_type",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="products",
                        to="reference.processingtype",
                    ),
                ),
            ],
            options={
                "ordering": ["name", "grade"],
                "constraints": [
                    models.UniqueConstraint(fields=("name", "grade"), name="uniq_product_name_grade"),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("form", "raw"), ("processing_type__isnull", True)),
                            models.Q(("form", "processed"), ("processing_type__isnull", False)),
                            _connector="OR",
                        ),
                        name="product_form_matches_processing_type",
                    ),
                ],
            },
        ),
    ]
