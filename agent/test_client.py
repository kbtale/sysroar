import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from agent import client as agent_client


def test_collector_handles_none_disk_io_counters():
    with (
        patch('agent.client.psutil.cpu_percent', return_value=12.5),
        patch('agent.client.psutil.virtual_memory', return_value=SimpleNamespace(percent=44.0)),
        patch('agent.client.psutil.disk_io_counters', return_value=None),
    ):
        collector = agent_client.TelemetryCollector()
        payload = collector.collect()

    assert payload['cpu_usage'] == 12.5
    assert payload['ram_usage'] == 44.0
    assert payload['disk_io'] == 0.0
    assert 'company' not in payload


def test_fetch_configuration_applies_log_level_to_agent_logger():
    prev_level = agent_client.logger.level
    prev_cadence = agent_client.settings['telemetry_cadence']
    response = MagicMock(status_code=200)
    response.json.return_value = {'telemetry_cadence': 15, 'log_level': 'DEBUG'}

    try:
        with patch('agent.client.requests.get', return_value=response):
            agent_client.fetch_configuration()

        assert agent_client.logger.level == logging.DEBUG
        assert agent_client.settings['telemetry_cadence'] == 15
    finally:
        agent_client.logger.setLevel(prev_level)
        agent_client.settings['telemetry_cadence'] = prev_cadence


def test_fetch_configuration_rejects_zero_negative_and_non_numeric_cadence():
    prev_level = agent_client.logger.level
    prev_cadence = agent_client.settings['telemetry_cadence']
    agent_client.settings['telemetry_cadence'] = 30
    agent_client.logger.setLevel(logging.INFO)

    try:
        for bad_cadence in (0, -5, 'not-a-number', None):
            response = MagicMock(status_code=200)
            response.json.return_value = {'telemetry_cadence': bad_cadence, 'log_level': 'INVALID_LEVEL'}
            with patch('agent.client.requests.get', return_value=response):
                agent_client.fetch_configuration()
            assert agent_client.settings['telemetry_cadence'] >= agent_client.MIN_TELEMETRY_CADENCE
            assert agent_client.logger.level == logging.INFO
    finally:
        agent_client.logger.setLevel(prev_level)
        agent_client.settings['telemetry_cadence'] = prev_cadence
