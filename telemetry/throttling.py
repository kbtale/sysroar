import uuid
from rest_framework.throttling import SimpleRateThrottle
from monitoring.models import Server


class ServerIngestRateThrottle(SimpleRateThrottle):
    scope = 'telemetry_ingest'

    def _extract_server_uuids(self, request):
        data = request.data
        if not isinstance(data, dict):
            return []
        if 'samples' in data and isinstance(data['samples'], list):
            raw_ids = []
            for item in data['samples'][:500]:
                if isinstance(item, dict) and item.get('server'):
                    raw_ids.append(item['server'])
        elif data.get('server'):
            raw_ids = [data['server']]
        else:
            return []

        uuids = set()
        for raw_id in raw_ids:
            try:
                uuids.add(uuid.UUID(str(raw_id)))
            except (ValueError, TypeError):
                return None
        return list(uuids)

    def get_cache_key(self, request, view):
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return None

        company_id = getattr(user, 'company_id', None)
        server_uuids = self._extract_server_uuids(request)
        ident = f'invalid:{user.pk}'

        if company_id and server_uuids:
            owned_count = Server.unscoped.filter(id__in=server_uuids, company_id=company_id).count()
            if owned_count == len(server_uuids):
                if len(server_uuids) == 1:
                    ident = f'{company_id}:{server_uuids[0]}'
                else:
                    ident = f'{company_id}:batch:{user.pk}'

        return self.cache_format % {
            'scope': self.scope,
            'ident': ident,
        }
