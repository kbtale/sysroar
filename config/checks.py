import os
from django.conf import settings
from django.core.checks import Warning, register


@register()
def check_elasticsearch_security(app_configs, **kwargs):
    if getattr(settings, 'LOG_BACKEND', 'none') != 'elasticsearch':
        return []

    es_security = os.getenv('ELASTICSEARCH_SECURITY_ENABLED', 'false').lower()
    if es_security != 'true':
        return [
            Warning(
                'Elasticsearch xpack.security appears to be disabled.',
                hint=(
                    'Enable xpack.security for production when using --profile elk. '
                    'Set ELASTICSEARCH_SECURITY_ENABLED=true in .env to suppress this warning.'
                ),
                id='sysroar.W001',
            )
        ]
    return []
