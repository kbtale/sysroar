import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import axios from 'axios'
import UptimeView from '../UptimeView.vue'
import { useAuthStore, type CompanyRole } from '../../stores/auth'

vi.mock('../../components/TimeSeriesChart.vue', () => ({
  default: {
    name: 'TimeSeriesChart',
    props: ['title'],
    template: '<div class="ts-stub">{{ title }}</div>',
  },
}))

async function mountUptime(role: CompanyRole) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.user = {
    id: 'u-1',
    username: 'ops',
    email: 'ops@acme.test',
    role,
    company_id: 'c-1',
    company_name: 'Acme',
    is_superuser: false,
  }

  vi.spyOn(axios, 'get').mockImplementation(async (url: string) => {
    if (url === '/api/monitoring/uptime-checks/') {
      return {
        data: {
          results: [
            {
              id: 'chk-1',
              name: 'Public API',
              check_type: 'http',
              target: 'https://api.example.com/health',
              port: null,
              expected_status: 200,
              expected_keyword: 'ok',
              ssl_expiry_warning_days: 14,
              interval_seconds: 60,
              timeout_seconds: 10,
              allow_private_targets: false,
              channel: null,
              tags: [],
              is_active: true,
              last_status: 'up',
              last_latency_ms: 42.5,
              last_ssl_expiry_days: 60,
              last_error: '',
              last_checked_at: new Date().toISOString(),
              consecutive_failures: 0,
              uptime_24h_percent: 99.95,
              recent_statuses: ['up', 'up', 'up'],
              created_at: '2026-11-26T00:00:00Z',
            },
          ],
        },
      } as never
    }
    if (url === '/api/monitoring/channels/') {
      return { data: { results: [] } } as never
    }
    if (url === '/api/monitoring/uptime-checks/chk-1/results/') {
      return { data: [] } as never
    }
    throw new Error(`Unexpected GET ${url}`)
  })

  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = mount(UptimeView, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] },
    attachTo: document.body,
  })
  await flushPromises()
  return wrapper
}

describe('UptimeView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders uptime checks, SSL expiry badge, and triggers on-demand run', async () => {
    const postSpy = vi.spyOn(axios, 'post').mockResolvedValue({ data: { status: 'up' } } as never)
    const wrapper = await mountUptime('member')

    expect(wrapper.text()).toContain('Public API')
    expect(wrapper.text()).toContain('99.95%')
    expect(wrapper.text()).toContain('SSL 60d')

    const runBtn = wrapper.findAll('button').find((b) => b.text().trim() === 'Run')
    expect(runBtn).toBeTruthy()
    await runBtn!.trigger('click')
    await flushPromises()
    expect(postSpy).toHaveBeenCalledWith('/api/monitoring/uptime-checks/chk-1/run/')

    wrapper.unmount()
  })

  it('hides mutating actions for viewer role', async () => {
    const wrapper = await mountUptime('viewer')
    expect(wrapper.text()).toContain('Public API')
    expect(wrapper.text()).not.toContain('Add Check')
    expect(wrapper.findAll('button').some((b) => b.text().trim() === 'Run')).toBe(false)
    wrapper.unmount()
  })
})
