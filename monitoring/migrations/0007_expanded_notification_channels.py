from django.db import migrations, models

CHANNEL_CHOICES = [
    ('EMAIL', 'Email'),
    ('WEBHOOK', 'Webhook'),
    ('SLACK', 'Slack'),
    ('DISCORD', 'Discord'),
    ('TEAMS', 'Microsoft Teams'),
    ('TELEGRAM', 'Telegram'),
    ('PAGERDUTY', 'PagerDuty'),
    ('OPSGENIE', 'Opsgenie'),
    ('NTFY', 'ntfy'),
    ('GOTIFY', 'Gotify'),
]


class Migration(migrations.Migration):
    dependencies = [
        ('monitoring', '0006_phase3_mvp_models'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notificationchannel',
            name='channel_type',
            field=models.CharField(choices=CHANNEL_CHOICES, default='EMAIL', max_length=16),
        ),
        migrations.AlterField(
            model_name='notificationchannel',
            name='target',
            field=models.CharField(max_length=512),
        ),
        migrations.AlterField(
            model_name='notificationchannel',
            name='webhook_secret',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AlterField(
            model_name='alertrule',
            name='notification_type',
            field=models.CharField(choices=CHANNEL_CHOICES, default='EMAIL', max_length=16),
        ),
        migrations.AlterField(
            model_name='alertrule',
            name='notification_target',
            field=models.CharField(blank=True, max_length=512, null=True),
        ),
        migrations.AlterField(
            model_name='alertrule',
            name='webhook_secret',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]
