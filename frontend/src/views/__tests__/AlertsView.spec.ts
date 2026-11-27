import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createMemoryHistory, createRouter } from 'vue-router'
import axios from 'axios'
import AlertsView from '../AlertsView.vue'
import { useAuthStore, type CompanyRole } from '../../stores/auth'

function mockAlertsApis() {
  vi.spyOn(axios, 'get').mockImplementation(async (url: string) => {
    if (url === '/api/monitoring/servers/') {
      return { data: { results: [{ id: 'srv-1', name: 'web-01', status: 'online', tags: ['prod'] }] } } as never
    }
    if (url === '/api/monitoring/incidents/') {
      return {
        data: {
          results: [
            {
              id: 'inc-1',
              server: 'srv-1',
              server_name: 'web-01',
              rule: 'rule-1',
              title: 'High CPU on web-01',
              severity: 'critical',
              status: 'open',
              trigger_value: 94.2,
              opened_at: '2026-11-26T10:00:00Z',
              comments: [],
            },
          ],
        },
      } as never
    }
    if (url === '/api/monitoring/rules/') {
      return {
        data: {
          results: [
            {
              id: 'rule-1',
              server: 'srv-1',
              server_name: 'web-01',
              scope: 'server',
              tag_filter: '',
              channel: 'ch-1',
              metric_type: 'cpu',
              operator: 'gt',
              severity: 'critical',
              aggregation: 'avg',
              threshold_value: 90,
              duration_minutes: 5,
              is_active: true,
              notification_type: 'WEBHOOK',
              notification_target: 'https://hooks.example.com/a',
            },
          ],
        },
      } as never
    }
    if (url === '/api/monitoring/channels/') {
      return {
        data: {
          results: [
            {
              id: 'ch-1',
              name: 'Ops Webhook',
              channel_type: 'WEBHOOK',
              target: 'https://hooks.example.com/a',
              is_default: true,
              is_active: true,
            },
          ],
        },
      } as never
    }
    if (url === '/api/monitoring/silences/') {
      return { data: { results: [] } } as never
    }
    throw new Error(`Unexpected GET ${url}`)
  })
}

async function mountAlerts(role: CompanyRole, initialUrl = '/alerts') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.user = {
    id: 'u-1',
    username: 'operator',
    email: 'ops@example.com',
    role,
    company_id: 'c-1',
    company_name: 'Acme',
    is_superuser: false,
  }

  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/alerts', component: AlertsView },
      { path: '/servers/:id', component: { template: '<div />' } },
    ],
  })
  await router.push(initialUrl)
  await router.isReady()

  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = mount(AlertsView, {
    global: {
      plugins: [pinia, router, [VueQueryPlugin, { queryClient }]],
    },
    attachTo: document.body,
  })
  await flushPromises()
  return { wrapper, router }
}

describe('AlertsView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('acknowledges incidents and sends test notifications on channels', async () => {
    mockAlertsApis()
    const postSpy = vi.spyOn(axios, 'post').mockResolvedValue({ data: { delivered: true, detail: 'HTTP 200' } } as never)

    const { wrapper } = await mountAlerts('member')
    expect(wrapper.text()).toContain('High CPU on web-01')

    const ackBtn = wrapper.findAll('button').find((b) => b.text().trim() === 'Acknowledge')
    expect(ackBtn).toBeTruthy()
    await ackBtn!.trigger('click')
    await flushPromises()
    expect(postSpy).toHaveBeenCalledWith('/api/monitoring/incidents/inc-1/acknowledge/')

    const channelsTab = wrapper.findAll('[role="tab"]').find((t) => t.text().includes('Channels'))
    expect(channelsTab).toBeTruthy()
    await channelsTab!.trigger('click')
    await flushPromises()

    const testBtn = wrapper.findAll('button').find((b) => b.text().includes('Send Test'))
    expect(testBtn).toBeTruthy()
    await testBtn!.trigger('click')
    await flushPromises()
    expect(postSpy).toHaveBeenCalledWith('/api/monitoring/channels/ch-1/test/')

    wrapper.unmount()
  })

  it('hides mutating controls for viewer role', async () => {
    mockAlertsApis()
    const { wrapper } = await mountAlerts('viewer')

    expect(wrapper.text()).toContain('High CPU on web-01')
    expect(wrapper.text()).not.toContain('New Rule')
    expect(wrapper.text()).not.toContain('Acknowledge')
    expect(wrapper.text()).not.toContain('Resolve')

    wrapper.unmount()
  })
})
