from datetime import timedelta
from django.db.models import Avg, Count, StdDev
from django.utils import timezone
from telemetry.models import MetricLog

_METRIC_SPECS = (
    ('cpu', 'CPU', 'cpu_usage', 5.0, 15.0, '%'),
    ('ram', 'RAM', 'ram_usage', 5.0, 15.0, '%'),
    ('disk', 'Disk', 'disk_usage', 3.0, 10.0, '%'),
    ('load', 'Load 1m', 'load_1m', 0.5, 1.0, ''),
)

MIN_BASELINE_SAMPLES = 6
Z_SCORE_THRESHOLD = 2.5


def compute_server_anomalies(company_id, server_ids, now=None) -> dict[str, list[dict]]:
    if not company_id or not server_ids:
        return {}

    now = now or timezone.now()
    recent_start = now - timedelta(minutes=15)
    baseline_start = now - timedelta(hours=24)

    baseline_rows = (
        MetricLog.unscoped.filter(
            company_id=company_id,
            server_id__in=server_ids,
            timestamp__gte=baseline_start,
            timestamp__lt=recent_start,
        )
        .values('server_id')
        .annotate(
            n=Count('id'),
            cpu_avg=Avg('cpu_usage'),
            cpu_std=StdDev('cpu_usage'),
            ram_avg=Avg('ram_usage'),
            ram_std=StdDev('ram_usage'),
            disk_avg=Avg('disk_usage'),
            disk_std=StdDev('disk_usage'),
            load_avg=Avg('load_1m'),
            load_std=StdDev('load_1m'),
        )
    )
    baseline_map = {str(row['server_id']): row for row in baseline_rows if (row.get('n') or 0) >= MIN_BASELINE_SAMPLES}
    if not baseline_map:
        return {}

    recent_rows = (
        MetricLog.unscoped.filter(
            company_id=company_id,
            server_id__in=server_ids,
            timestamp__gte=recent_start,
            timestamp__lte=now,
        )
        .values('server_id')
        .annotate(
            cpu_cur=Avg('cpu_usage'),
            ram_cur=Avg('ram_usage'),
            disk_cur=Avg('disk_usage'),
            load_cur=Avg('load_1m'),
        )
    )

    anomalies: dict[str, list[dict]] = {}
    for row in recent_rows:
        key = str(row['server_id'])
        base = baseline_map.get(key)
        if not base:
            continue
        hints = []
        for metric_key, label, _col, min_std, min_delta, unit in _METRIC_SPECS:
            cur_val = row.get(f'{metric_key}_cur')
            base_avg = base.get(f'{metric_key}_avg')
            base_std = base.get(f'{metric_key}_std')
            if cur_val is None or base_avg is None:
                continue
            delta = float(cur_val) - float(base_avg)
            if delta < min_delta:
                continue
            denom = max(float(base_std or 0.0), min_std)
            z_score = delta / denom
            if z_score >= Z_SCORE_THRESHOLD:
                hints.append(
                    {
                        'metric': metric_key,
                        'label': label,
                        'current': round(float(cur_val), 1),
                        'baseline': round(float(base_avg), 1),
                        'z_score': round(z_score, 2),
                        'message': f'{label} is {float(cur_val):.1f}{unit} vs {float(base_avg):.1f}{unit} baseline',
                    }
                )
        if hints:
            anomalies[key] = hints

    return anomalies
