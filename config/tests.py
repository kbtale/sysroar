import io
import json
import logging
import os
import subprocess
import sys
from unittest.mock import patch
from django.conf import settings
from django.test import SimpleTestCase, override_settings


class AsgiSmokeTests(SimpleTestCase):
    def test_asgi_application_imports_cleanly_from_fresh_process(self):
        env = os.environ.copy()
        env.pop('DJANGO_SETTINGS_MODULE', None)
        result = subprocess.run(
            [
                sys.executable,
                '-c',
                'import config.asgi as asgi; assert callable(asgi.application)',
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f'ASGI cold import failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}',
        )

    def test_asgi_application_routes_http_and_websocket(self):
        from channels.routing import ProtocolTypeRouter
        from channels.security.websocket import OriginValidator
        from config.asgi import application

        self.assertIsInstance(application, ProtocolTypeRouter)
        self.assertIn('http', application.application_mapping)
        self.assertIn('websocket', application.application_mapping)
        self.assertIsInstance(application.application_mapping['websocket'], OriginValidator)


class LoggingConfigurationTests(SimpleTestCase):
    def test_console_handler_uses_json_formatter_and_logstash_disabled_by_default(self):
        self.assertEqual(settings.LOG_BACKEND, 'none')
        self.assertEqual(settings.LOGGING['handlers']['console']['formatter'], 'json')
        self.assertNotIn('logstash', settings.LOGGING['root']['handlers'])
        self.assertNotIn('logstash', settings.LOGGING['handlers'])

    def test_elk_security_check_silent_when_log_backend_is_none(self):
        from config.checks import check_elasticsearch_security

        with override_settings(LOG_BACKEND='none'):
            self.assertEqual(check_elasticsearch_security(None), [])

    def test_elk_security_check_warns_only_when_elasticsearch_enabled_without_security(self):
        from config.checks import check_elasticsearch_security

        with override_settings(LOG_BACKEND='elasticsearch'):
            with patch.dict(os.environ, {'ELASTICSEARCH_SECURITY_ENABLED': 'false'}):
                warnings = check_elasticsearch_security(None)
                self.assertEqual(len(warnings), 1)
                self.assertEqual(warnings[0].id, 'sysroar.W001')

            with patch.dict(os.environ, {'ELASTICSEARCH_SECURITY_ENABLED': 'true'}):
                self.assertEqual(check_elasticsearch_security(None), [])

    def test_json_tcp_log_handler_serializes_json_not_pickle_and_elk_builder_uses_5044(self):
        from pythonjsonlogger.jsonlogger import JsonFormatter
        from config.logging_utils import CorrelationIdFilter, JsonTcpLogHandler, build_logging_config

        handler = JsonTcpLogHandler('logstash', 5044)
        handler.setFormatter(JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s %(correlation_id)s'))
        handler.addFilter(CorrelationIdFilter())

        record = logging.LogRecord(
            name='sysroar.test',
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='hello structured log',
            args=(),
            exc_info=None,
        )
        record.request = io.BytesIO(b'unpicklable')
        handler.filter(record)

        wire_bytes = handler.makePickle(record)
        self.assertTrue(wire_bytes.endswith(b'\n'))
        parsed = json.loads(wire_bytes.decode('utf-8'))
        self.assertEqual(parsed['message'], 'hello structured log')
        self.assertEqual(parsed['levelname'], 'INFO')
        self.assertIn('correlation_id', parsed)

        elk_logging = build_logging_config(log_backend='elasticsearch', logstash_host='logstash', logstash_port=5044)
        self.assertIn('logstash', elk_logging['root']['handlers'])
        self.assertEqual(elk_logging['handlers']['logstash']['port'], 5044)
        self.assertEqual(elk_logging['handlers']['logstash']['formatter'], 'json')
        self.assertEqual(elk_logging['handlers']['logstash']['class'], 'config.logging_utils.JsonTcpLogHandler')


class ComposeProfileTests(SimpleTestCase):
    def test_elk_services_live_behind_elk_profile_in_main_compose(self):
        compose_path = settings.BASE_DIR / 'docker-compose.yml'
        legacy_elk_path = settings.BASE_DIR / 'docker-compose.elk.yml'
        self.assertFalse(legacy_elk_path.exists())

        content = compose_path.read_text(encoding='utf-8')
        for service in ('elasticsearch:', 'logstash:', 'kibana:'):
            self.assertIn(service, content)
        self.assertGreaterEqual(content.count('- elk'), 3)
        self.assertIn('LOGSTASH_PORT=5044', content)

    def test_logstash_pipeline_separates_syslog_5000_and_json_lines_5044(self):
        pipeline_path = settings.BASE_DIR / 'logstash' / 'pipeline' / 'syslog.conf'
        content = pipeline_path.read_text(encoding='utf-8')
        self.assertIn('port => 5000', content)
        self.assertIn('port => 5044', content)
        self.assertIn('codec => json_lines', content)
