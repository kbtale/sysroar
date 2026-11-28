from datetime import timedelta
import math
import os
import signal
import time
import uuid
from django.core.management.base import BaseCommand
from django.utils import timezone
from accounts.models import Company, User
from monitoring.heartbeat import record_heartbeats_batch
from monitoring.models import (
    AlertRule,
    MaintenanceWindow,
    NotificationChannel,
    Server,
    StatusPage,
    UptimeCheck,
    UptimeCheckResult,
)
from telemetry.ingestion import push_batch_to_stream
from telemetry.models import MetricLog

DEMO_COMPANY_NAME = 'SysRoar Demo Ops'
DEMO_USERNAME = 'demo'
DEMO_DEFAULT_CREDENTIAL = os.environ.get('SYSROAR_DEMO_LOGIN', 'DemoPass2026!')
DEMO_VIEWER_USERNAME = 'demo-viewer'


class DemoNoise:
    def __init__(self, seed: int = 42):
        self._state = seed & 0xFFFFFFFF

    def _next_unit(self) -> float:
        self._state = (self._state * 1664525 + 1013904223) & 0xFFFFFFFF
        return self._state / 4294967296.0

    def uniform(self, low: float, high: float) -> float:
        return low + (high - low) * self._next_unit()

    def randint(self, low: int, high: int) -> int:
        return low + int(self._next_unit() * (high - low + 1))

DEMO_SERVER_SPECS = [
    {
        'name': 'prod-api-eu-01',
        'hostname': 'prod-api-eu-01.demo.internal',
        'ip_address': '10.24.1.11',
        'os_info': 'Ubuntu 24.04 LTS',
        'kernel': '6.8.0-49-generic',
        'cpu_model': 'AMD EPYC 9654',
        'cpu_cores': 8,
        'total_ram_bytes': 34359738368,
        'tags': ['prod', 'eu-west', 'api'],
        'profile': 'web',
        'phase': 0.0,
    },
    {
        'name': 'prod-api-eu-02',
        'hostname': 'prod-api-eu-02.demo.internal',
        'ip_address': '10.24.1.12',
        'os_info': 'Ubuntu 24.04 LTS',
        'kernel': '6.8.0-49-generic',
        'cpu_model': 'AMD EPYC 9654',
        'cpu_cores': 8,
        'total_ram_bytes': 34359738368,
        'tags': ['prod', 'eu-west', 'api'],
        'profile': 'web',
        'phase': 0.4,
    },
    {
        'name': 'prod-api-us-01',
        'hostname': 'prod-api-us-01.demo.internal',
        'ip_address': '10.24.2.11',
        'os_info': 'Ubuntu 24.04 LTS',
        'kernel': '6.8.0-49-generic',
        'cpu_model': 'Intel Xeon Platinum 8488C',
        'cpu_cores': 16,
        'total_ram_bytes': 68719476736,
        'tags': ['prod', 'us-east', 'api'],
        'profile': 'web',
        'phase': 1.2,
    },
    {
        'name': 'prod-db-primary',
        'hostname': 'prod-db-primary.demo.internal',
        'ip_address': '10.24.1.21',
        'os_info': 'Debian GNU/Linux 12',
        'kernel': '6.1.0-27-amd64',
        'cpu_model': 'AMD EPYC 9654',
        'cpu_cores': 16,
        'total_ram_bytes': 68719476736,
        'tags': ['prod', 'eu-west', 'db'],
        'profile': 'db',
        'phase': 0.2,
    },
    {
        'name': 'prod-db-replica',
        'hostname': 'prod-db-replica.demo.internal',
        'ip_address': '10.24.1.22',
        'os_info': 'Debian GNU/Linux 12',
        'kernel': '6.1.0-27-amd64',
        'cpu_model': 'AMD EPYC 9654',
        'cpu_cores': 16,
        'total_ram_bytes': 68719476736,
        'tags': ['prod', 'eu-west', 'db'],
        'profile': 'db_replica',
        'phase': 0.6,
    },
    {
        'name': 'prod-redis-01',
        'hostname': 'prod-redis-01.demo.internal',
        'ip_address': '10.24.1.31',
        'os_info': 'Debian GNU/Linux 12',
        'kernel': '6.1.0-27-amd64',
        'cpu_model': 'AMD EPYC 9654',
        'cpu_cores': 4,
        'total_ram_bytes': 17179869184,
        'tags': ['prod', 'eu-west', 'cache'],
        'profile': 'cache',
        'phase': 0.8,
    },
    {
        'name': 'prod-worker-01',
        'hostname': 'prod-worker-01.demo.internal',
        'ip_address': '10.24.2.41',
        'os_info': 'Ubuntu 24.04 LTS',
        'kernel': '6.8.0-49-generic',
        'cpu_model': 'Intel Xeon Platinum 8488C',
        'cpu_cores': 8,
        'total_ram_bytes': 34359738368,
        'tags': ['prod', 'us-east', 'worker'],
        'profile': 'spiky',
        'phase': 1.5,
    },
    {
        'name': 'prod-worker-02',
        'hostname': 'prod-worker-02.demo.internal',
        'ip_address': '10.24.2.42',
        'os_info': 'Ubuntu 24.04 LTS',
        'kernel': '6.8.0-49-generic',
        'cpu_model': 'Intel Xeon Platinum 8488C',
        'cpu_cores': 8,
        'total_ram_bytes': 34359738368,
        'tags': ['prod', 'us-east', 'worker'],
        'profile': 'worker',
        'phase': 2.0,
    },
    {
        'name': 'edge-cdn-01',
        'hostname': 'edge-cdn-01.demo.internal',
        'ip_address': '10.24.3.10',
        'os_info': 'Alpine Linux 3.20',
        'kernel': '6.6.52-0-virt',
        'cpu_model': 'AMD EPYC 7R13',
        'cpu_cores': 4,
        'total_ram_bytes': 8589934592,
        'tags': ['prod', 'edge'],
        'profile': 'edge',
        'phase': 2.4,
    },
    {
        'name': 'edge-flap-01',
        'hostname': 'edge-flap-01.demo.internal',
        'ip_address': '10.24.3.99',
        'os_info': 'Ubuntu 24.04 LTS',
        'kernel': '6.8.0-49-generic',
        'cpu_model': 'AMD EPYC 7R13',
        'cpu_cores': 4,
        'total_ram_bytes': 8589934592,
        'tags': ['prod', 'edge', 'flapping'],
        'profile': 'flapping',
        'phase': 3.1,
    },
]


