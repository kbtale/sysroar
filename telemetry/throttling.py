import uuid
from rest_framework.throttling import SimpleRateThrottle
from monitoring.models import Server


class ServerIngestRateThrottle(SimpleRateThrottle):
    scope = 'telemetry_ingest'

    def get_cache_key(self, request, view):
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return None

        company_id = getattr(user, 'company_id', None)
        raw_server = request.data.get('server') if isinstance(request.data, dict) else None
        ident = f'invalid:{user.pk}'

        if company_id and raw_server:
            try:
                server_uuid = uuid.UUID(str(raw_server))
            except (ValueError, TypeError):
                server_uuid = None

            if server_uuid and Server.unscoped.filter(id=server_uuid, company_id=company_id).exists():
                ident = f'{company_id}:{server_uuid}'

        return self.cache_format % {
            'scope': self.scope,
            'ident': ident,
        }
