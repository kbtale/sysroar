from collections import defaultdict
from datetime import datetime, timezone as dt_timezone
import gzip
import struct
import uuid
from django.utils import timezone

MAX_COMPRESSED_BYTES = 4 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 8 * 1024 * 1024


class OpenIngestError(ValueError):
    pass


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    length = len(buf)
    while pos < length:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, pos
        shift += 7
        if shift > 63:
            raise OpenIngestError('Varint overflow.')
    raise OpenIngestError('Truncated varint.')


def snappy_decompress(data: bytes, max_output_bytes: int = MAX_DECOMPRESSED_BYTES) -> bytes:
    if not data:
        raise OpenIngestError('Empty snappy payload.')
    uncompressed_len, pos = _read_varint(data, 0)
    if uncompressed_len > max_output_bytes:
        raise OpenIngestError('Decompressed payload exceeds size limit.')

    out = bytearray()
    total = len(data)
    while pos < total:
        tag = data[pos]
        pos += 1
        tag_type = tag & 0x03
        if tag_type == 0:
            length_code = tag >> 2
            if length_code < 60:
                lit_len = length_code + 1
            else:
                extra = length_code - 59
                if pos + extra > total:
                    raise OpenIngestError('Truncated snappy literal length.')
                lit_len = int.from_bytes(data[pos : pos + extra], 'little') + 1
                pos += extra
            if pos + lit_len > total:
                raise OpenIngestError('Truncated snappy literal data.')
            if len(out) + lit_len > max_output_bytes:
                raise OpenIngestError('Decompressed payload exceeds size limit.')
            out.extend(data[pos : pos + lit_len])
            pos += lit_len
        else:
            if tag_type == 1:
                if pos >= total:
                    raise OpenIngestError('Truncated snappy 1-byte copy.')
                copy_len = ((tag >> 2) & 0x07) + 4
                offset = ((tag & 0xE0) << 3) | data[pos]
                pos += 1
            elif tag_type == 2:
                if pos + 2 > total:
                    raise OpenIngestError('Truncated snappy 2-byte copy.')
                copy_len = (tag >> 2) + 1
                offset = int.from_bytes(data[pos : pos + 2], 'little')
                pos += 2
            else:
                if pos + 4 > total:
                    raise OpenIngestError('Truncated snappy 4-byte copy.')
                copy_len = (tag >> 2) + 1
                offset = int.from_bytes(data[pos : pos + 4], 'little')
                pos += 4

            if offset == 0 or offset > len(out):
                raise OpenIngestError('Invalid snappy copy offset.')
            if len(out) + copy_len > max_output_bytes:
                raise OpenIngestError('Decompressed payload exceeds size limit.')
            start = len(out) - offset
            if copy_len <= offset:
                out.extend(out[start : start + copy_len])
            else:
                for idx in range(copy_len):
                    out.append(out[start + idx])

    if len(out) != uncompressed_len:
        raise OpenIngestError('Snappy output length mismatch.')
    return bytes(out)


def snappy_compress_literals(raw: bytes) -> bytes:
    out = bytearray()
    n = len(raw)
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            break

    pos = 0
    total = len(raw)
    while pos < total:
        chunk = raw[pos : pos + 65536]
        length = len(chunk)
        if length <= 60:
            out.append((length - 1) << 2)
        else:
            count = length - 1
            extra_bytes = (count.bit_length() + 7) // 8
            out.append((59 + extra_bytes) << 2)
            out.extend(count.to_bytes(extra_bytes, 'little'))
        out.extend(chunk)
        pos += length
    return bytes(out)


def _skip_proto_field(buf: bytes, pos: int, wire_type: int) -> int:
    if wire_type == 0:
        _, pos = _read_varint(buf, pos)
        return pos
    if wire_type == 1:
        if pos + 8 > len(buf):
            raise OpenIngestError('Truncated fixed64 field.')
        return pos + 8
    if wire_type == 2:
        size, pos = _read_varint(buf, pos)
        if pos + size > len(buf):
            raise OpenIngestError('Truncated length-delimited field.')
        return pos + size
    if wire_type == 5:
        if pos + 4 > len(buf):
            raise OpenIngestError('Truncated fixed32 field.')
        return pos + 4
    raise OpenIngestError(f'Unsupported protobuf wire type {wire_type}.')


def _decode_prom_label(buf: bytes) -> tuple[str, str]:
    pos = 0
    end = len(buf)
    name = ''
    value = ''
    while pos < end:
        key, pos = _read_varint(buf, pos)
        field_num = key >> 3
        wire_type = key & 0x07
        if field_num in (1, 2) and wire_type == 2:
            size, pos = _read_varint(buf, pos)
            if pos + size > end:
                raise OpenIngestError('Truncated label string.')
            text = buf[pos : pos + size].decode('utf-8', errors='replace')
            pos += size
            if field_num == 1:
                name = text
            else:
                value = text
        else:
            pos = _skip_proto_field(buf, pos, wire_type)
    return name, value


