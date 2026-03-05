from django.core.checks import Warning, register


@register()
def check_elasticsearch_security(app_configs, **kwargs):
    """
    Warns developers if Elasticsearch xpack.security is likely disabled.
    This check runs on every `manage.py runserver`, `migrate`, and `check`.
    """
    import os
    errors = []

    es_security = os.getenv("ELASTICSEARCH_SECURITY_ENABLED", "false").lower()
    if es_security != "true":
        errors.append(
            Warning(
                "Elasticsearch xpack.security appears to be disabled.",
                hint=(
                    "Enable xpack.security in docker-compose.elk.yml for production. "
                    "Set ELASTICSEARCH_SECURITY_ENABLED=true in .env to suppress this warning."
                ),
                id="sysroar.W001",
            )
        )
    return errors
