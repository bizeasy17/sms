from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('market_sentiment', '0003_alter_marketsentimentsnapshot_sentiment_level')]

    operations = [
        migrations.AlterModelOptions(
            name='marketsentimentfactor',
            options={'ordering': ['sort_order', 'id']},
        ),
    ]
