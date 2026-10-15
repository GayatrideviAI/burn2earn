from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("farms", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="farmer",
            name="needs_review",
            field=models.BooleanField(default=False),
        ),
    ]