def _decode_prom_sample(buf: bytes) -> tuple[float, int]:
    pos = 0
    end = len(buf)
    value = 0.0
    ts_ms = 0
    while pos < end:
        key, pos = _read_varint(buf, pos)
        field_num = key >> 3
        wire_type = key & 0x07
        if field_num == 1 and wire_type == 1:
            if pos + 8 > end:
                raise OpenIngestError('Truncated sample double.')
            value = struct.unpack('<d', buf[pos : pos + 8])[0]
            pos += 8
        elif field_num == 2 and wire_type == 0:
            raw_ts, pos = _read_varint(buf, pos)
            if raw_ts >= (1 << 63):
                raw_ts -= 1 << 64
            ts_ms = raw_ts
        else:
            pos = _skip_proto_field(buf, pos, wire_type)
    return value, ts_ms


def _decode_prom_timeseries(buf: bytes) -> tuple[dict[str, str], list[tuple[float, int]]]:
    pos = 0
    end = len(buf)
    labels: dict[str, str] = {}
    samples: list[tuple[float, int]] = []
    while pos < end:
        key, pos = _read_varint(buf, pos)
        field_num = key >> 3
        wire_type = key & 0x07
        if field_num == 1 and wire_type == 2:
            size, pos = _read_varint(buf, pos)
            if pos + size > end:
                raise OpenIngestError('Truncated label message.')
            lname, lval = _decode_prom_label(buf[pos : pos + size])
            if lname:
                labels[lname] = lval
            pos += size
        elif field_num == 2 and wire_type == 2:
            size, pos = _read_varint(buf, pos)
            if pos + size > end:
                raise OpenIngestError('Truncated sample message.')
            samples.append(_decode_prom_sample(buf[pos : pos + size]))
            pos += size
        else:
            pos = _skip_proto_field(buf, pos, wire_type)
    return labels, samples


def decode_prometheus_write_request(buf: bytes) -> list[tuple[dict[str, str], list[tuple[float, int]]]]:
    pos = 0
    end = len(buf)
    series: list[tuple[dict[str, str], list[tuple[float, int]]]] = []
    while pos < end:
        key, pos = _read_varint(buf, pos)
        field_num = key >> 3
        wire_type = key & 0x07
        if field_num == 1 and wire_type == 2:
            size, pos = _read_varint(buf, pos)
            if pos + size > end:
                raise OpenIngestError('Truncated timeseries message.')
            series.append(_decode_prom_timeseries(buf[pos : pos + size]))
            pos += size
        else:
            pos = _skip_proto_field(buf, pos, wire_type)
    return series


def _clamp_pct(val: float, scale_unit: bool = False) -> float:
    if scale_unit and 0.0 <= val <= 1.0:
        val *= 100.0
    return round(max(0.0, min(100.0, float(val))), 2)