def _clamp(val: float, low: float = 0.0, high: float = 100.0) -> float:
    return round(max(low, min(high, val)), 2)


def is_flapping_offline(ts) -> bool:
    bucket = int(ts.timestamp() // 90)
    return bucket % 4 == 3


def generate_demo_sample(spec: dict, ts, rng: DemoNoise, spike_now: bool = False) -> dict:
    hour_frac = (ts.hour + ts.minute / 60.0 + ts.second / 3600.0) / 24.0
    diurnal = 0.5 + 0.5 * math.sin((2.0 * math.pi * hour_frac) - 1.2 + spec['phase'])
    profile = spec['profile']

    if profile == 'web':
        cpu = 22.0 + 34.0 * diurnal + rng.uniform(-3.0, 4.0)
        ram = 46.0 + 14.0 * diurnal + rng.uniform(-1.5, 1.5)
        disk = 38.0 + rng.uniform(-0.2, 0.2)
        net_rx = (1_800_000 + 3_200_000 * diurnal) * rng.uniform(0.85, 1.15)
        net_tx = (2_400_000 + 4_500_000 * diurnal) * rng.uniform(0.85, 1.15)
        disk_r = 350_000 + rng.uniform(0, 250_000)
        disk_w = 500_000 + rng.uniform(0, 350_000)
    elif profile == 'db':
        cpu = 32.0 + 22.0 * diurnal + rng.uniform(-2.5, 3.5)
        ram = 74.0 + 6.0 * diurnal + rng.uniform(-1.0, 1.0)
        disk = 62.5 + rng.uniform(-0.1, 0.2)
        net_rx = (3_000_000 + 2_000_000 * diurnal) * rng.uniform(0.9, 1.1)
        net_tx = (4_200_000 + 3_000_000 * diurnal) * rng.uniform(0.9, 1.1)
        disk_r = 4_500_000 + 3_000_000 * diurnal
        disk_w = 6_200_000 + 4_000_000 * diurnal
    elif profile == 'db_replica':
        cpu = 18.0 + 15.0 * diurnal + rng.uniform(-2.0, 2.0)
        ram = 68.0 + 5.0 * diurnal + rng.uniform(-1.0, 1.0)
        disk = 61.0 + rng.uniform(-0.1, 0.2)
        net_rx = 3_500_000 * rng.uniform(0.85, 1.15)
        net_tx = 900_000 * rng.uniform(0.85, 1.15)
        disk_r = 2_100_000 + 1_200_000 * diurnal
        disk_w = 3_800_000 + 1_500_000 * diurnal
    elif profile == 'cache':
        cpu = 12.0 + 14.0 * diurnal + rng.uniform(-1.5, 2.0)
        ram = 58.0 + 10.0 * diurnal + rng.uniform(-1.0, 1.0)
        disk = 21.0
        net_rx = 4_800_000 + 2_000_000 * diurnal
        net_tx = 5_100_000 + 2_200_000 * diurnal
        disk_r = 120_000
        disk_w = 240_000
    elif profile == 'spiky':
        is_burst = spike_now or (int(ts.timestamp() // 300) % 6 == 0)
        cpu = (86.0 + rng.uniform(0.0, 9.0)) if is_burst else (24.0 + 16.0 * diurnal + rng.uniform(-3.0, 3.0))
        ram = (72.0 + rng.uniform(0.0, 6.0)) if is_burst else (44.0 + 8.0 * diurnal + rng.uniform(-2.0, 2.0))
        disk = 47.0 + rng.uniform(-0.2, 0.3)
        net_rx = 1_200_000 + 1_500_000 * diurnal
        net_tx = 950_000 + 1_200_000 * diurnal
        disk_r = 1_800_000
        disk_w = 2_600_000
    elif profile == 'worker':
        cpu = 28.0 + 30.0 * diurnal + rng.uniform(-5.0, 8.0)
        ram = 51.0 + 12.0 * diurnal + rng.uniform(-2.0, 2.0)
        disk = 43.0
        net_rx = 900_000 + 1_100_000 * diurnal
        net_tx = 800_000 + 900_000 * diurnal
        disk_r = 1_100_000
        disk_w = 1_400_000
    elif profile == 'edge':
        cpu = 16.0 + 20.0 * diurnal + rng.uniform(-2.0, 3.0)
        ram = 34.0 + 6.0 * diurnal + rng.uniform(-1.0, 1.0)
        disk = 28.0
        net_rx = 8_500_000 + 6_000_000 * diurnal
        net_tx = 12_000_000 + 9_000_000 * diurnal
        disk_r = 300_000
        disk_w = 400_000
    else:
        cpu = 64.0 + 28.0 * diurnal + rng.uniform(-6.0, 8.0)
        ram = 62.0 + 18.0 * diurnal + rng.uniform(-3.0, 5.0)
        disk = 71.0 + rng.uniform(-0.5, 0.5)
        net_rx = 2_200_000 * rng.uniform(0.5, 1.5)
        net_tx = 1_900_000 * rng.uniform(0.5, 1.5)
        disk_r = 650_000
        disk_w = 900_000

    cpu_val = _clamp(cpu)
    ram_val = _clamp(ram)
    disk_val = _clamp(disk)
    load_val = round(max(0.05, (cpu_val / 100.0) * spec['cpu_cores'] * 0.75 + rng.uniform(0.0, 0.25)), 2)

    details = {
        'cpu_iowait_percent': round(rng.uniform(0.4, 4.8), 2),
        'cpu_steal_percent': round(rng.uniform(0.0, 0.8), 2),
        'process_count': int(140 + spec['cpu_cores'] * 8 + rng.randint(-5, 10)),
        'top_processes': [
            {
                'pid': 1024,
                'name': 'gunicorn' if profile == 'web' else profile,
                'cpu_percent': round(cpu_val * 0.45, 1),
                'memory_bytes': 640_000_000,
            },
            {'pid': 2048, 'name': 'sysroar-agent', 'cpu_percent': 0.6, 'memory_bytes': 28_000_000},
        ],
        'mounts': [
            {
                'mount': '/',
                'total_bytes': 107374182400,
                'available_bytes': int(107374182400 * (1.0 - disk_val / 100.0)),
                'used_percent': disk_val,
                'inodes_used_percent': round(disk_val * 0.42, 1),
            }
        ],
        'temperatures': [
            {'label': 'CPU Package', 'celsius': round(41.0 + cpu_val * 0.32, 1)},
        ],
        'docker_containers': [
            {
                'id': f'{spec["name"]}-app'[:12],
                'name': f'{spec["name"]}-svc',
                'image': 'ghcr.io/sysroar/demo-svc:1.0',
                'state': 'running',
                'cpu_percent': round(cpu_val * 0.6, 1),
                'memory_bytes': 512_000_000,
                'memory_limit_bytes': 2_147_483_648,
            }
        ],
        'systemd_units': [
            {'name': 'sysroar-agent.service', 'active_state': 'active', 'sub_state': 'running'},
            {'name': 'docker.service', 'active_state': 'active', 'sub_state': 'running'},
        ],
    }

    return {
        'cpu_usage': cpu_val,
        'ram_usage': ram_val,
        'disk_usage': disk_val,
        'swap_usage': round(rng.uniform(0.5, 4.5), 2),
        'disk_io': round((disk_r + disk_w) / 1_048_576.0, 2),
        'disk_read_bps': round(disk_r, 1),
        'disk_write_bps': round(disk_w, 1),
        'net_rx_bps': round(net_rx, 1),
        'net_tx_bps': round(net_tx, 1),
        'load_1m': load_val,
        'uptime_seconds': 86400 * 14 + int(ts.timestamp()) % 86400,
        'details': details,
    }


def seed_demo_environment(backfill_hours: int = 6) -> tuple[Company, list[tuple[Server, dict]]]:
    company, _ = Company.objects.get_or_create(
        name=DEMO_COMPANY_NAME,
        defaults={'retention_days': 30, 'digest_enabled': True, 'digest_hour_utc': 8},
    )

    owner, created = User.objects.get_or_create(
        username=DEMO_USERNAME,
        defaults={
            'email': 'demo@sysroar.local',
            'company': company,
            'role': User.ROLE_OWNER,
            'is_staff': True,
            'is_superuser': True,
        },
    )
    if created:
        owner.set_password(DEMO_DEFAULT_CREDENTIAL)
        owner.save(update_fields=['password'])

    viewer, v_created = User.objects.get_or_create(
        username=DEMO_VIEWER_USERNAME,
        defaults={
            'email': 'viewer@sysroar.local',
            'company': company,
            'role': User.ROLE_VIEWER,
        },
    )
    if v_created:
        viewer.set_password(DEMO_DEFAULT_CREDENTIAL)
        viewer.save(update_fields=['password'])

    now = timezone.now()
    rng = DemoNoise(42)
    server_pairs: list[tuple[Server, dict]] = []

    for spec in DEMO_SERVER_SPECS:
        srv, _ = Server.unscoped.get_or_create(
            company=company,
            name=spec['name'],
            defaults={
                'hostname': spec['hostname'],
                'ip_address': spec['ip_address'],
                'os_info': spec['os_info'],
                'kernel': spec['kernel'],
                'cpu_model': spec['cpu_model'],
                'cpu_cores': spec['cpu_cores'],
                'total_ram_bytes': spec['total_ram_bytes'],
                'agent_version': '0.2.0',
                'telemetry_cadence': 15,
                'tags': spec['tags'],
                'last_ping': now,
                'is_active': True,
            },
        )
        server_pairs.append((srv, spec))

    if backfill_hours > 0 and not MetricLog.unscoped.filter(company=company).exists():
        rows = []
        steps = max(1, int(backfill_hours * 12))
        for step in range(steps, 0, -1):
            ts = now - timedelta(minutes=step * 5)
            for srv, spec in server_pairs:
                if spec['profile'] == 'flapping' and is_flapping_offline(ts):
                    continue
                sample = generate_demo_sample(spec, ts, rng, spike_now=(step <= 2 and spec['profile'] == 'spiky'))
                rows.append(
                    MetricLog(
                        company=company,
                        server=srv,
                        timestamp=ts,
                        cpu_usage=sample['cpu_usage'],
                        ram_usage=sample['ram_usage'],
                        disk_usage=sample['disk_usage'],
                        swap_usage=sample['swap_usage'],
                        disk_io=sample['disk_io'],
                        disk_read_bps=sample['disk_read_bps'],
                        disk_write_bps=sample['disk_write_bps'],
                        net_rx_bps=sample['net_rx_bps'],
                        net_tx_bps=sample['net_tx_bps'],
                        load_1m=sample['load_1m'],
                        uptime_seconds=sample['uptime_seconds'],
                        details=sample['details'] if step == 1 else {},
                    )
                )
        MetricLog.unscoped.bulk_create(rows, batch_size=500, ignore_conflicts=True)

    channel, _ = NotificationChannel.unscoped.get_or_create(
        company=company,
        name='Demo Ops Email',
        defaults={
            'channel_type': 'EMAIL',
            'target': 'ops@sysroar.local',
            'is_default': True,
            'is_active': True,
        },
    )

    if not AlertRule.unscoped.filter(company=company).exists():
        first_srv = server_pairs[0][0]
        spiky_srv = next(s for s, sp in server_pairs if sp['profile'] == 'spiky')
        AlertRule.unscoped.create(
            company=company,
            server=spiky_srv,
            scope='server',
            channel=channel,
            metric_type='cpu',
            operator='gt',
            severity='warning',
            threshold_value=82.0,
            duration_minutes=1,
            notification_type=channel.channel_type,
            notification_target=channel.target,
        )
        AlertRule.unscoped.create(
            company=company,
            server=first_srv,
            scope='server',
            channel=channel,
            metric_type='ram',
            operator='gt',
            severity='critical',
            threshold_value=90.0,
            duration_minutes=2,
            notification_type=channel.channel_type,
            notification_target=channel.target,
        )

    demo_checks = [
        ('Public API Health', 'http', 'https://api.demo.sysroar.dev/health', 'up', 38.4, 62),
        ('Checkout Gateway', 'http', 'https://checkout.demo.sysroar.dev/status', 'up', 74.1, 44),
        ('Edge TLS Certificate', 'ssl', 'edge.demo.sysroar.dev', 'degraded', 19.2, 9),
    ]
    created_checks = []
    for name, ctype, target, st, latency, ssl_days in demo_checks:
        chk, chk_created = UptimeCheck.unscoped.get_or_create(
            company=company,
            name=name,
            defaults={
                'check_type': ctype,
                'target': target,
                'port': 443 if ctype == 'ssl' else None,
                'channel': channel,
                'last_status': st,
                'last_latency_ms': latency,
                'last_ssl_expiry_days': ssl_days,
                'last_checked_at': now,
                'is_active': True,
            },
        )
        created_checks.append(chk)
        if chk_created:
            res_rows = [
                UptimeCheckResult(
                    company=company,
                    check_obj=chk,
                    status='down' if (i == 7 and name == 'Checkout Gateway') else st,
                    latency_ms=round(latency + rng.uniform(-6.0, 12.0), 1),
                    status_code=200 if ctype == 'http' else None,
                    ssl_expiry_days=ssl_days,
                    checked_at=now - timedelta(minutes=(25 - i) * 5),
                )
                for i in range(25)
            ]
            UptimeCheckResult.unscoped.bulk_create(res_rows)

    if not MaintenanceWindow.unscoped.filter(company=company).exists():
        MaintenanceWindow.unscoped.create(
            company=company,
            name='Sunday Database Vacuum',
            scope='tag',
            tag_filter='db',
            recurrence='weekly',
            starts_at=now + timedelta(days=2),
            ends_at=now + timedelta(days=2, hours=1),
            reason='Scheduled weekly vacuum and reindex',
            created_by=owner,
        )

    status_page, sp_created = StatusPage.unscoped.get_or_create(
        slug='demo',
        defaults={
            'company': company,
            'title': 'SysRoar Demo Platform Status',
            'description': 'Live simulated uptime and fleet health for SysRoar demo mode.',
            'is_public': True,
            'accent_color': '#10b981',
            'show_incidents': True,
        },
    )
    if sp_created:
        status_page.uptime_checks.set(created_checks)
        status_page.servers.set([s for s, _ in server_pairs[:4]])

    return company, server_pairs


class Command(BaseCommand):
    help = 'Seed a demo company with 10 realistic servers and stream live telemetry samples.'

    def add_arguments(self, parser):
        parser.add_argument('--interval', type=int, default=10)
        parser.add_argument('--backfill-hours', type=int, default=6)
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        interval = max(2, int(options['interval']))
        backfill_hours = max(0, int(options['backfill_hours']))
        run_once = bool(options['once'])

        running = True

        def _stop(_sig, _frame):
            nonlocal running
            running = False

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)

        company, server_pairs = seed_demo_environment(backfill_hours=backfill_hours)
        self.stdout.write(
            self.style.SUCCESS(
                f'Demo workspace "{company.name}" ready (login: {DEMO_USERNAME} / {DEMO_DEFAULT_CREDENTIAL}, '
                f'status page: /status/demo, servers: {len(server_pairs)}).'
            )
        )

        rng = DemoNoise(int(time.time()))
        tick = 0
        while running:
            now = timezone.now()
            payloads = []
            heartbeats = []
            for srv, spec in server_pairs:
                if spec['profile'] == 'flapping' and is_flapping_offline(now):
                    continue
                sample = generate_demo_sample(
                    spec,
                    now,
                    rng,
                    spike_now=(spec['profile'] == 'spiky' and tick % 3 == 0),
                )
                payloads.append(
                    {
                        'sample_id': str(uuid.uuid4()),
                        'server_id': str(srv.id),
                        'company_id': str(company.id),
                        'timestamp': now,
                        'received_at': now,
                        **sample,
                    }
                )
                heartbeats.append(
                    {
                        'server_id': srv.id,
                        'company_id': company.id,
                        'seen_at': now,
                        'ip_address': spec['ip_address'],
                        'os_info': spec['os_info'],
                    }
                )

            if payloads:
                push_batch_to_stream(payloads)
                record_heartbeats_batch(heartbeats)

            tick += 1
            if run_once:
                break
            time.sleep(interval)
