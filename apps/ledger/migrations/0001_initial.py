import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

# The database itself refuses to change or remove a ledger row, so even someone with direct
# database access has to work around a trigger to rewrite history.
CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION ledger_reject_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'The ledger is append-only: rows cannot be updated or deleted'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$ LANGUAGE plpgsql;
"""
CREATE_TRIGGER = """
CREATE TRIGGER ledger_append_only
BEFORE UPDATE OR DELETE ON ledger_ledgerentry
FOR EACH ROW EXECUTE FUNCTION ledger_reject_change();
"""
DROP_TRIGGER = "DROP TRIGGER IF EXISTS ledger_append_only ON ledger_ledgerentry;"
DROP_FUNCTION = "DROP FUNCTION IF EXISTS ledger_reject_change();"


class Migration(migrations.Migration):
    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="LedgerEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("seq", models.PositiveBigIntegerField(unique=True)),
                ("entry_type", models.CharField(db_index=True, max_length=64)),
                ("subject_type", models.CharField(db_index=True, max_length=40)),
                ("subject_id", models.CharField(db_index=True, max_length=64)),
                ("payload_text", models.TextField()),
                ("created_at", models.DateTimeField()),
                ("prev_hash", models.CharField(max_length=64)),
                ("hash", models.CharField(max_length=64, unique=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"verbose_name_plural": "ledger entries", "ordering": ["seq"]},
        ),
        migrations.RunSQL(sql=[CREATE_FUNCTION, CREATE_TRIGGER], reverse_sql=[DROP_TRIGGER, DROP_FUNCTION]),
    ]
