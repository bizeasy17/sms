from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('market_sentiment', '0001_initial')]

    operations = [
        migrations.AlterField(
            model_name='marketsentimentsnapshot',
            name='status',
            field=models.CharField(db_index=True, default='PENDING', max_length=32),
        ),
    ]
