from datetime import datetime, timedelta, timezone as dt_timezone
import uuid
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.permissions import IsCompanyViewer
from monitoring.models import Server
from telemetry.logs import get_log_backend

_LOG_RANGES = {
    '15m': timedelta(minutes=15),
    '1h': timedelta(hours=1),
    '6h': timedelta(hours=6),
    '24h': timedelta(hours=24),
    '7d': timedelta(days=7),
}


def _parse_iso_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)
        return dt
    except ValueError:
        return None


class LogsStatusView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyViewer]

    def get(self, request):
        backend = get_log_backend()
        return Response(backend.health(), status=status.HTTP_200_OK)


class LogsQueryView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyViewer]

    def get(self, request):
        backend = get_log_backend()
        company_id = getattr(request.user, 'company_id', None)
        if not company_id:
            return Response({'detail': 'Tenant scope required.'}, status=status.HTTP_403_FORBIDDEN)

        if not backend.enabled:
            return Response(
                {'enabled': False, 'backend': backend.backend_name, 'entries': []},
                status=status.HTTP_200_OK,
            )

        raw_server_id = (request.query_params.get('server_id') or '').strip()
        scoped_server_id = None
        if raw_server_id:
            try:
                parsed_uid = uuid.UUID(raw_server_id)
            except ValueError:
                return Response({'detail': 'Invalid server_id.'}, status=status.HTTP_400_BAD_REQUEST)
            if not Server.unscoped.filter(id=parsed_uid, company_id=company_id).exists():
                return Response({'detail': 'Server not found.'}, status=status.HTTP_404_NOT_FOUND)
            scoped_server_id = str(parsed_uid)

        now = timezone.now()
        range_key = (request.query_params.get('range') or '1h').strip()
        delta = _LOG_RANGES.get(range_key, timedelta(hours=1))
        end_dt = _parse_iso_dt(request.query_params.get('end')) or now
        start_dt = _parse_iso_dt(request.query_params.get('start')) or (end_dt - delta)
        q = (request.query_params.get('q') or '').strip()[:256]
        level = (request.query_params.get('level') or '').strip().upper()[:16]
        try:
            limit = max(1, min(500, int(request.query_params.get('limit') or 200)))
        except ValueError:
            limit = 200

        try:
            entries = backend.query(
                company_id=str(company_id),
                server_id=scoped_server_id,
                q=q,
                level=level,
                start=start_dt,
                end=end_dt,
                limit=limit,
            )
        except Exception as exc:
            return Response(
                {'detail': f'Log backend query failed: {exc}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                'enabled': True,
                'backend': backend.backend_name,
                'entries': entries,
            },
            status=status.HTTP_200_OK,
        )
