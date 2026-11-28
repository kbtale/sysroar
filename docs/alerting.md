# Alerting, Maintenance & Anomaly Hints

## Alert State Machine

Every `AlertRule` is evaluated on a 30-second schedule against windowed metrics in TimescaleDB (or log match counts when `metric_type=log_count`) using a durable state machine:

1. **OK -> PENDING:** When the metric breaches the configured threshold (`>`, `>=`, `<`, `<=`), the rule enters `PENDING` until it stays breached for `duration_minutes`.
2. **PENDING -> FIRING:** Once the pending duration elapses, SysRoar opens an `Incident` and enqueues a transactional `NotificationOutbox` delivery.
3. **Escalating Cooldown:** Repeated reminders back off cleanly (3m, 5m, 10m, 30m, 60m) to prevent alert fatigue.
4. **Hysteresis & Auto-Resolution:** The metric must recover past `threshold +/- hysteresis_margin` to resolve the incident and dispatch a recovery notice.

## Notification Channels (10 Native Providers)

All webhook-based channels run through SysRoar's SSRF guard (`send_safe_webhook_post`), blocking loopback, RFC1918, and cloud metadata IPs:

- Email (SMTP)
- Signed Generic Webhook (HMAC-SHA256 `X-SysRoar-Signature`)
- Slack
- Discord
- Microsoft Teams
- Telegram
- PagerDuty (Events API v2 with dedup keys & resolve events)
- Opsgenie
- ntfy
- Gotify

## Noise Reduction

- **Alert Silences:** Quick ad-hoc suppression per server, rule, or entire tenant.
- **Maintenance Windows:** One-time, daily, or weekly recurring windows scoped to all resources, a single server, or a tag filter. Suppresses both metric alert rules and uptime incident creation.
- **Alert Grouping:** Simultaneous alerts firing in the same cycle for the same company and notification channel are consolidated into a single grouped notification.
- **Daily Digest Emails:** Optional daily fleet, incident, and 24-hour uptime summary configured per workspace in **Settings -> Company**.
- **Anomaly Hints:** Rolling 24-hour vs 15-minute z-score baselines flag sudden CPU, RAM, disk, or load deviations (`z >= 2.5`) with subtle **Unusual for this server** badges.
