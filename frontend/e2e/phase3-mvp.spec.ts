import { expect, test } from '@playwright/test'

const API_BASE = process.env.E2E_API_URL || 'http://localhost:8000'

test.describe('SysRoar Phase 3 MVP End-to-End Acceptance', () => {
  test('full journey: setup wizard, agent onboarding, charts, alerts, invite RBAC, and responsive audit', async ({
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
    await expect(page).toHaveURL(/\/setup/)
    await expect(page.getByRole('heading', { name: /Initial Instance Setup/i })).toBeVisible()

    await page.getByLabel('Company Name').fill('SysRoar E2E Ops')
    await page.getByLabel('Admin Username').fill('e2eowner')
    await page.getByLabel('Admin Email').fill('owner@e2e.test')
    await page.getByLabel('Password', { exact: true }).fill('Str0ng!Pass2026')
    await page.getByRole('button', { name: /Create Workspace/i }).click()

    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByRole('heading', { name: 'Fleet Overview' })).toBeVisible()
    await expect(page.getByText('No servers monitored yet')).toBeVisible()

    await page.getByRole('button', { name: /Add Server/i }).first().click()
    await expect(page.getByRole('heading', { name: 'Add Server' })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('heading', { name: 'Add Server' })).toBeHidden()

    await page.getByRole('button', { name: /Add Server/i }).first().click()
    await page.getByRole('button', { name: /Generate Enrollment Command/i }).click()
    await expect(page.getByText(/Waiting for first heartbeat/i)).toBeVisible()

    const tokenText = (await page.locator('.token-value').innerText()).trim()
    expect(tokenText).toContain('.')

    const enrollResp = await request.post(`${API_BASE}/api/telemetry/enroll/`, {
      data: {
        enrollment_token: tokenText,
        name: 'e2e-edge-01',
        hostname: 'e2e-edge-01.internal',
        os_info: 'Ubuntu 24.04 LTS',
        kernel: '6.8.0-generic',
        cpu_model: 'AMD EPYC 9654',
        cpu_cores: 8,
        total_ram_bytes: 17179869184,
        agent_version: '0.1.0',
      },
    })
    expect(enrollResp.status()).toBe(201)
    const enrolled = await enrollResp.json()

    const nowIso = new Date().toISOString()
    const ingestResp = await request.post(`${API_BASE}/api/telemetry/ingest/batch/`, {
      headers: {
        Authorization: `AgentKey ${enrolled.agent_key}`,
      },
      data: {
        samples: [
          {
            server: enrolled.server_id,
            timestamp: nowIso,
            cpu_usage: 74.5,
            ram_usage: 58.2,
            disk_usage: 41.0,
            swap_usage: 3.5,
            disk_read_bps: 204800,
            disk_write_bps: 102400,
            net_rx_bps: 512000,
            net_tx_bps: 256000,
            load_1m: 1.25,
            uptime_seconds: 93600,
          },
        ],
      },
    })
    expect(ingestResp.status()).toBe(202)

    await expect(page.getByRole('heading', { name: 'Host Connected' })).toBeVisible({ timeout: 15000 })
    await page.getByRole('link', { name: /Inspect Server/i }).click()

    await expect(page).toHaveURL(new RegExp(`/servers/${enrolled.server_id}`))
    await expect(page.getByRole('heading', { name: 'e2e-edge-01' })).toBeVisible()
    await expect(page.getByText('Ubuntu 24.04 LTS')).toBeVisible()
    await expect(page.getByText('16.0 GiB', { exact: true })).toBeVisible()

    await page.getByRole('radio', { name: '24h' }).click()
    await expect(page).toHaveURL(/range=24h/)

    await page.getByRole('button', { name: 'Edit' }).click()
    await expect(page.getByRole('heading', { name: 'Edit Server' })).toBeVisible()
    await page.getByLabel('Tags (comma-separated)').fill('prod, edge')
    await page.getByRole('button', { name: 'Save Changes' }).click()
    await expect(page.getByRole('heading', { name: 'Edit Server' })).toBeHidden()
    await expect(page.getByText('#prod')).toBeVisible()

    await page.getByRole('link', { name: 'Alerts' }).click()
    await expect(page).toHaveURL(/\/alerts/)
    await expect(page.getByRole('heading', { name: /Alerts & Incidents/i })).toBeVisible()

    await page.getByRole('button', { name: 'New Rule' }).click()
    await expect(page.getByRole('heading', { name: 'New Alert Rule' })).toBeVisible()
    await page.getByLabel('Threshold').fill('80')
    await page.getByLabel('Duration (min)').fill('2')
    await page.getByLabel('Email Address').fill('ops@e2e.test')
    await page.getByRole('button', { name: 'Create Rule' }).click()
    await expect(page.getByRole('heading', { name: 'New Alert Rule' })).toBeHidden()

    await page.getByRole('tab', { name: /Rules/i }).click()
    await expect(page.getByText('e2e-edge-01').first()).toBeVisible()

    await page.getByRole('tab', { name: /Channels/i }).click()
    await page.getByRole('button', { name: 'Add Channel' }).click()
    await expect(page.getByRole('heading', { name: 'Add Notification Channel' })).toBeVisible()
    await page.getByLabel('Channel Name').fill('Primary Ops Email')
    await page.getByLabel('Channel Type').click()
    await page.getByRole('option', { name: 'Email' }).click()
    await page.getByLabel('Email Address').fill('alerts@e2e.test')
    await page.getByRole('button', { name: 'Create Channel' }).click()
    await expect(page.getByRole('heading', { name: 'Add Notification Channel' })).toBeHidden()
    await expect(page.getByText('Primary Ops Email').first()).toBeVisible()

    await page.getByRole('tab', { name: /Silences/i }).click()
    await page.getByRole('button', { name: 'Create Silence' }).click()
    await expect(page.getByRole('heading', { name: 'Create Alert Silence' })).toBeVisible()
    await page.getByLabel('Reason').fill('Deploy window')
    await page.getByRole('button', { name: 'Create Silence' }).last().click()
    await expect(page.getByRole('heading', { name: 'Create Alert Silence' })).toBeHidden()
    await expect(page.getByText('Deploy window').first()).toBeVisible()

    await page.getByRole('link', { name: 'Settings' }).click()
    await expect(page).toHaveURL(/\/settings/)
    await page.getByLabel('Metric Retention (days)').fill('30')
    await page.getByRole('button', { name: 'Save Workspace' }).click()

    await page.getByRole('tab', { name: /Members & Invites/i }).click()
    await page.getByRole('button', { name: 'Invite Member' }).click()
    await expect(page.getByRole('heading', { name: 'Invite Team Member' })).toBeVisible()
    await page.getByLabel('Email Address').fill('viewer@e2e.test')
    await page.getByRole('combobox', { name: 'Role', exact: true }).click()
    await page.getByRole('option', { name: /Viewer/i }).click()
    await page.getByRole('button', { name: 'Create Invitation' }).click()

    const inviteUrl = (await page.locator('.copy-code').innerText()).trim()
    expect(inviteUrl).toContain('/accept-invite?token=')
    await page.getByRole('button', { name: 'Done' }).click()
    await expect(page.getByRole('heading', { name: 'Invite Team Member' })).toBeHidden()

    const viewerContext = await browser.newContext()
    const viewerPage = await viewerContext.newPage()
    const invitePath = new URL(inviteUrl).pathname + new URL(inviteUrl).search
    await viewerPage.goto(invitePath)
    await expect(viewerPage.getByRole('heading', { name: /Accept Team Invite/i })).toBeVisible()
    await viewerPage.getByLabel('Username').fill('e2eviewer')
    await viewerPage.getByLabel('Password', { exact: true }).fill('View3r!Pass2026')
    await viewerPage.getByRole('button', { name: /Join Workspace/i }).click()

    await expect(viewerPage).toHaveURL(/\/$/)
    await expect(viewerPage.getByText('e2e-edge-01')).toBeVisible()
    await expect(viewerPage.getByRole('button', { name: /Add Server/i })).toHaveCount(0)

    await viewerPage.getByRole('link', { name: 'Alerts' }).click()
    await expect(viewerPage.getByRole('button', { name: 'New Rule' })).toHaveCount(0)

    await viewerPage.getByRole('link', { name: 'Settings' }).click()
    await expect(viewerPage.getByRole('tab', { name: /Members & Invites/i })).toHaveCount(0)
    await expect(viewerPage.getByRole('tab', { name: /Keys & Tokens/i })).toHaveCount(0)
    await expect(viewerPage.getByRole('tab', { name: /Audit Log/i })).toHaveCount(0)
    await viewerContext.close()

    await page.getByRole('link', { name: 'Fleet' }).click()
    await expect(page.getByText('e2e-edge-01')).toBeVisible()

    const themeSwitch = page.locator('.desktop-sidebar [role="switch"]')
    const initialTheme = await page.locator('html').getAttribute('data-theme')
    const nextTheme = initialTheme === 'dark' ? 'light' : 'dark'
    await themeSwitch.click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', nextTheme)
    await themeSwitch.click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', initialTheme || 'dark')

    const viewports = [
      { width: 1440, height: 900 },
      { width: 1024, height: 768 },
      { width: 768, height: 1024 },
      { width: 390, height: 844 },
    ]
    for (const vp of viewports) {
      await page.setViewportSize(vp)
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      )
      expect(overflow, `Horizontal overflow at ${vp.width}x${vp.height}`).toBe(false)
    }

    expect(pageErrors).toEqual([])
    expect(consoleErrors.filter((e) => !e.includes('WebSocket'))).toEqual([])
  })
})
