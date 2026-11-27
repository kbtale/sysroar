from django.conf import settings

DEFAULT_CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self' ws: wss:; "
    "frame-ancestors 'none'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

DEFAULT_PERMISSIONS_POLICY = 'geolocation=(), microphone=(), camera=(), payment=(), usb=()'

_UNSAFE_KEY_PREFIXES = (
    'django-insecure',
    'dev-secret-key',
)


def validate_production_security(debug: bool, secret_key: str, allowed_hosts: list[str]) -> list[tuple[str, str]]:
    if debug:
        return []

    errors: list[tuple[str, str]] = []
    key = (secret_key or '').strip()
    if len(key) < 32 or any(key.startswith(prefix) for prefix in _UNSAFE_KEY_PREFIXES):
        errors.append(
            (
                'sysroar.E001',
                'Refusing to start with DEBUG=False and a default or weak SECRET_KEY (minimum 32 characters).',
            )
        )

    cleaned_hosts = [str(host).strip() for host in (allowed_hosts or []) if str(host).strip()]
    if not cleaned_hosts or '*' in cleaned_hosts:
        errors.append(
            (
                'sysroar.E002',
                'Refusing to start with DEBUG=False and empty or wildcard (*) ALLOWED_HOSTS.',
            )
        )

    return errors


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        csp = getattr(settings, 'CSP_POLICY', DEFAULT_CSP_POLICY)
        if csp and 'Content-Security-Policy' not in response:
            response['Content-Security-Policy'] = csp
        if 'Permissions-Policy' not in response:
            response['Permissions-Policy'] = getattr(
                settings,
                'PERMISSIONS_POLICY',
                DEFAULT_PERMISSIONS_POLICY,
            )
        if 'Cross-Origin-Opener-Policy' not in response:
            response['Cross-Origin-Opener-Policy'] = 'same-origin'
        return response
