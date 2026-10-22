from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("admin", "Admin"),
                    ("mitra", "Biomass Mitra"),
                    ("farmer", "Farmer"),
                    ("buyer", "Buyer"),
                    ("yard", "Yard operator"),
                ],
                max_length=10,
            ),
        ),
    ]
