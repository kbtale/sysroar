import ipaddress
from config.logging_utils import get_correlation_id


def _client_ip(request):
    if request is None:
        return None
    raw = request.META.get('REMOTE_ADDR')
    if not raw:
        return None
    try:
        return str(ipaddress.ip_address(raw.strip()))
    except ValueError:
        return None


def record_audit_event(
    request,
    action: str,
    resource_type: str,
    resource_id: str = '',
    metadata: dict | None = None,
    company_id=None,
):
    from monitoring.models import AuditLog

    user = getattr(request, 'user', None) if request is not None else None
    is_human = bool(user and getattr(user, 'is_authenticated', False) and not getattr(user, 'is_agent', False))
    resolved_company_id = company_id or (getattr(user, 'company_id', None) if is_human else None)
    if not resolved_company_id:
        return None

    return AuditLog.unscoped.create(
        company_id=resolved_company_id,
        actor=user if is_human else None,
        actor_username=getattr(user, 'username', '') if is_human else 'system',
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id else '',
        metadata=metadata or {},
        ip_address=_client_ip(request),
        correlation_id=(get_correlation_id() or '')[:64],
    )
