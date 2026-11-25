import uuid
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

CREATE_EXTENSION_SQL = 'CREATE EXTENSION IF NOT EXISTS timescaledb;'

CONVERT_TO_HYPERTABLE_SQL = """
ALTER TABLE telemetry_metriclog DROP CONSTRAINT telemetry_metriclog_pkey;
ALTER TABLE telemetry_metriclog ADD PRIMARY KEY (server_id, timestamp);
SELECT create_hypertable(
    'telemetry_metriclog',
    'timestamp',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);
"""

ENABLE_COMPRESSION_AND_RETENTION_SQL = """
ALTER TABLE telemetry_metriclog SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'company_id, server_id',
    timescaledb.compress_orderby = 'timestamp DESC'
);
SELECT add_compression_policy('telemetry_metriclog', INTERVAL '1 day', if_not_exists => TRUE);
SELECT add_retention_policy('telemetry_metriclog', INTERVAL '14 days', if_not_exists => TRUE);
"""

CREATE_CAGG_1M_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_metric_1m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', timestamp) AS bucket,
    company_id,
    server_id,
    COUNT(*) AS sample_count,
    AVG(cpu_usage) AS avg_cpu,
    MIN(cpu_usage) AS min_cpu,
    MAX(cpu_usage) AS max_cpu,
    AVG(ram_usage) AS avg_ram,
    MIN(ram_usage) AS min_ram,
    MAX(ram_usage) AS max_ram,
    AVG(disk_io) AS avg_disk_io,
    MIN(disk_io) AS min_disk_io,
    MAX(disk_io) AS max_disk_io,
    AVG(disk_usage) AS avg_disk_usage,
    MAX(disk_usage) AS max_disk_usage,
    AVG(load_1m) AS avg_load_1m,
    MAX(load_1m) AS max_load_1m,
    AVG(net_rx_bps) AS avg_net_rx_bps,
    MAX(net_rx_bps) AS max_net_rx_bps,
    AVG(net_tx_bps) AS avg_net_tx_bps,
    MAX(net_tx_bps) AS max_net_tx_bps
FROM telemetry_metriclog
GROUP BY bucket, company_id, server_id
WITH NO DATA;
SELECT add_continuous_aggregate_policy(
    'telemetry_metric_1m',
    start_offset => INTERVAL '1 hour',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE
);
"""

CREATE_CAGG_1H_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_metric_1h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', timestamp) AS bucket,
    company_id,
    server_id,
    COUNT(*) AS sample_count,
    AVG(cpu_usage) AS avg_cpu,
    MIN(cpu_usage) AS min_cpu,
    MAX(cpu_usage) AS max_cpu,
    AVG(ram_usage) AS avg_ram,
    MIN(ram_usage) AS min_ram,
    MAX(ram_usage) AS max_ram,
    AVG(disk_io) AS avg_disk_io,
    MIN(disk_io) AS min_disk_io,
    MAX(disk_io) AS max_disk_io,
    AVG(disk_usage) AS avg_disk_usage,
    MAX(disk_usage) AS max_disk_usage,
    AVG(load_1m) AS avg_load_1m,
    MAX(load_1m) AS max_load_1m,
    AVG(net_rx_bps) AS avg_net_rx_bps,
    MAX(net_rx_bps) AS max_net_rx_bps,
    AVG(net_tx_bps) AS avg_net_tx_bps,
    MAX(net_tx_bps) AS max_net_tx_bps
FROM telemetry_metriclog
GROUP BY bucket, company_id, server_id
WITH NO DATA;
SELECT add_continuous_aggregate_policy(
    'telemetry_metric_1h',
    start_offset => INTERVAL '1 day',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '15 minutes',
    if_not_exists => TRUE
);
"""

CREATE_CAGG_1D_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_metric_1d
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', timestamp) AS bucket,
    company_id,
    server_id,
    COUNT(*) AS sample_count,
    AVG(cpu_usage) AS avg_cpu,
    MIN(cpu_usage) AS min_cpu,
    MAX(cpu_usage) AS max_cpu,
    AVG(ram_usage) AS avg_ram,
    MIN(ram_usage) AS min_ram,
    MAX(ram_usage) AS max_ram,
    AVG(disk_io) AS avg_disk_io,
    MIN(disk_io) AS min_disk_io,
    MAX(disk_io) AS max_disk_io,
    AVG(disk_usage) AS avg_disk_usage,
    MAX(disk_usage) AS max_disk_usage,
    AVG(load_1m) AS avg_load_1m,
    MAX(load_1m) AS max_load_1m,
    AVG(net_rx_bps) AS avg_net_rx_bps,
    MAX(net_rx_bps) AS max_net_rx_bps,
    AVG(net_tx_bps) AS avg_net_tx_bps,
    MAX(net_tx_bps) AS max_net_tx_bps
FROM telemetry_metriclog
GROUP BY bucket, company_id, server_id
WITH NO DATA;
SELECT add_continuous_aggregate_policy(
    'telemetry_metric_1d',
    start_offset => INTERVAL '7 days',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);
"""


class Migration(migrations.Migration):
    initial = True
    atomic = False

    dependencies = [
        ('accounts', '0001_initial'),
        ('monitoring', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(CREATE_EXTENSION_SQL, reverse_sql=migrations.RunSQL.noop),
        migrations.CreateModel(
            name='MetricLog',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('sample_id', models.UUIDField(blank=True, null=True)),
                ('timestamp', models.DateTimeField(db_index=True)),
                ('received_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('cpu_usage', models.FloatField()),
                ('ram_usage', models.FloatField()),
                ('disk_io', models.FloatField(blank=True, null=True)),
                ('swap_usage', models.FloatField(blank=True, null=True)),
                ('disk_usage', models.FloatField(blank=True, null=True)),
                ('disk_read_bps', models.FloatField(blank=True, null=True)),
                ('disk_write_bps', models.FloatField(blank=True, null=True)),
                ('net_rx_bps', models.FloatField(blank=True, null=True)),
                ('net_tx_bps', models.FloatField(blank=True, null=True)),
                ('load_1m', models.FloatField(blank=True, null=True)),
                ('uptime_seconds', models.BigIntegerField(blank=True, null=True)),
                ('details', models.JSONField(blank=True, default=dict)),
                (
                    'company',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='%(class)s_data',
                        to='accounts.company',
                    ),
                ),
                (
                    'server',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='metrics',
                        to='monitoring.server',
                    ),
                ),
            ],
            options={
                'ordering': ['-timestamp'],
                'indexes': [
                    models.Index(fields=['company', 'server', 'timestamp'], name='telemetry_m_company_9aec1f_idx'),
                    models.Index(fields=['server', 'timestamp'], name='telemetry_m_server__edd1e2_idx'),
                ],
            },
        ),
        migrations.RunSQL(CONVERT_TO_HYPERTABLE_SQL, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(ENABLE_COMPRESSION_AND_RETENTION_SQL, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(
            CREATE_CAGG_1M_SQL,
            reverse_sql='DROP MATERIALIZED VIEW IF EXISTS telemetry_metric_1m CASCADE;',
        ),
        migrations.RunSQL(
            CREATE_CAGG_1H_SQL,
            reverse_sql='DROP MATERIALIZED VIEW IF EXISTS telemetry_metric_1h CASCADE;',
        ),
        migrations.RunSQL(
            CREATE_CAGG_1D_SQL,
            reverse_sql='DROP MATERIALIZED VIEW IF EXISTS telemetry_metric_1d CASCADE;',
        ),
    ]
