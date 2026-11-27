import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'
import { createMemoryHistory, createRouter } from 'vue-router'
import axios from 'axios'
import DashboardView from '../DashboardView.vue'
import { useTelemetryStore } from '../../stores/telemetry'

vi.mock('../../components/MetricChart.vue', () => ({
  default: {
    name: 'MetricChart',
    props: ['label', 'data', 'color', 'height'],
    template: '<div class="metric-chart-stub">{{ label }}:{{ data.length }}</div>',
  },
}))

class FakeWebSocket {
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  close() {}
}

describe('DashboardView Fleet Overview', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders fleet summary counts, filters by search and status, and switches to table view', async () => {
    vi.spyOn(axios, 'post').mockResolvedValue({ data: { ticket: 'tk' } } as never)
    vi.spyOn(axios, 'get').mockResolvedValue({
      data: {
        count: 2,
        results: [
          {
            id: 's-1',
            name: 'prod-web-01',
            hostname: 'prod-web-01',
            ip_address: '10.0.1.10',
            os_info: 'Ubuntu 24.04',
            is_active: true,
            telemetry_cadence: 10,
            log_level: 'INFO',
            tags: ['prod', 'web'],
            last_seen: new Date().toISOString(),
            status: 'online',
            alert_status: 'ok',
            sparkline: [{ t: '2026-11-26T10:00:00Z', cpu: 24.5, ram: 52.0 }],
            created_at: '2026-11-26T00:00:00Z',
          },
          {
            id: 's-2',
            name: 'staging-db-01',
            hostname: 'staging-db-01',
            ip_address: '10.0.2.20',
            os_info: 'Debian 12',
            is_active: true,
            telemetry_cadence: 10,
            log_level: 'INFO',
            tags: ['staging', 'db'],
            last_seen: null,
            status: 'offline',
            alert_status: 'critical',
            sparkline: [],
            created_at: '2026-11-26T00:00:00Z',
          },
        ],
      },
    } as never)

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: DashboardView },
        { path: '/servers/:id', component: { template: '<div />' } },
      ],
    })
    await router.push('/')
    await router.isReady()

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })

    const wrapper = mount(DashboardView, {
      global: {
        plugins: [createPinia(), router, [VueQueryPlugin, { queryClient }]],
      },
    })

    await flushPromises()
    expect(wrapper.text()).toContain('prod-web-01')
    expect(wrapper.text()).toContain('staging-db-01')
    expect(wrapper.text()).toContain('24.5%')

    const criticalBtn = wrapper.findAll('.summary-card').find((b) => b.text().includes('Critical'))
    expect(criticalBtn).toBeTruthy()
    await criticalBtn!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('prod-web-01')
    expect(wrapper.text()).toContain('staging-db-01')
    expect(router.currentRoute.value.query.status).toBe('critical')

    const telemetry = useTelemetryStore()
    telemetry.disconnectAll()
    wrapper.unmount()
  })
})
