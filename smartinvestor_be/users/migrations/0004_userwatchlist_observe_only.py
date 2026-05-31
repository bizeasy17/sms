from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0003_userstocktag"),
    ]

    operations = [
        migrations.AddField(
            model_name="userwatchlist",
            name="observe_only",
            field=models.BooleanField(default=False, verbose_name="是否观察"),
        ),
    ]
