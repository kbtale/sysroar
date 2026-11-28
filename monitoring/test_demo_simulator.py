from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch
import pytest
from django.core.management import call_command
from accounts.models import User
from monitoring.management.commands.run_demo_simulator import (
    DEMO_COMPANY_NAME,
    DEMO_SERVER_SPECS,
    DEMO_USERNAME,
    DemoNoise,
    generate_demo_sample,
    is_flapping_offline,
    seed_demo_environment,
)
from monitoring.models import AlertRule, Server, StatusPage, UptimeCheck
from telemetry.models import MetricLog


@pytest.mark.django_db
def test_demo_simulator_seeds_idempotently_and_streams_batch():
    company, pairs = seed_demo_environment(backfill_hours=1)
    assert company.name == DEMO_COMPANY_NAME
    assert len(pairs) == 10
    assert User.objects.filter(username=DEMO_USERNAME, company=company).exists()
    assert Server.unscoped.filter(company=company).count() == 10
    assert AlertRule.unscoped.filter(company=company).count() == 2
    assert UptimeCheck.unscoped.filter(company=company).count() == 3
    assert StatusPage.unscoped.filter(company=company, slug='demo', is_public=True).exists()
    initial_metrics = MetricLog.unscoped.filter(company=company).count()
    assert initial_metrics >= 90

    company_again, pairs_again = seed_demo_environment(backfill_hours=1)
    assert company_again.id == company.id
    assert len(pairs_again) == 10
    assert Server.unscoped.filter(company=company).count() == 10

    with (
        patch('monitoring.management.commands.run_demo_simulator.push_batch_to_stream') as mock_push,
        patch('monitoring.management.commands.run_demo_simulator.record_heartbeats_batch') as mock_hb,
    ):
        call_command('run_demo_simulator', '--once', '--backfill-hours', '0')
    assert mock_push.called
    assert mock_hb.called
    batch = mock_push.call_args[0][0]
    assert len(batch) in (9, 10)
    assert all(entry['company_id'] == str(company.id) for entry in batch)


def test_demo_sample_diurnal_spike_and_flapping_behavior():
    spiky = next(s for s in DEMO_SERVER_SPECS if s['profile'] == 'spiky')
    rng = DemoNoise(7)
    ts = datetime(2026, 11, 28, 12, 0, tzinfo=dt_timezone.utc)
    burst = generate_demo_sample(spiky, ts, rng, spike_now=True)
    assert burst['cpu_usage'] >= 85.0
    assert len(burst['details']['docker_containers']) == 1

    online_ts = datetime(2026, 11, 28, 0, 0, 0, tzinfo=dt_timezone.utc)
    offline_ts = datetime(2026, 11, 28, 0, 4, 30, tzinfo=dt_timezone.utc)
    assert is_flapping_offline(online_ts) is False
    assert is_flapping_offline(offline_ts) is True
