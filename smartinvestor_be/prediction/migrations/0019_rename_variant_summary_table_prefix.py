from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("prediction", "0018_stockvaluationvariantsummarylatest_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            ALTER TABLE IF EXISTS prediction_stockvaluationvariantsummarylatest
            RENAME TO valuation_stockvaluationvariantsummarylatest;
            """,
            reverse_sql="""
            ALTER TABLE IF EXISTS valuation_stockvaluationvariantsummarylatest
            RENAME TO prediction_stockvaluationvariantsummarylatest;
            """,
        ),
    ]