def _attr_map(attrs: list | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(attrs, list):
        return out
    for item in attrs:
        if not isinstance(item, dict):
            continue
        key = item.get('key')
        val_obj = item.get('value')
        if not key or not isinstance(val_obj, dict):
            continue
        for vkey in ('stringValue', 'intValue', 'doubleValue', 'boolValue'):
            if vkey in val_obj:
                out[str(key)] = str(val_obj[vkey])
                break
    return out


def _dp_value(dp: dict) -> float | None:
    if 'asDouble' in dp and dp['asDouble'] is not None:
        return float(dp['asDouble'])
    if 'asInt' in dp and dp['asInt'] is not None:
        return float(dp['asInt'])
    return None


def _dp_timestamp(dp: dict, default_now: datetime) -> datetime:
    raw = dp.get('timeUnixNano')
    if raw:
        try:
            ns = int(raw)
            if ns > 0:
                return datetime.fromtimestamp(ns / 1_000_000_000.0, tz=dt_timezone.utc)
        except (ValueError, TypeError, OverflowError):
            pass
    return default_now


def parse_otlp_metrics_json(payload: dict, default_now: datetime | None = None) -> list[dict]:
    if not isinstance(payload, dict):
        raise OpenIngestError('OTLP payload must be a JSON object.')
    resource_metrics = payload.get('resourceMetrics')
    if not isinstance(resource_metrics, list):
        raise OpenIngestError('Missing resourceMetrics array.')

    now = default_now or timezone.now()
    buckets: dict[tuple[str, int], dict] = defaultdict(dict)

    for rm in resource_metrics:
        if not isinstance(rm, dict):
            continue
        res_attrs = _attr_map((rm.get('resource') or {}).get('attributes'))
        host_hint = (
            res_attrs.get('sysroar.server_id')
            or res_attrs.get('host.name')
            or res_attrs.get('service.instance.id')
            or ''
        )
        for sm in rm.get('scopeMetrics') or []:
            if not isinstance(sm, dict):
                continue
            for metric in sm.get('metrics') or []:
                if not isinstance(metric, dict):
                    continue
                name = str(metric.get('name') or '').strip().lower()
                container = metric.get('gauge') or metric.get('sum') or {}
                dps = container.get('dataPoints') if isinstance(container, dict) else None
                if not isinstance(dps, list):
                    continue
                for dp in dps:
                    if not isinstance(dp, dict):
                        continue
                    val = _dp_value(dp)
                    if val is None:
                        continue
                    ts = _dp_timestamp(dp, now)
                    dp_attrs = _attr_map(dp.get('attributes'))
                    target_hint = dp_attrs.get('sysroar.server_id') or host_hint
                    bucket_key = (target_hint, int(ts.timestamp()))
                    entry = buckets[bucket_key]
                    entry.setdefault('host_hint', target_hint)
                    entry.setdefault('timestamp', ts)

                    if name in ('system.cpu.utilization', 'cpu.utilization', 'cpu_usage'):
                        entry['cpu_usage'] = _clamp_pct(val, scale_unit=name != 'cpu_usage')
                    elif name in ('system.memory.utilization', 'memory.utilization', 'ram_usage'):
                        entry['ram_usage'] = _clamp_pct(val, scale_unit=name != 'ram_usage')
                    elif name in ('system.filesystem.utilization', 'disk.utilization', 'disk_usage'):
                        entry['disk_usage'] = _clamp_pct(val, scale_unit=name != 'disk_usage')
                    elif name in ('system.paging.utilization', 'swap_usage'):
                        entry['swap_usage'] = _clamp_pct(val, scale_unit=name != 'swap_usage')
                    elif name in ('system.cpu.load_average.1m', 'load_1m'):
                        entry['load_1m'] = round(max(0.0, val), 3)
                    elif name in ('system.network.io', 'net_rx_bps', 'net_tx_bps'):
                        direction = dp_attrs.get('network.io.direction', '').lower()
                        if name == 'net_tx_bps' or direction == 'transmit':
                            entry['net_tx_bps'] = round(max(0.0, val), 2)
                        else:
                            entry['net_rx_bps'] = round(max(0.0, val), 2)
                    elif name in ('system.disk.io', 'disk_read_bps', 'disk_write_bps'):
                        direction = dp_attrs.get('disk.io.direction', '').lower()
                        if name == 'disk_write_bps' or direction == 'write':
                            entry['disk_write_bps'] = round(max(0.0, val), 2)
                        else:
                            entry['disk_read_bps'] = round(max(0.0, val), 2)

    samples = []
    for entry in buckets.values():
        if any(
            k in entry
            for k in (
                'cpu_usage',
                'ram_usage',
                'disk_usage',
                'load_1m',
                'swap_usage',
                'net_rx_bps',
                'net_tx_bps',
                'disk_read_bps',
                'disk_write_bps',
            )
        ):
            entry.setdefault('cpu_usage', 0.0)
            entry.setdefault('ram_usage', 0.0)
            samples.append(entry)
    return samples


def parse_prometheus_remote_write(raw_body: bytes, content_encoding: str = '', default_now=None) -> list[dict]:
    if len(raw_body) > MAX_COMPRESSED_BYTES:
        raise OpenIngestError('Compressed payload exceeds size limit.')
    enc = (content_encoding or '').strip().lower()
    if enc == 'gzip':
        proto_bytes = gzip.decompress(raw_body)
    elif enc in ('', 'snappy'):
        proto_bytes = snappy_decompress(raw_body)
    else:
        proto_bytes = raw_body

    if len(proto_bytes) > MAX_DECOMPRESSED_BYTES:
        raise OpenIngestError('Decompressed payload exceeds size limit.')

    series_list = decode_prometheus_write_request(proto_bytes)
    now = default_now or timezone.now()
    buckets: dict[tuple[str, int], dict] = defaultdict(dict)
    mem_totals: dict[tuple[str, int], float] = {}
    mem_avails: dict[tuple[str, int], float] = {}
    fs_sizes: dict[tuple[str, int], float] = {}
    fs_avails: dict[tuple[str, int], float] = {}

    for labels, samples in series_list:
        metric_name = (labels.get('__name__') or '').strip()
        if not metric_name:
            continue
        host_hint = labels.get('sysroar_server_id') or labels.get('host') or labels.get('instance') or ''
        for val, ts_ms in samples:
            if ts_ms > 0:
                ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=dt_timezone.utc)
            else:
                ts = now
            bkey = (host_hint, int(ts.timestamp()))
            entry = buckets[bkey]
            entry.setdefault('host_hint', host_hint)
            entry.setdefault('timestamp', ts)

            lower = metric_name.lower()
            if lower in ('cpu_usage', 'system_cpu_utilization', 'node_cpu_utilization'):
                entry['cpu_usage'] = _clamp_pct(val, scale_unit='utilization' in lower)
            elif lower in ('ram_usage', 'system_memory_utilization', 'node_memory_utilization'):
                entry['ram_usage'] = _clamp_pct(val, scale_unit='utilization' in lower)
            elif lower == 'node_memory_memtotal_bytes':
                mem_totals[bkey] = max(0.0, float(val))
            elif lower == 'node_memory_memavailable_bytes':
                mem_avails[bkey] = max(0.0, float(val))
            elif lower in ('disk_usage', 'system_filesystem_utilization', 'node_filesystem_utilization'):
                entry['disk_usage'] = _clamp_pct(val, scale_unit='utilization' in lower)
            elif lower == 'node_filesystem_size_bytes':
                fs_sizes[bkey] = max(0.0, float(val))
            elif lower == 'node_filesystem_avail_bytes':
                fs_avails[bkey] = max(0.0, float(val))
            elif lower in ('node_load1', 'load_1m', 'system_cpu_load_average_1m'):
                entry['load_1m'] = round(max(0.0, float(val)), 3)
            elif lower in ('swap_usage', 'system_swap_utilization'):
                entry['swap_usage'] = _clamp_pct(val, scale_unit='utilization' in lower)
            elif lower in ('net_rx_bps', 'node_network_receive_bytes_total'):
                entry['net_rx_bps'] = round(max(0.0, float(val)), 2)
            elif lower in ('net_tx_bps', 'node_network_transmit_bytes_total'):
                entry['net_tx_bps'] = round(max(0.0, float(val)), 2)

    for bkey, total in mem_totals.items():
        if total > 0 and bkey in mem_avails and 'ram_usage' not in buckets[bkey]:
            used_pct = ((total - mem_avails[bkey]) / total) * 100.0
            buckets[bkey]['ram_usage'] = _clamp_pct(used_pct)

    for bkey, total in fs_sizes.items():
        if total > 0 and bkey in fs_avails and 'disk_usage' not in buckets[bkey]:
            used_pct = ((total - fs_avails[bkey]) / total) * 100.0
            buckets[bkey]['disk_usage'] = _clamp_pct(used_pct)

    out = []
    for entry in buckets.values():
        if any(
            k in entry
            for k in ('cpu_usage', 'ram_usage', 'disk_usage', 'load_1m', 'swap_usage', 'net_rx_bps', 'net_tx_bps')
        ):
            entry.setdefault('cpu_usage', 0.0)
            entry.setdefault('ram_usage', 0.0)
            out.append(entry)
    return out


