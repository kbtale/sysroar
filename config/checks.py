import os
from django.conf import settings
from django.core.checks import Error, Warning, register
from config.security import validate_production_security


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


@register()
def check_production_security(app_configs, **kwargs):
    issues = validate_production_security(
        debug=bool(getattr(settings, 'DEBUG', False)),
        secret_key=str(getattr(settings, 'SECRET_KEY', '')),
        allowed_hosts=list(getattr(settings, 'ALLOWED_HOSTS', [])),
    )
    return [Error(message, id=code) for code, message in issues]
