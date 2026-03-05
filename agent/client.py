import os
import time
import json
import logging
import logging.handlers
import threading
import psutil
import requests
from dotenv import load_dotenv
from datetime import datetime, timezone

# Load configuration from .env file if it exists
load_dotenv()


# Backend Configuration
API_URL = os.getenv("SYSROAR_API_URL", "http://localhost:8000/api/telemetry/ingest/")
CONFIG_URL = os.getenv("SYSROAR_CONFIG_URL", "http://localhost:8000/api/telemetry/config/")
API_TOKEN = os.getenv("SYSROAR_API_TOKEN")
SERVER_ID = os.getenv("SYSROAR_SERVER_ID")
COMPANY_ID = os.getenv("SYSROAR_COMPANY_ID")

# Logstash Configuration
LOGSTASH_HOST = os.getenv("SYSROAR_LOGSTASH_HOST", "localhost")
LOGSTASH_PORT = int(os.getenv("SYSROAR_LOGSTASH_PORT", 5000))

# Global settings that can be updated dynamically
settings = {
    "telemetry_cadence": int(os.getenv("SYSROAR_TELEMETRY_CADENCE", 30)),
    "log_level": "INFO"
}

# Logger setup
logger = logging.getLogger("sysroar-agent")
logger.setLevel(logging.INFO)

# Console handler (always active)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(console_handler)

def configure_syslog_handler(host, port, server_id):
    """
    Attaches a SysLogHandler to the agent logger.
    Returns the handler on success, or None if the connection fails.
    """
    try:
        handler = logging.handlers.SysLogHandler(address=(host, port))
        handler.setFormatter(
            logging.Formatter(f'sysroar-agent[{server_id}]: %(levelname)s %(message)s')
        )
        logger.addHandler(handler)
        return handler
    except Exception as e:
        logger.warning(f"Syslog handler could not connect: {e}. Logs will only go to stdout.")
        return None

# Initialize syslog handler at startup
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
        read_bytes = current_disk_io.read_bytes - self.last_disk_io.read_bytes
        write_bytes = current_disk_io.write_bytes - self.last_disk_io.write_bytes
        self.last_disk_io = current_disk_io
        
        disk_throughput_mb = (read_bytes + write_bytes) / (1024 * 1024)

        return {
            "server": SERVER_ID,
            "company": COMPANY_ID,
            "cpu_usage": float(cpu_usage),
            "ram_usage": float(ram_usage),
            "disk_io": float(disk_throughput_mb),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

def push_telemetry(payload):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {API_TOKEN}"
    }
    
    try:
        response = requests.post(API_URL, json=payload, headers=headers, timeout=10)
        if response.status_code == 202:
            logger.info("Telemetry successfully pushed (202 Accepted).")
        else:
            logger.warning(f"Unexpected response from server: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Failed to connect to backend: {e}")

def fetch_configuration():
    """
    Fetches the latest server-side configuration.
    """
    headers = {
        "Authorization": f"Token {API_TOKEN}",
        "X-Server-ID": SERVER_ID
    }
    try:
        response = requests.get(CONFIG_URL, headers=headers, timeout=10)
        if response.status_code == 200:
            new_config = response.json()
            settings.update(new_config)
            logger.info(f"Configuration synchronized: {settings}")
            
            # Apply log level if it changed
            if "log_level" in new_config:
                logging.getLogger().setLevel(new_config["log_level"])
        else:
            logger.warning(f"Failed to fetch config: {response.status_code}")
    except Exception as e:
        logger.error(f"Error fetching configuration: {e}")

def config_polling_loop():
    """
    Background loop that polls for configuration every hour.
    """
    while True:
        fetch_configuration()
        time.sleep(3600) # Poll every 1 hour

def run_agent():
    if not all([API_TOKEN, SERVER_ID, COMPANY_ID]):
        logger.error("Missing mandatory environment variables.")
        return

    # Start configuration polling in a background thread
    config_thread = threading.Thread(target=config_polling_loop, daemon=True)
    config_thread.start()

    logger.info(f"Starting SysRoar Remote Agent.")
    collector = TelemetryCollector()

    while True:
        try:
            payload = collector.collect()
            push_telemetry(payload)
        except Exception as e:
            logger.error(f"Error in telemetry loop: {e}")
        
        time.sleep(settings["telemetry_cadence"])

if __name__ == "__main__":
    run_agent()
