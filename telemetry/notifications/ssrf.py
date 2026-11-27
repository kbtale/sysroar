import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit
import requests
from requests.adapters import HTTPAdapter

ALLOWED_SCHEMES = {'http', 'https'}

_EXTRA_BLOCKED_NETWORKS = (
    ipaddress.ip_network('0.0.0.0/8'),
    ipaddress.ip_network('100.64.0.0/10'),
    ipaddress.ip_network('169.254.0.0/16'),
    ipaddress.ip_network('192.0.0.0/24'),
    ipaddress.ip_network('198.18.0.0/15'),
    ipaddress.ip_network('fd00:ec2::254/128'),
)


class SSRFBlockedError(ValueError):
    pass


def validate_ip_address(raw_ip: str) -> str:
    try:
        ip = ipaddress.ip_address(raw_ip)
    except ValueError as exc:
        raise SSRFBlockedError('Invalid resolved IP address.') from exc

    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise SSRFBlockedError('Webhook target resolves to a disallowed IP range.')

    for net in _EXTRA_BLOCKED_NETWORKS:
        if ip.version == net.version and ip in net:
            raise SSRFBlockedError('Webhook target resolves to a disallowed IP range.')

    return str(ip)


def validate_webhook_url(url: str) -> tuple[str, str, int]:
    if not url or not isinstance(url, str):
        raise SSRFBlockedError('Webhook URL is required.')
    cleaned = url.strip()
    if any(ch in cleaned for ch in ('\r', '\n', '\t', ' ')):
        raise SSRFBlockedError('Webhook URL contains illegal whitespace.')

    parsed = urlsplit(cleaned)
    scheme = (parsed.scheme or '').lower()
    if scheme not in ALLOWED_SCHEMES:
        raise SSRFBlockedError('Webhook URL must use http or https.')
    if parsed.username or parsed.password:
        raise SSRFBlockedError('Webhook URL must not contain embedded credentials.')

    hostname = (parsed.hostname or '').strip().rstrip('.').lower()
    if not hostname:
        raise SSRFBlockedError('Webhook URL must include a hostname.')

    try:
        port = parsed.port or (443 if scheme == 'https' else 80)
    except ValueError as exc:
        raise SSRFBlockedError('Webhook URL contains an invalid port.') from exc

    if port < 1 or port > 65535:
        raise SSRFBlockedError('Webhook URL port out of range.')

    try:
        addr_info = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SSRFBlockedError('Webhook hostname could not be resolved.') from exc

    if not addr_info:
        raise SSRFBlockedError('Webhook hostname resolved to no addresses.')

    validated_ips = []
    for entry in addr_info:
        sockaddr = entry[4]
        raw_ip = sockaddr[0].split('%', 1)[0]
        validated_ips.append(validate_ip_address(raw_ip))

    return hostname, validated_ips[0], port


class _PinnedHostTLSAdapter(HTTPAdapter):
    def __init__(self, hostname: str, **kwargs):
        self._pinned_hostname = hostname
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs['assert_hostname'] = self._pinned_hostname
        pool_kwargs['server_hostname'] = self._pinned_hostname
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


def send_safe_webhook_post(
    url: str,
    body: bytes,
    headers: dict[str, str],
    timeout: tuple[float, float] = (3.0, 5.0),
) -> requests.Response:
    hostname, resolved_ip, port = validate_webhook_url(url)
    parsed = urlsplit(url.strip())
    scheme = parsed.scheme.lower()
    ip_host = f'[{resolved_ip}]' if ':' in resolved_ip else resolved_ip
    default_port = 443 if scheme == 'https' else 80
    pinned_netloc = f'{ip_host}:{port}' if port != default_port else ip_host
    pinned_url = urlunsplit((scheme, pinned_netloc, parsed.path or '/', parsed.query, ''))

    original_netloc = f'{hostname}:{port}' if port != default_port else hostname
    req_headers = dict(headers)
    req_headers['Host'] = original_netloc

    session = requests.Session()
    try:
        if scheme == 'https':
            session.mount('https://', _PinnedHostTLSAdapter(hostname))
        return session.post(
            pinned_url,
            data=body,
            headers=req_headers,
            timeout=timeout,
            allow_redirects=False,
        )
    finally:
        session.close()
