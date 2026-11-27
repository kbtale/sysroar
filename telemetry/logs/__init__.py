from django.conf import settings
from .base import LogBackend
from .elasticsearch import ElasticsearchLogBackend
from .loki import LokiLogBackend
from .null import NullLogBackend


def get_log_backend() -> LogBackend:
    backend_kind = (getattr(settings, 'LOG_BACKEND', 'none') or 'none').strip().lower()
    if backend_kind == 'loki':
        return LokiLogBackend(base_url=getattr(settings, 'LOKI_URL', 'http://loki:3100'))
    if backend_kind == 'elasticsearch':
        return ElasticsearchLogBackend(
            base_url=getattr(settings, 'ELASTICSEARCH_URL', 'http://elasticsearch:9200'),
            index_pattern=getattr(settings, 'ELASTICSEARCH_LOG_INDEX', 'sysroar-logs-*'),
        )
    return NullLogBackend()


__all__ = [
    'ElasticsearchLogBackend',
    'LogBackend',
    'LokiLogBackend',
    'NullLogBackend',
    'get_log_backend',
]
