from datetime import datetime, timedelta
import requests
from django.utils import timezone
from .base import LogBackend


class ElasticsearchLogBackend(LogBackend):
    backend_name = 'elasticsearch'
    enabled = True

    def __init__(self, base_url: str, index_pattern: str = 'sysroar-logs-*', timeout_seconds: float = 5.0):
        self.base_url = base_url.rstrip('/')
        self.index_pattern = index_pattern
        self.timeout_seconds = timeout_seconds

    def _build_query(
        self,
        company_id: str,
        server_id: str | None,
        q: str,
        level: str,
        start: datetime,
        end: datetime,
    ) -> dict:
        filters: list[dict] = [
            {'term': {'company_id': str(company_id)}},
            {'range': {'@timestamp': {'gte': start.isoformat(), 'lte': end.isoformat()}}},
        ]
        if server_id:
            filters.append({'term': {'server_id': str(server_id)}})
        if level:
            filters.append({'term': {'level': level.upper()}})
        must: list[dict] = []
        cleaned_q = (q or '').strip()
        if cleaned_q:
            must.append({'simple_query_string': {'query': cleaned_q, 'fields': ['message']}})
        return {'bool': {'filter': filters, 'must': must}}

    def query(
        self,
        company_id: str,
        server_id: str | None = None,
        q: str = '',
        level: str = '',
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 200,
    ) -> list[dict]:
        now = timezone.now()
        end_dt = end or now
        start_dt = start or (end_dt - timedelta(hours=1))
        clamped_limit = max(1, min(500, int(limit or 200)))
        es_query = self._build_query(company_id, server_id, q, level, start_dt, end_dt)
        resp = requests.post(
            f'{self.base_url}/{self.index_pattern}/_search',
            json={
                'size': clamped_limit,
                'sort': [{'@timestamp': {'order': 'desc'}}],
                'query': es_query,
            },
            timeout=self.timeout_seconds,
        )
        resp.raise_for_status()
        hits = ((resp.json().get('hits') or {}).get('hits')) or []
        entries = []
        for hit in hits:
            src = hit.get('_source') or {}
            entries.append(
                {
                    'timestamp': str(src.get('@timestamp') or now.isoformat()),
                    'level': str(src.get('level') or 'INFO').upper(),
                    'message': str(src.get('message') or ''),
                    'server_id': str(src.get('server_id') or ''),
                    'source': str(src.get('source') or 'syslog'),
                    'labels': {
                        k: str(v)
                        for k, v in src.items()
                        if k not in ('company_id', 'message', '@timestamp') and isinstance(v, (str, int, float))
                    },
                }
            )
        return entries

    def count_matching(
        self,
        company_id: str,
        server_id: str | None = None,
        q: str = '',
        level: str = '',
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> int:
        now = timezone.now()
        end_dt = end or now
        start_dt = start or (end_dt - timedelta(minutes=5))
        es_query = self._build_query(company_id, server_id, q, level, start_dt, end_dt)
        resp = requests.post(
            f'{self.base_url}/{self.index_pattern}/_count',
            json={'query': es_query},
            timeout=self.timeout_seconds,
        )
        resp.raise_for_status()
        return int(resp.json().get('count') or 0)

    def health(self) -> dict:
        try:
            resp = requests.get(f'{self.base_url}/_cluster/health', timeout=min(self.timeout_seconds, 3.0))
            healthy = resp.status_code == 200
        except requests.RequestException:
            healthy = False
        return {'enabled': True, 'backend': 'elasticsearch', 'healthy': healthy}