def resolve_open_ingest_server(request, company_id, host_hint: str = ''):
    from monitoring.models import Server

    agent_key = getattr(request, 'auth', None)
    bound_server_id = getattr(agent_key, 'server_id', None)
    header_server_id = (request.headers.get('X-Server-ID') or '').strip()

    if bound_server_id is not None:
        if header_server_id and str(bound_server_id) != header_server_id:
            return None, 'X-Server-ID does not match bound agent key server.'
        srv = Server.unscoped.filter(id=bound_server_id, company_id=company_id, is_active=True).first()
        return srv, ('' if srv else 'Server not found or access denied.')

    if header_server_id:
        try:
            uid = uuid.UUID(header_server_id)
        except ValueError:
            return None, 'Invalid X-Server-ID UUID.'
        srv = Server.unscoped.filter(id=uid, company_id=company_id, is_active=True).first()
        return srv, ('' if srv else 'Server not found or access denied.')

    hint = (host_hint or '').strip()
    if hint:
        try:
            uid = uuid.UUID(hint)
            srv = Server.unscoped.filter(id=uid, company_id=company_id, is_active=True).first()
            if srv:
                return srv, ''
        except ValueError:
            pass
        host_base = hint.split(':', 1)[0]
        srv = Server.unscoped.filter(company_id=company_id, is_active=True, hostname__iexact=host_base).first()
        if srv is None:
            srv = Server.unscoped.filter(company_id=company_id, is_active=True, name__iexact=host_base).first()
        if srv:
            return srv, ''

    return None, 'Unable to resolve target server. Provide X-Server-ID header or matching host.name.'
