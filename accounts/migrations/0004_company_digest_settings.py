from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0003_user_role_companyinvite'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='digest_email',
            field=models.EmailField(blank=True, default='', max_length=254),
        ),
        migrations.AddField(
            model_name='company',
            name='digest_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='company',
            name='digest_hour_utc',
            field=models.PositiveSmallIntegerField(
                default=8,
                validators=[MinValueValidator(0), MaxValueValidator(23)],
            ),
        ),
        migrations.AddField(
            model_name='company',
            name='last_digest_sent_on',
            field=models.DateField(blank=True, null=True),
        ),
    ]
