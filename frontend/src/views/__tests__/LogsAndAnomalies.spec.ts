import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createMemoryHistory, createRouter } from 'vue-router'
import axios from 'axios'
import LogViewer from '../../components/LogViewer.vue'
import DashboardView from '../DashboardView.vue'
import { useAuthStore } from '../../stores/auth'

describe('Logs UI and Anomaly Hints', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('LogViewer queries tenant logs and renders matching lines', async () => {
    vi.spyOn(axios, 'get').mockImplementation(async (url: string) => {
      if (url === '/api/monitoring/servers/') {
        return { data: { results: [{ id: 'srv-1', name: 'web-01' }] } } as never
      }
      if (url === '/api/logs/query/') {
        return {
          data: {
            enabled: true,
            backend: 'loki',
            entries: [
              {
                timestamp: '2026-11-27T12:00:00Z',
                level: 'ERROR',
                message: 'upstream gateway timeout on /checkout',
                server_id: 'srv-1',
                source: 'nginx',
                labels: { level: 'ERROR', source: 'nginx' },
              },
            ],
          },
        } as never
      }
      return { data: {} } as never
    })

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = mount(LogViewer, {
      global: { plugins: [[VueQueryPlugin, { queryClient }]] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('ERROR')
    expect(wrapper.text()).toContain('upstream gateway timeout on /checkout')
    expect(wrapper.text()).toContain('nginx')
  })

  it('DashboardView displays Unusual for this server badge when anomalies exist', async () => {
    const auth = useAuthStore()
    auth.user = {
      id: 'u1',
      username: 'admin',
      email: 'admin@example.com',
      company_id: 'c1',
      company_name: 'Acme',
      role: 'admin',
      is_superuser: false,
    }

    vi.spyOn(axios, 'get').mockImplementation(async (url: string) => {
      if (url === '/api/monitoring/servers/') {
        return {
          data: {
            results: [
              {
                id: 'srv-1',
                name: 'spike-host',
                hostname: 'spike-host.local',
                ip_address: '10.0.0.5',
                status: 'online',
                alert_status: 'ok',
                tags: ['prod'],
                sparkline: [],
                anomalies: [
                  {
                    metric: 'cpu',
                    label: 'CPU',
                    current: 91.2,
                    baseline: 22.0,
                    z_score: 6.4,
                    message: 'CPU is 91.2% vs 22.0% baseline',
                  },
                ],
              },
            ],
          },
        } as never
      }
      return { data: {} } as never
    })

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: DashboardView },
        { path: '/servers/:id', component: { template: '<div />' } },
      ],
    })
    await router.push('/')
    await router.isReady()

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = mount(DashboardView, {
      global: {
        plugins: [router, [VueQueryPlugin, { queryClient }]],
        stubs: { MetricChart: true },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('spike-host')
    expect(wrapper.text()).toContain('Unusual for this server')
  })
})
