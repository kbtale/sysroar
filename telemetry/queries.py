from datetime import timedelta
from django.db import connection
from django.utils import timezone
from accounts.models import Company

_AGGREGATE_SQL_BY_BUCKET = {
    '1m': (
        'SELECT bucket, sample_count, '
        'avg_cpu, min_cpu, max_cpu, '
        'avg_ram, min_ram, max_ram, '
        'avg_disk_io, min_disk_io, max_disk_io, '
        'avg_disk_usage, max_disk_usage, '
        'avg_load_1m, max_load_1m, '
        'avg_net_rx_bps, max_net_rx_bps, '
        'avg_net_tx_bps, max_net_tx_bps '
        'FROM telemetry_metric_1m '
        'WHERE company_id = %s AND server_id = %s AND bucket >= %s AND bucket <= %s '
        'ORDER BY bucket ASC'
    ),
    '1h': (
        'SELECT bucket, sample_count, '
        'avg_cpu, min_cpu, max_cpu, '
        'avg_ram, min_ram, max_ram, '
        'avg_disk_io, min_disk_io, max_disk_io, '
        'avg_disk_usage, max_disk_usage, '
        'avg_load_1m, max_load_1m, '
        'avg_net_rx_bps, max_net_rx_bps, '
        'avg_net_tx_bps, max_net_tx_bps '
        'FROM telemetry_metric_1h '
        'WHERE company_id = %s AND server_id = %s AND bucket >= %s AND bucket <= %s '
        'ORDER BY bucket ASC'
    ),
    '1d': (
        'SELECT bucket, sample_count, '
        'avg_cpu, min_cpu, max_cpu, '
        'avg_ram, min_ram, max_ram, '
        'avg_disk_io, min_disk_io, max_disk_io, '
        'avg_disk_usage, max_disk_usage, '
        'avg_load_1m, max_load_1m, '
        'avg_net_rx_bps, max_net_rx_bps, '
        'avg_net_tx_bps, max_net_tx_bps '
        'FROM telemetry_metric_1d '
        'WHERE company_id = %s AND server_id = %s AND bucket >= %s AND bucket <= %s '
        'ORDER BY bucket ASC'
    ),
}

_INTERVAL_BY_BUCKET = {
    '1m': '1 minute',
    '1h': '1 hour',
    '1d': '1 day',
}


def _effective_start(company_id, start):
    retention_days = (
        Company.objects.filter(id=company_id).values_list('retention_days', flat=True).first()
        or 14
    )
    earliest_allowed = timezone.now() - timedelta(days=retention_days)
    if start is None or start < earliest_allowed:
        return earliest_allowed
    return start


def query_metric_aggregates(company_id, server_id, bucket='1m', start=None, end=None):
    sql = _AGGREGATE_SQL_BY_BUCKET.get(bucket)
    if sql is None:
        raise ValueError(f'Unsupported bucket: {bucket}')

    effective_start = _effective_start(company_id, start)
    effective_end = end or timezone.now()

    with connection.cursor() as cursor:
        cursor.execute(sql, [str(company_id), str(server_id), effective_start, effective_end])
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def query_metric_percentiles(company_id, server_id, bucket='1m', start=None, end=None):
    interval_str = _INTERVAL_BY_BUCKET.get(bucket)
    if interval_str is None:
        raise ValueError(f'Unsupported bucket: {bucket}')

    effective_start = _effective_start(company_id, start)
    effective_end = end or timezone.now()

    sql = (
        'SELECT time_bucket(%s::interval, timestamp) AS bucket, '
        'AVG(cpu_usage) AS avg_cpu, MIN(cpu_usage) AS min_cpu, MAX(cpu_usage) AS max_cpu, '
        'percentile_cont(0.95) WITHIN GROUP (ORDER BY cpu_usage) AS p95_cpu, '
        'AVG(ram_usage) AS avg_ram, MIN(ram_usage) AS min_ram, MAX(ram_usage) AS max_ram, '
        'percentile_cont(0.95) WITHIN GROUP (ORDER BY ram_usage) AS p95_ram, '
        'AVG(disk_io) AS avg_disk_io, MAX(disk_io) AS max_disk_io, '
        'percentile_cont(0.95) WITHIN GROUP (ORDER BY disk_io) AS p95_disk_io '
        'FROM telemetry_metriclog '
        'WHERE company_id = %s AND server_id = %s AND timestamp >= %s AND timestamp <= %s '
        'GROUP BY bucket ORDER BY bucket ASC'
    )

    with connection.cursor() as cursor:
        cursor.execute(sql, [interval_str, str(company_id), str(server_id), effective_start, effective_end])
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


