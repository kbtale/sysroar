from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('monitoring', '0010_status_pages'),
    ]

    operations = [
        migrations.AddField(
            model_name='alertrule',
            name='log_level',
            field=models.CharField(blank=True, default='', max_length=16),
        ),
        migrations.AddField(
            model_name='alertrule',
            name='log_query',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AlterField(
            model_name='alertrule',
            name='metric_type',
            field=models.CharField(
                choices=[
                    ('cpu', 'CPU Usage (%)'),
                    ('ram', 'RAM Usage (%)'),
                    ('disk', 'Disk Usage (%)'),
                    ('disk_io', 'Disk I/O (MB)'),
                    ('swap', 'Swap Usage (%)'),
                    ('load', 'Load Average (1m)'),
                    ('no_data', 'Host Offline / No Data'),
                    ('log_count', 'Log Match Count'),
                ],
                max_length=16,
            ),
        ),
    ]
