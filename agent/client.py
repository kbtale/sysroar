import os
import time
import json
import logging
import psutil
import requests
from dotenv import load_dotenv
from datetime import datetime

# Load configuration from .env file if it exists
load_dotenv()

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Backend Configuration
# Use environment variables for sensitive or variable configuration
API_URL = os.getenv("SYSROAR_API_URL", "http://localhost:8000/api/telemetry/ingest/")
API_TOKEN = os.getenv("SYSROAR_API_TOKEN")
SERVER_ID = os.getenv("SYSROAR_SERVER_ID")
COMPANY_ID = os.getenv("SYSROAR_COMPANY_ID")
TELEMETRY_CADENCE = int(os.getenv("SYSROAR_TELEMETRY_CADENCE", 30))

class TelemetryCollector:
    def __init__(self):
        # Initial call to cpu_percent to establish a baseline
        psutil.cpu_percent(interval=None)
        self.last_disk_io = psutil.disk_io_counters()

    def collect(self):
        """
        Gathers system-level telemetry using psutil.
        """
        # CPU
        cpu_usage = psutil.cpu_percent(interval=None)
        
        # RAM
        memory = psutil.virtual_memory()
        ram_usage = memory.percent
        
        # Disk I/O (Calculate delta since last collection)
        current_disk_io = psutil.disk_io_counters()
        read_bytes = current_disk_io.read_bytes - self.last_disk_io.read_bytes
        write_bytes = current_disk_io.write_bytes - self.last_disk_io.write_bytes
        self.last_disk_io = current_disk_io
        
        # Aggregate bytes for simple "disk usage" metric or store as throughput
        disk_throughput_mb = (read_bytes + write_bytes) / (1024 * 1024)

        return {
            "server": SERVER_ID,
            "company": COMPANY_ID,
            "cpu_usage": float(cpu_usage),
            "ram_usage": float(ram_usage),
            "disk_io": float(disk_throughput_mb),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

def push_telemetry(payload):
    """
    Sends the collected telemetry to the SysRoar backend.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_TOKEN}"
    }
    
    try:
        response = requests.post(API_URL, json=payload, headers=headers, timeout=10)
        if response.status_code == 202:
            logger.info("Telemetry successfully pushed (202 Accepted).")
        else:
            logger.warning(f"Unexpected response from server: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Failed to connect to backend: {e}")

def run_agent():
    """
    Main loop for the telemetry agent.
    """
    if not all([API_TOKEN, SERVER_ID, COMPANY_ID]):
        logger.error("Missing mandatory environment variables (TOKEN, SERVER_ID, or COMPANY_ID).")
        return

    logger.info(f"Starting SysRoar Remote Agent. Cadence: {TELEMETRY_CADENCE}s")
    collector = TelemetryCollector()

    while True:
        try:
            payload = collector.collect()
            logger.debug(f"Collected payload: {json.dumps(payload)}")
            push_telemetry(payload)
        except Exception as e:
            logger.error(f"Error in telemetry loop: {e}")
        
        time.sleep(TELEMETRY_CADENCE)

if __name__ == "__main__":
    run_agent()