RANGE_SPECS = {
    '15m': (timedelta(minutes=15), 'raw'),
    '1h': (timedelta(hours=1), '1 minute'),
    '6h': (timedelta(hours=6), '5 minutes'),
    '24h': (timedelta(hours=24), '15 minutes'),
    '7d': (timedelta(days=7), '1 hour'),
    '30d': (timedelta(days=30), '1 day'),
}


def _round_or_none(val):
    return round(float(val), 2) if val is not None else None


def query_server_metrics_range(company_id, server_id, range_key: str = '1h', now=None) -> dict:
    spec = RANGE_SPECS.get(range_key)
    if spec is None:
        raise ValueError(f'Unsupported range: {range_key}')

    delta, bucket_mode = spec
    end = now or timezone.now()
    start = end - delta

    if bucket_mode == 'raw':
        sql = (
            'SELECT timestamp AS bucket, cpu_usage AS avg_cpu, cpu_usage AS max_cpu, '
            'ram_usage AS avg_ram, ram_usage AS max_ram, swap_usage AS avg_swap, '
            'disk_usage AS avg_disk, disk_read_bps AS avg_disk_read_bps, '
            'disk_write_bps AS avg_disk_write_bps, net_rx_bps AS avg_net_rx_bps, '
            'net_tx_bps AS avg_net_tx_bps, load_1m AS avg_load_1m, uptime_seconds '
            'FROM telemetry_metriclog '
            'WHERE company_id = %s AND server_id = %s AND timestamp >= %s AND timestamp <= %s '
            'ORDER BY timestamp ASC LIMIT 600'
        )
        params = [str(company_id), str(server_id), start, end]
    else:
        sql = (
            'SELECT time_bucket(%s::interval, timestamp) AS bucket, '
            'AVG(cpu_usage) AS avg_cpu, MAX(cpu_usage) AS max_cpu, '
            'AVG(ram_usage) AS avg_ram, MAX(ram_usage) AS max_ram, '
            'AVG(swap_usage) AS avg_swap, AVG(disk_usage) AS avg_disk, '
            'AVG(disk_read_bps) AS avg_disk_read_bps, AVG(disk_write_bps) AS avg_disk_write_bps, '
            'AVG(net_rx_bps) AS avg_net_rx_bps, AVG(net_tx_bps) AS avg_net_tx_bps, '
            'AVG(load_1m) AS avg_load_1m, MAX(uptime_seconds) AS uptime_seconds '
            'FROM telemetry_metriclog '
            'WHERE company_id = %s AND server_id = %s AND timestamp >= %s AND timestamp <= %s '
            'GROUP BY bucket ORDER BY bucket ASC'
        )
        params = [bucket_mode, str(company_id), str(server_id), start, end]

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()

    points = [
        {
            'timestamp': row[0].isoformat(),
            'cpu': _round_or_none(row[1]),
            'max_cpu': _round_or_none(row[2]),
            'ram': _round_or_none(row[3]),
            'max_ram': _round_or_none(row[4]),
            'swap': _round_or_none(row[5]),
            'disk': _round_or_none(row[6]),
            'disk_read_bps': _round_or_none(row[7]),
            'disk_write_bps': _round_or_none(row[8]),
            'net_rx_bps': _round_or_none(row[9]),
            'net_tx_bps': _round_or_none(row[10]),
            'load_1m': _round_or_none(row[11]),
            'uptime_seconds': int(row[12]) if row[12] is not None else None,
        }
        for row in rows
    ]

    return {
        'server_id': str(server_id),
        'range': range_key,
        'bucket': bucket_mode,
        'start': start.isoformat(),
        'end': end.isoformat(),
        'points': points,
    }
