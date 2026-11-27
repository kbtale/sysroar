import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0004_company_digest_settings'),
        ('monitoring', '0008_uptime_checks'),
    ]

    operations = [
        migrations.CreateModel(
            name='MaintenanceWindow',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=128)),
                (
                    'scope',
                    models.CharField(
                        choices=[('all', 'All Resources'), ('server', 'Single Server'), ('tag', 'Server Tag')],
                        default='all',
                        max_length=16,
                    ),
                ),
                ('tag_filter', models.CharField(blank=True, default='', max_length=64)),
                (
                    'recurrence',
                    models.CharField(
                        choices=[('none', 'One-time'), ('daily', 'Daily'), ('weekly', 'Weekly')],
                        default='none',
                        max_length=16,
                    ),
                ),
                ('starts_at', models.DateTimeField(db_index=True)),
                ('ends_at', models.DateTimeField(db_index=True)),
                ('reason', models.CharField(blank=True, default='', max_length=255)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'company',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='%(class)s_data',
                        to='accounts.company',
                    ),
                ),
                (
                    'created_by',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='created_maintenance_windows',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'server',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='maintenance_windows',
                        to='monitoring.server',
                    ),
                ),
            ],
            options={
                'ordering': ['-starts_at'],
                'indexes': [
                    models.Index(fields=['company', 'is_active', 'starts_at'], name='monitoring_mw_co_act_idx'),
                ],
            },
        ),
    ]
