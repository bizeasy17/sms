from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("prediction", "0016_snapshot_bucket_unique"),
    ]

    operations = [
        migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop),
    ]
