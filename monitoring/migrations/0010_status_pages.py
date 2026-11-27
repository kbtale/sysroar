import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0004_company_digest_settings'),
        ('monitoring', '0009_maintenance_windows'),
    ]

    operations = [
        migrations.CreateModel(
            name='StatusPage',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('slug', models.SlugField(max_length=80, unique=True)),
                ('title', models.CharField(max_length=128)),
                ('description', models.TextField(blank=True, default='')),
                ('is_public', models.BooleanField(db_index=True, default=True)),
                ('accent_color', models.CharField(default='#0ea5e9', max_length=16)),
                ('show_incidents', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'company',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='%(class)s_data',
                        to='accounts.company',
                    ),
                ),
                (
                    'servers',
                    models.ManyToManyField(blank=True, related_name='status_pages', to='monitoring.server'),
                ),
                (
                    'uptime_checks',
                    models.ManyToManyField(blank=True, related_name='status_pages', to='monitoring.uptimecheck'),
                ),
            ],
            options={'ordering': ['title', 'slug']},
        ),
    ]
