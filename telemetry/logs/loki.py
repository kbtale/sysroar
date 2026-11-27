from datetime import datetime, timedelta, timezone as dt_timezone
import requests
from django.utils import timezone
from .base import LogBackend


def _escape_logql_value(value: str) -> str:
    return value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')


def _ns_timestamp(dt: datetime) -> str:
    return str(int(dt.timestamp() * 1_000_000_000))


class LokiLogBackend(LogBackend):
    backend_name = 'loki'
    enabled = True

    def __init__(self, base_url: str, timeout_seconds: float = 5.0):
        self.base_url = base_url.rstrip('/')
        self.timeout_seconds = timeout_seconds

    def _build_logql(self, company_id: str, server_id: str | None, q: str, level: str) -> str:
        selectors = [f'company_id="{_escape_logql_value(str(company_id))}"']
        if server_id:
            selectors.append(f'server_id="{_escape_logql_value(str(server_id))}"')
        if level:
            selectors.append(f'level="{_escape_logql_value(level.upper())}"')
        expr = '{' + ','.join(selectors) + '}'
        cleaned_q = (q or '').strip()
        if cleaned_q:
            expr += f' |= "{_escape_logql_value(cleaned_q)}"'
        return expr

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
        logql = self._build_logql(company_id, server_id, q, level)
        resp = requests.get(
            f'{self.base_url}/loki/api/v1/query_range',
            params={
                'query': logql,
                'start': _ns_timestamp(start_dt),
                'end': _ns_timestamp(end_dt),
                'limit': clamped_limit,
                'direction': 'backward',
            },
            headers={'X-Scope-OrgID': str(company_id)},
            timeout=self.timeout_seconds,
        )
        resp.raise_for_status()
        body = resp.json()
        streams = ((body.get('data') or {}).get('result')) or []
        entries = []
        for stream_obj in streams:
            labels = stream_obj.get('stream') or {}
            for pair in stream_obj.get('values') or []:
                if len(pair) < 2:
                    continue
                ts_ns, line = pair[0], pair[1]
                try:
                    dt = datetime.fromtimestamp(int(ts_ns) / 1_000_000_000.0, tz=dt_timezone.utc)
                    ts_iso = dt.isoformat()
                except (ValueError, TypeError, OverflowError):
                    ts_iso = now.isoformat()
                entries.append(
                    {
                        'timestamp': ts_iso,
                        'level': str(labels.get('level') or 'INFO').upper(),
                        'message': str(line),
                        'server_id': str(labels.get('server_id') or ''),
                        'source': str(labels.get('source') or labels.get('job') or 'agent'),
                        'labels': {k: v for k, v in labels.items() if k != 'company_id'},
                    }
                )
        entries.sort(key=lambda item: item['timestamp'], reverse=True)
        return entries[:clamped_limit]

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
        window_s = max(1, int((end_dt - start_dt).total_seconds()))
        logql = self._build_logql(company_id, server_id, q, level)
        expr = f'sum(count_over_time({logql}[{window_s}s]))'
        resp = requests.get(
            f'{self.base_url}/loki/api/v1/query',
            params={'query': expr, 'time': _ns_timestamp(end_dt)},
            headers={'X-Scope-OrgID': str(company_id)},
            timeout=self.timeout_seconds,
        )
        resp.raise_for_status()
        body = resp.json()
        results = ((body.get('data') or {}).get('result')) or []
        total = 0
        for row in results:
            val = row.get('value')
            if isinstance(val, list) and len(val) >= 2:
                try:
                    total += int(float(val[1]))
                except (ValueError, TypeError):
                    pass
        return total

    def health(self) -> dict:
        try:
            resp = requests.get(f'{self.base_url}/ready', timeout=min(self.timeout_seconds, 3.0))
            healthy = resp.status_code == 200
        except requests.RequestException:
            healthy = False
        return {'enabled': True, 'backend': 'loki', 'healthy': healthy}
