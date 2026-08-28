from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('market_sentiment', '0002_alter_marketsentimentsnapshot_status')]

    operations = [
        migrations.AlterField(
            model_name='marketsentimentsnapshot',
            name='sentiment_level',
            field=models.CharField(db_index=True, default='WARMING_UP', max_length=32),
        ),
    ]
