import os
import subprocess
import sys
from django.test import SimpleTestCase


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
