---
layout: home

hero:
  name: SysRoar
  text: Self-Hosted Server Monitoring
  tagline: One-line Rust agent, TimescaleDB rollups, real-time WebSocket fleet view, smart alerts, uptime checks, public status pages, and optional multi-tenant logs.
  actions:
    - theme: brand
      text: Quick Start & Demo
      link: /install
    - theme: alt
      text: Install the Rust Agent
      link: /agent

features:
  - title: Lightweight Rust Agent v2
    details: Single static binary with local SQLite disk buffering, gzip batching, Docker container stats, systemd units, mount inodes, temperatures, optional log shipping, and Ed25519 signed auto-updates.
  - title: Multi-Tenant by Design
    details: Strict server-side company scoping across REST APIs, WebSockets, TimescaleDB hypertables, and Loki X-Scope-OrgID log queries with RBAC roles and audit logs.
  - title: Alerting That Does Not Spam
    details: Hysteresis, pending duration timers, escalating cooldowns, 10 native SSRF-guarded notification channels, silences, recurring maintenance windows, alert grouping, daily digests, and z-score anomaly hints.
  - title: Uptime, Status Pages & Open Ingestion
    details: Built-in HTTP/TCP/SSL/DNS/Ping uptime monitors, unauthenticated public status pages with zero data leakage, plus OTLP/HTTP and Prometheus remote-write ingestion endpoints.
---
