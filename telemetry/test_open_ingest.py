import gzip
import json
import struct
from unittest.mock import patch
import pytest
from rest_framework.test import APIClient
from accounts.models import Company, User
from monitoring.models import AgentKey, Server
from telemetry.open_ingest import snappy_compress_literals


def _encode_varint(value: int) -> bytes:
    if value < 0:
        value += 1 << 64
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def _encode_len(field_num: int, payload: bytes) -> bytes:
    return _encode_varint((field_num << 3) | 2) + _encode_varint(len(payload)) + payload


def _build_prom_write_request(series_specs: list[tuple[dict[str, str], list[tuple[float, int]]]]) -> bytes:
    out = bytearray()
    for labels, samples in series_specs:
        ts_buf = bytearray()
        for k, v in labels.items():
            lbl_buf = _encode_len(1, k.encode('utf-8')) + _encode_len(2, v.encode('utf-8'))
            ts_buf.extend(_encode_len(1, lbl_buf))
        for val, ts_ms in samples:
            smp_buf = (
                _encode_varint((1 << 3) | 1)
                + struct.pack('<d', val)
                + _encode_varint((2 << 3) | 0)
                + _encode_varint(ts_ms)
            )
            ts_buf.extend(_encode_len(2, smp_buf))
        out.extend(_encode_len(1, bytes(ts_buf)))
    return bytes(out)


@pytest.mark.django_db
def test_otlp_http_metrics_ingest_and_cross_tenant_rejection():
    company_a = Company.objects.create(name='OTel Co A')
    company_b = Company.objects.create(name='OTel Co B')
    admin_a = User.objects.create_user(username='otel_a', password='Password123!', company=company_a, role='admin')
    srv_a = Server.unscoped.create(company=company_a, name='otel-node-1', hostname='otel-node-1.local')
    srv_b = Server.unscoped.create(company=company_b, name='other-node-2', hostname='other-node-2.local')

    otlp_body = {
        'resourceMetrics': [
            {
                'resource': {'attributes': [{'key': 'host.name', 'value': {'stringValue': 'otel-node-1.local'}}]},
                'scopeMetrics': [
                    {
                        'metrics': [
                            {
                                'name': 'system.cpu.utilization',
                                'gauge': {'dataPoints': [{'asDouble': 0.64, 'timeUnixNano': '1764259200000000000'}]},
                            },
                            {
                                'name': 'system.memory.utilization',
                                'gauge': {'dataPoints': [{'asDouble': 0.72, 'timeUnixNano': '1764259200000000000'}]},
                            },
                            {
                                'name': 'system.filesystem.utilization',
                                'gauge': {'dataPoints': [{'asDouble': 0.41, 'timeUnixNano': '1764259200000000000'}]},
                            },
                            {
                                'name': 'system.cpu.load_average.1m',
                                'gauge': {'dataPoints': [{'asDouble': 1.85, 'timeUnixNano': '1764259200000000000'}]},
                            },
                        ]
                    }
                ],
            }
        ]
    }

    anon = APIClient()
    assert anon.post('/api/telemetry/otlp/v1/metrics', data=otlp_body, format='json').status_code == 401

    client_a = APIClient()
    client_a.force_authenticate(user=admin_a)

    cross = client_a.post(
        '/api/telemetry/otlp/v1/metrics',
        data=otlp_body,
        format='json',
        HTTP_X_SERVER_ID=str(srv_b.id),
    )
    assert cross.status_code == 403

    gz_body = gzip.compress(json.dumps(otlp_body).encode('utf-8'))
    with (
        patch('telemetry.views.push_batch_to_stream') as mock_push,
        patch('telemetry.views.record_heartbeats_batch') as mock_hb,
    ):
        resp = client_a.post(
            '/api/telemetry/otlp/v1/metrics',
            data=gz_body,
            content_type='application/json',
            HTTP_CONTENT_ENCODING='gzip',
        )
    assert resp.status_code == 200
    assert resp.data['accepted'] == 1
    batch = mock_push.call_args[0][0]
    assert len(batch) == 1
    assert batch[0]['server_id'] == str(srv_a.id)
    assert batch[0]['company_id'] == str(company_a.id)
    assert batch[0]['cpu_usage'] == 64.0
    assert batch[0]['ram_usage'] == 72.0
    assert batch[0]['disk_usage'] == 41.0
    assert batch[0]['load_1m'] == 1.85
    assert mock_hb.called


@pytest.mark.django_db
def test_prometheus_remote_write_snappy_ingest_with_agent_key():
    company = Company.objects.create(name='Prom Co')
    srv = Server.unscoped.create(company=company, name='prom-node-1')
    _, raw_key = AgentKey.generate(server=srv)

    ts_ms = 1764259200000
    proto = _build_prom_write_request(
        [
            ({'__name__': 'cpu_usage'}, [(48.5, ts_ms)]),
            ({'__name__': 'node_memory_MemTotal_bytes'}, [(1000.0, ts_ms)]),
            ({'__name__': 'node_memory_MemAvailable_bytes'}, [(250.0, ts_ms)]),
            ({'__name__': 'node_load1'}, [(2.25, ts_ms)]),
        ]
    )
    snappy_body = snappy_compress_literals(proto)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'AgentKey {raw_key}')

    bad_resp = client.post(
        '/api/telemetry/prometheus/remote-write',
        data=b'\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff',
        content_type='application/x-protobuf',
        HTTP_CONTENT_ENCODING='snappy',
    )
    assert bad_resp.status_code == 400

    with (
        patch('telemetry.views.push_batch_to_stream') as mock_push,
        patch('telemetry.views.record_heartbeats_batch') as mock_hb,
    ):
        resp = client.post(
            '/api/telemetry/prometheus/remote-write',
            data=snappy_body,
            content_type='application/x-protobuf',
            HTTP_CONTENT_ENCODING='snappy',
        )
    assert resp.status_code == 204
    batch = mock_push.call_args[0][0]
    assert len(batch) == 1
    assert batch[0]['server_id'] == str(srv.id)
    assert batch[0]['cpu_usage'] == 48.5
    assert batch[0]['ram_usage'] == 75.0
    assert batch[0]['load_1m'] == 2.25
    assert mock_hb.called
