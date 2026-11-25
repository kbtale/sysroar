import logging
import logging.handlers
import os
import threading
import time
from datetime import datetime, timezone
import psutil
import requests
from dotenv import load_dotenv

load_dotenv()

MIN_TELEMETRY_CADENCE = 5
MAX_TELEMETRY_CADENCE = 3600
DEFAULT_TELEMETRY_CADENCE = 30
VALID_LOG_LEVELS = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}

API_URL = os.getenv('SYSROAR_API_URL', 'http://localhost:8000/api/telemetry/ingest/')
CONFIG_URL = os.getenv('SYSROAR_CONFIG_URL', 'http://localhost:8000/api/telemetry/config/')
API_TOKEN = os.getenv('SYSROAR_API_TOKEN')
SERVER_ID = os.getenv('SYSROAR_SERVER_ID')

LOGSTASH_HOST = os.getenv('SYSROAR_LOGSTASH_HOST', 'localhost')
LOGSTASH_PORT = int(os.getenv('SYSROAR_LOGSTASH_PORT', 5000))


def _validate_cadence(value, fallback=DEFAULT_TELEMETRY_CADENCE):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    if parsed < MIN_TELEMETRY_CADENCE:
        return MIN_TELEMETRY_CADENCE
    if parsed > MAX_TELEMETRY_CADENCE:
        return MAX_TELEMETRY_CADENCE
    return parsed


def _apply_log_level(level_name):
    if not isinstance(level_name, str):
        return False
    normalized = level_name.upper()
    if normalized not in VALID_LOG_LEVELS:
        return False
    logger.setLevel(getattr(logging, normalized))
    return True


settings = {
    'telemetry_cadence': _validate_cadence(os.getenv('SYSROAR_TELEMETRY_CADENCE', DEFAULT_TELEMETRY_CADENCE)),
    'log_level': 'INFO',
}

logger = logging.getLogger('sysroar-agent')
logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(console_handler)


def configure_syslog_handler(host, port, server_id):
    try:
        handler = logging.handlers.SysLogHandler(address=(host, port))
        handler.setFormatter(
            logging.Formatter(f'sysroar-agent[{server_id}]: %(levelname)s %(message)s')
        )
        logger.addHandler(handler)
        return handler
    except Exception as e:
        logger.warning(f'Syslog handler could not connect: {e}. Logs will only go to stdout.')
        return None


configure_syslog_handler(LOGSTASH_HOST, LOGSTASH_PORT, SERVER_ID)


class TelemetryCollector:
    def __init__(self):
        psutil.cpu_percent(interval=None)
        self.last_disk_io = psutil.disk_io_counters()

    def collect(self):
        cpu_usage = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        ram_usage = memory.percent

        current_disk_io = psutil.disk_io_counters()
        if current_disk_io is not None and self.last_disk_io is not None:
            read_bytes = max(0, current_disk_io.read_bytes - self.last_disk_io.read_bytes)
            write_bytes = max(0, current_disk_io.write_bytes - self.last_disk_io.write_bytes)
            disk_throughput_mb = (read_bytes + write_bytes) / (1024 * 1024)
        else:
            disk_throughput_mb = 0.0
        self.last_disk_io = current_disk_io

        return {
            'server': SERVER_ID,
            'cpu_usage': float(cpu_usage),
            'ram_usage': float(ram_usage),
            'disk_io': float(disk_throughput_mb),
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }


def push_telemetry(payload):
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Token {API_TOKEN}',
    }

    try:
        response = requests.post(API_URL, json=payload, headers=headers, timeout=10)
        if response.status_code == 202:
            logger.info('Telemetry successfully pushed (202 Accepted).')
        else:
            logger.warning(f'Unexpected response from server: {response.status_code} - {response.text}')
    except Exception as e:
        logger.error(f'Failed to connect to backend: {e}')


def fetch_configuration():
    headers = {
        'Authorization': f'Token {API_TOKEN}',
        'X-Server-ID': SERVER_ID,
    }
    try:
        response = requests.get(CONFIG_URL, headers=headers, timeout=10)
        if response.status_code == 200:
            new_config = response.json()
            if 'telemetry_cadence' in new_config:
                settings['telemetry_cadence'] = _validate_cadence(
                    new_config['telemetry_cadence'],
                    fallback=settings['telemetry_cadence'],
                )
            if 'log_level' in new_config and _apply_log_level(new_config['log_level']):
                settings['log_level'] = new_config['log_level'].upper()
            logger.info(f'Configuration synchronized: {settings}')
        else:
            logger.warning(f'Failed to fetch config: {response.status_code}')
    except Exception as e:
        logger.error(f'Error fetching configuration: {e}')


def config_polling_loop():
    while True:
        fetch_configuration()
        time.sleep(3600)


def run_agent():
    if not all([API_TOKEN, SERVER_ID]):
        logger.error('Missing mandatory environment variables.')
        return

    config_thread = threading.Thread(target=config_polling_loop, daemon=True)
    config_thread.start()

    logger.info('Starting SysRoar Remote Agent.')
    collector = TelemetryCollector()

    while True:
        try:
            payload = collector.collect()
            push_telemetry(payload)
        except Exception as e:
            logger.error(f'Error in telemetry loop: {e}')

        time.sleep(settings['telemetry_cadence'])


if __name__ == '__main__':
    run_agent()
