import { expect, test } from '@playwright/test'

const API_BASE = process.env.E2E_API_URL || 'http://localhost:8000'

test.describe('SysRoar Phase 4 Competitive Features E2E Acceptance', () => {
  test('uptime checks, maintenance windows, public status page, OTLP ingestion, and logs-off UX', async ({
    page,
    browser,
    request,
  }) => {
    const consoleErrors: string[] = []
    const pageErrors: string[] = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text())
      }
    })
    page.on('pageerror', (err) => {
      pageErrors.push(String(err))
    })

    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/')

    if (page.url().includes('/setup')) {
      await page.getByLabel('Company Name').fill('SysRoar Phase 4 Ops')
      await page.getByLabel('Admin Username').fill('e2eowner')
      await page.getByLabel('Admin Email').fill('owner@e2e.test')
      await page.getByLabel('Password', { exact: true }).fill('Str0ng!Pass2026')
      await page.getByRole('button', { name: /Create Workspace/i }).click()
    } else if (page.url().includes('/login')) {
      await page.getByLabel('Username').fill('e2eowner')
      await page.getByLabel('Password', { exact: true }).fill('Str0ng!Pass2026')
      await page.getByRole('button', { name: 'Sign In' }).click()
    }

    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByRole('heading', { name: 'Fleet Overview' })).toBeVisible()

    await expect(page.getByRole('link', { name: 'Logs', exact: true })).toHaveCount(0)

    await page.goto('/logs')
    await expect(page.getByText(/Log storage is turned off/i)).toBeVisible()

    await page.getByRole('link', { name: 'Uptime' }).click()
    await expect(page).toHaveURL(/\/uptime/)
    await expect(page.getByRole('heading', { name: /Uptime Checks/i })).toBeVisible()

    await page.getByRole('button', { name: 'Add Check' }).click()
    await expect(page.getByRole('heading', { name: 'New Uptime Check' })).toBeVisible()
    await page.getByLabel('Check Name').fill('Local Healthz Probe')
    await page.getByLabel('Endpoint URL').fill(`${API_BASE}/healthz`)
    await page.locator('.switch-row [role="switch"]').click()
    await page.getByRole('button', { name: 'Create Check' }).click()
    await expect(page.getByRole('heading', { name: 'New Uptime Check' })).toBeHidden()
    await expect(page.getByText('Local Healthz Probe')).toBeVisible()

    await page.getByRole('button', { name: /Run Now/i }).first().click()
    await expect(page.getByText('up', { exact: true }).first()).toBeVisible({ timeout: 15000 })

    await page.getByRole('link', { name: 'Alerts' }).click()
    await expect(page).toHaveURL(/\/alerts/)
    await page.getByRole('tab', { name: /Maintenance/i }).click()
    await page.getByRole('button', { name: 'Schedule Window' }).click()
    await expect(page.getByRole('heading', { name: 'Schedule Maintenance Window' })).toBeVisible()
    await page.getByLabel('Window Name').fill('E2E Patching Window')
    await page.getByLabel('Reason (optional)').fill('Automated kernel rollout')
    await page.getByRole('button', { name: 'Schedule Window' }).last().click()
    await expect(page.getByRole('heading', { name: 'Schedule Maintenance Window' })).toBeHidden()
    await expect(page.getByText('E2E Patching Window')).toBeVisible()
    await expect(page.getByText('active now')).toBeVisible()

    await page.getByRole('link', { name: 'Settings' }).click()
    await expect(page).toHaveURL(/\/settings/)
    await page.getByRole('tab', { name: /Status Pages/i }).click()
    await page.getByRole('button', { name: 'New Status Page' }).click()
    await expect(page.getByRole('heading', { name: 'Create Public Status Page' })).toBeVisible()
    await page.getByLabel('Page Title').fill('SysRoar E2E Status')
    await page.getByLabel('URL Slug').fill('e2e-public-status')
    await page.getByLabel('Description (optional)').fill('Real-time service status.')
    await page.getByLabel('Local Healthz Probe').check()
    await page.getByRole('button', { name: 'Create Status Page' }).click()
    await expect(page.getByRole('heading', { name: 'Create Public Status Page' })).toBeHidden()
    await expect(page.getByText('/status/e2e-public-status')).toBeVisible()

    const anonContext = await browser.newContext()
    const anonPage = await anonContext.newPage()
    await anonPage.goto('/status/e2e-public-status')
    await expect(anonPage.getByRole('heading', { name: 'SysRoar E2E Status' })).toBeVisible()
    await expect(anonPage.getByText('All Systems Operational')).toBeVisible()
    await expect(anonPage.getByText('Local Healthz Probe')).toBeVisible()
    const publicBody = await anonPage.locator('body').innerText()
    expect(publicBody).not.toContain('owner@e2e.test')
    expect(publicBody).not.toContain('127.0.0.1')

    await anonPage.setViewportSize({ width: 390, height: 844 })
    const statusOverflow = await anonPage.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    )
    expect(statusOverflow).toBe(false)
    await anonContext.close()

    await page.getByRole('link', { name: 'Fleet' }).click()
    await page.getByRole('button', { name: /Add Server/i }).first().click()
    await page.getByRole('button', { name: /Generate Enrollment Command/i }).click()
    const enrollToken = (await page.locator('.token-value').innerText()).trim()
    await page.getByRole('tab', { name: /OTLP \/ Prom/i }).click()
    await expect(page.getByText(/\/api\/telemetry\/otlp\/v1\/metrics/)).toBeVisible()

    const enrollResp = await request.post(`${API_BASE}/api/telemetry/enroll/`, {
      data: {
        enrollment_token: enrollToken,
        name: 'otlp-e2e-host',
        hostname: 'otlp-e2e-host.local',
        agent_version: '0.2.0',
      },
    })
    expect(enrollResp.status()).toBe(201)
    const enrolled = await enrollResp.json()

    const otlpResp = await request.post(`${API_BASE}/api/telemetry/otlp/v1/metrics`, {
      headers: {
        Authorization: `AgentKey ${enrolled.agent_key}`,
      },
      data: {
        resourceMetrics: [
          {
            resource: { attributes: [{ key: 'host.name', value: { stringValue: 'otlp-e2e-host.local' } }] },
            scopeMetrics: [
              {
                metrics: [
                  {
                    name: 'system.cpu.utilization',
                    gauge: { dataPoints: [{ asDouble: 0.42 }] },
                  },
                  {
                    name: 'system.memory.utilization',
                    gauge: { dataPoints: [{ asDouble: 0.55 }] },
                  },
                ],
              },
            ],
          },
        ],
      },
    })
    expect(otlpResp.status()).toBe(200)
    const otlpJson = await otlpResp.json()
    expect(otlpJson.accepted).toBe(1)

    await expect(page.getByRole('heading', { name: 'Host Connected' })).toBeVisible({ timeout: 15000 })
    await page.getByRole('link', { name: /Inspect Server/i }).click()
    await expect(page).toHaveURL(new RegExp(`/servers/${enrolled.server_id}`))
    await expect(page.getByRole('heading', { name: 'otlp-e2e-host' })).toBeVisible()

    expect(pageErrors).toEqual([])
    expect(consoleErrors.filter((e) => !e.includes('WebSocket'))).toEqual([])
  })
})
