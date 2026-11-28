import { expect, test } from '@playwright/test'

const API_BASE = process.env.E2E_API_URL || 'http://localhost:8000'
const METRICS_TOKEN = process.env.E2E_METRICS_TOKEN || ''

test.describe('SysRoar Phase 5 Production Readiness E2E', () => {
  test('healthz, readyz, OpenAPI schema, setup status, and Prometheus /metrics auth', async ({
    request,
  }) => {
    const healthResp = await request.get(`${API_BASE}/healthz`)
    expect(healthResp.status()).toBe(200)
    expect(await healthResp.json()).toEqual({ status: 'ok' })

    const readyResp = await request.get(`${API_BASE}/readyz`)
    expect(readyResp.status()).toBe(200)
    const readyBody = await readyResp.json()
    expect(readyBody.status).toBe('ready')
    expect(readyBody.checks.database).toBe(true)
    expect(readyBody.checks.redis).toBe(true)
    expect(readyBody.checks.ingest_lag).toBe(true)

    const schemaResp = await request.get(`${API_BASE}/api/schema/`)
    expect(schemaResp.status()).toBe(401)

    const setupResp = await request.get(`${API_BASE}/api/accounts/setup/`)
    expect(setupResp.status()).toBe(200)
    const setupBody = await setupResp.json()
    expect(typeof setupBody.needs_setup).toBe('boolean')

    const unauthMetrics = await request.get(`${API_BASE}/metrics`)
    if (METRICS_TOKEN) {
      expect(unauthMetrics.status()).toBe(401)

      const wrongMetrics = await request.get(`${API_BASE}/metrics`, {
        headers: { Authorization: 'Bearer wrong-metrics-token' },
      })
      expect(wrongMetrics.status()).toBe(401)

      const authMetrics = await request.get(`${API_BASE}/metrics`, {
        headers: { Authorization: `Bearer ${METRICS_TOKEN}` },
      })
      expect(authMetrics.status()).toBe(200)
      const metricsText = await authMetrics.text()
      expect(metricsText).toContain('sysroar_db_up 1.0')
      expect(metricsText).toContain('sysroar_redis_up 1.0')
      expect(metricsText).toContain('sysroar_active_servers_total')
      expect(metricsText).toContain('sysroar_open_incidents_total')
      expect(metricsText).toContain('sysroar_uptime_checks_down_total')
      expect(metricsText).toContain('sysroar_ws_active_connections')
    } else {
      expect(unauthMetrics.status()).toBe(403)
    }
  })
})
