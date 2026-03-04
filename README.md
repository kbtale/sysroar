# SysRoar

SysRoar is a high-performance infrastructure monitoring and telemetry ingestion platform designed for massive horizontal scalability and robust alert management.

## System Architecture

The platform utilizes a modern, asynchronous architecture to handle high-throughput metric streams from distributed agents.

### Core Backend
- **Asynchronous Ingestion**: A Django/DRF API that immediately returns `202 Accepted` after queueing payloads to Redis, decoupling the client from database latency.
- **Write-Behind Processing**: Celery workers consume telemetry batches from Redis using **atomic Lua scripts**, ensuring safe horizontal scaling across multiple worker instances.
- **Persistence Layer**: PostgreSQL handles structured storage with optimized `bulk_create` operations.
- **Alert Evaluation Engine**: A dedicated engine that evaluates incoming metrics against `AlertRule` thresholds in real-time.
- **Alert State Machine**: A sophisticated cooldown manager that prevents alert fatigue using tiered intervals (3m, 5m, 10m, 30m, 60m) and row-level database locking for concurrency safety.

### Remote Telemetry Agent
- **Lightweight Implementation**: A standalone Python agent utilizing `psutil` for minimal resource overhead.
- **Metrics Collection**: High-precision gathering of CPU usage, RAM utilization, and Disk I/O throughput.
- **Configurable Cadence**: Default 30-second telemetry push interval.
- **Resilient Delivery**: Automatic UTC timestamping and extensible error handling.

## Project Structure

```text
sysroar/
├── accounts/          # Tenant and User management
├── monitoring/        # Alert rules, state machine, and evaluation logic
├── telemetry/         # High-speed ingestion API and batch workers
├── config/            # Project settings, middleware, and logging utils
└── agent/             # Standalone remote telemetry client
```

## Getting Started

### Backend Setup (Docker)

1. **Environment Configuration**:
   Create a `.env` file in the root directory and configure mandatory variables:
   ```env
   SECRET_KEY=your_secret_key
   DB_NAME=sysroar
   DB_USER=postgres
   DB_PASSWORD=postgres
   REDIS_URL=redis://redis:6379/0
   ```

2. **Launch Services**:
   ```bash
   docker compose up -d
   ```

3. **Run Migrations**:
   ```bash
   docker compose exec web python manage.py migrate
   ```

### Remote Agent Setup

1. **Install Dependencies**:
   ```bash
   pip install -r agent/requirements.txt
   ```

2. **Configure Environment**:
   ```env
   SYSROAR_API_URL=http://your-app-url/api/telemetry/ingest/
   SYSROAR_API_TOKEN=your_auth_token
   SYSROAR_SERVER_ID=uuid-of-server
   SYSROAR_COMPANY_ID=uuid-of-company
   ```

3. **Launch Agent**:
   ```bash
   python agent/client.py
   ```

## Technical Stack
- **Framework**: Django 5.x, Django REST Framework
- **Task Queue**: Celery & Redis
- **Database**: PostgreSQL
- **Monitoring**: psutil
- **Observability**: Custom Correlation ID Middleware, JSON Logging
