import argparse
import concurrent.futures
import gzip
import json
import math
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
import requests


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil((pct / 100.0) * len(ordered)) - 1))
    return ordered[idx]


def build_batch_payload(server_id: str, batch_size: int, base_time: datetime) -> tuple[bytes, list[str]]:
    samples = []
    sample_ids = []
    for i in range(batch_size):
        sid = str(uuid.uuid4())
        sample_ids.append(sid)
        ts = base_time - timedelta(microseconds=(batch_size - i) * 100)
        samples.append(
            {
                'server': server_id,
                'sample_id': sid,
                'cpu_usage': float((i * 7) % 95 + 1),
                'ram_usage': float((i * 5) % 90 + 5),
                'swap_usage': 12.5,
                'disk_usage': 45.0,
                'disk_io': 2.5,
                'disk_read_bps': 102400.0,
                'disk_write_bps': 51200.0,
                'net_rx_bps': 204800.0,
                'net_tx_bps': 102400.0,
                'load_1m': 1.25,
                'uptime_seconds': 86400 + i,
                'timestamp': ts.isoformat(),
            }
        )
    raw = json.dumps({'samples': samples}).encode('utf-8')
    return gzip.compress(raw), sample_ids


def run_load_test(
    base_url: str,
    token: str,
    server_ids: list[str],
    target_rate: int,
    duration_seconds: float,
    batch_size: int,
    workers: int,
    timeout_seconds: float = 10.0,
) -> dict:
    endpoint = f'{base_url.rstrip("/")}/api/telemetry/ingest/batch/'
    batches_per_sec = max(target_rate / float(batch_size), 0.1)
    interval_per_worker = workers / batches_per_sec

    lock = threading.Lock()
    latencies_ms: list[float] = []
    accepted_samples = 0
    failed_requests = 0
    sent_sample_ids: list[str] = []
    server_counter = 0

    stop_at = time.monotonic() + duration_seconds
    started_at = time.monotonic()

    def next_server_id() -> str:
        nonlocal server_counter
        with lock:
            sid = server_ids[server_counter % len(server_ids)]
            server_counter += 1
            return sid

    def worker_loop(worker_index: int):
        nonlocal accepted_samples, failed_requests
        session = requests.Session()
        session.headers.update(
            {
                'Authorization': f'Token {token}',
                'Content-Type': 'application/json',
                'Content-Encoding': 'gzip',
            }
        )
        next_tick = started_at + (worker_index * (interval_per_worker / max(workers, 1)))
        while True:
            now_mono = time.monotonic()
            if now_mono >= stop_at:
                break
            sleep_for = next_tick - now_mono
            if sleep_for > 0:
                time.sleep(min(sleep_for, max(stop_at - now_mono, 0.0)))
                if time.monotonic() >= stop_at:
                    break
            next_tick = max(next_tick + interval_per_worker, time.monotonic())

            server_id = next_server_id()
            body, batch_ids = build_batch_payload(server_id, batch_size, datetime.now(timezone.utc))
            req_start = time.monotonic()
            try:
                resp = session.post(endpoint, data=body, timeout=timeout_seconds)
                elapsed_ms = (time.monotonic() - req_start) * 1000.0
                if resp.status_code == 202:
                    data = resp.json()
                    with lock:
                        latencies_ms.append(elapsed_ms)
                        accepted_samples += int(data.get('accepted', len(batch_ids)))
                        sent_sample_ids.extend(batch_ids)
                else:
                    with lock:
                        failed_requests += 1
            except requests.RequestException:
                with lock:
                    failed_requests += 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(worker_loop, idx) for idx in range(workers)]
        for future in futures:
            future.result()

    elapsed_total = max(time.monotonic() - started_at, 0.001)
    return {
        'elapsed_seconds': round(elapsed_total, 3),
        'accepted_samples': accepted_samples,
        'failed_requests': failed_requests,
        'achieved_rate': round(accepted_samples / elapsed_total, 2),
        'p50_http_ms': round(percentile(latencies_ms, 50), 2),
        'p95_http_ms': round(percentile(latencies_ms, 95), 2),
        'p99_http_ms': round(percentile(latencies_ms, 99), 2),
        'sample_ids': sent_sample_ids,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='SysRoar telemetry batch ingest load generator')
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--token', required=True)
    parser.add_argument('--server-ids', required=True, help='Comma-separated server UUIDs')
    parser.add_argument('--rate', type=int, default=600)
    parser.add_argument('--duration', type=float, default=15.0)
    parser.add_argument('--batch-size', type=int, default=100)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--min-rate', type=float, default=500.0)
    parser.add_argument('--max-p95-ms', type=float, default=5000.0)
    parser.add_argument('--sample-ids-out', default='')
    args = parser.parse_args(argv)

    server_ids = [sid.strip() for sid in args.server_ids.split(',') if sid.strip()]
    if not server_ids:
        print('At least one server ID is required', file=sys.stderr)
        return 2

    result = run_load_test(
        base_url=args.base_url,
        token=args.token,
        server_ids=server_ids,
        target_rate=args.rate,
        duration_seconds=args.duration,
        batch_size=args.batch_size,
        workers=args.workers,
    )

    if args.sample_ids_out:
        with open(args.sample_ids_out, 'w', encoding='utf-8') as handle:
            json.dump(result['sample_ids'], handle)

    summary = {k: v for k, v in result.items() if k != 'sample_ids'}
    print(json.dumps(summary, indent=2))

    if result['failed_requests'] > 0:
        return 1
    if result['achieved_rate'] < args.min_rate:
        return 1
    if result['p95_http_ms'] > args.max_p95_ms:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
