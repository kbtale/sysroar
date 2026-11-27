import uuid
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0003_user_role_companyinvite'),
        ('monitoring', '0007_expanded_notification_channels'),
    ]

    operations = [
        migrations.CreateModel(
            name='UptimeCheck',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=128)),
                (
                    'check_type',
                    models.CharField(
                        choices=[
                            ('http', 'HTTP / HTTPS'),
                            ('tcp', 'TCP Port'),
                            ('ping', 'Ping'),
                            ('dns', 'DNS Lookup'),
                            ('ssl', 'SSL Certificate'),
                        ],
                        default='http',
                        max_length=16,
                    ),
                ),
                ('target', models.CharField(max_length=512)),
                ('port', models.PositiveIntegerField(blank=True, null=True)),
                ('expected_status', models.PositiveIntegerField(default=200)),
                ('expected_keyword', models.CharField(blank=True, default='', max_length=255)),
                ('ssl_expiry_warning_days', models.PositiveIntegerField(default=14)),
                ('interval_seconds', models.PositiveIntegerField(default=60)),
                ('timeout_seconds', models.PositiveIntegerField(default=10)),
                ('allow_private_targets', models.BooleanField(default=False)),
                ('tags', models.JSONField(blank=True, default=list)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                (
                    'last_status',
                    models.CharField(
                        choices=[
                            ('up', 'Up'),
                            ('degraded', 'Degraded'),
                            ('down', 'Down'),
                            ('unknown', 'Unknown'),
                        ],
                        default='unknown',
                        max_length=16,
                    ),
                ),
                ('last_latency_ms', models.FloatField(blank=True, null=True)),
                ('last_ssl_expiry_days', models.IntegerField(blank=True, null=True)),
                ('last_error', models.CharField(blank=True, default='', max_length=512)),
                ('last_checked_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('consecutive_failures', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'channel',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='uptime_checks',
                        to='monitoring.notificationchannel',
                    ),
                ),
                (
                    'company',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='%(class)s_data',
                        to='accounts.company',
                    ),
                ),
            ],
            options={'abstract': False},
        ),
        migrations.CreateModel(
            name='UptimeCheckResult',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    'status',
                    models.CharField(
                        choices=[('up', 'Up'), ('degraded', 'Degraded'), ('down', 'Down')],
                        max_length=16,
                    ),
                ),
                ('latency_ms', models.FloatField(blank=True, null=True)),
                ('status_code', models.PositiveIntegerField(blank=True, null=True)),
                ('ssl_expiry_days', models.IntegerField(blank=True, null=True)),
                ('error_message', models.CharField(blank=True, default='', max_length=512)),
                ('checked_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                (
                    'check_obj',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='results',
                        to='monitoring.uptimecheck',
                    ),
                ),
                (
                    'company',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='%(class)s_data',
                        to='accounts.company',
                    ),
                ),
            ],
            options={
                'indexes': [
                    models.Index(fields=['company', 'check_obj', '-checked_at'], name='monitoring_u_co_chk_idx'),
                ],
            },
        ),
        migrations.AlterField(
            model_name='incident',
            name='server',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='incidents',
                to='monitoring.server',
            ),
        ),
        migrations.AddField(
            model_name='incident',
            name='uptime_check',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='incidents',
                to='monitoring.uptimecheck',
            ),
        ),
    ]
