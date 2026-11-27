import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import axios from 'axios'
import PublicStatusView from '../PublicStatusView.vue'

describe('PublicStatusView', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders operational banner, components, bars, and recent incidents', async () => {
    vi.spyOn(axios, 'get').mockResolvedValueOnce({
      data: {
        slug: 'acme-cloud',
        title: 'Acme Cloud Status',
        description: 'Live platform health.',
        accent_color: '#0ea5e9',
        overall_status: 'operational',
        updated_at: '2026-11-27T12:00:00Z',
        components: [
          {
            id: 'chk-1',
            name: 'Public API',
            kind: 'uptime',
            status: 'operational',
            uptime_24h: 99.98,
            recent_statuses: ['up', 'up', 'up'],
          },
        ],
        incidents: [
          {
            id: 'inc-1',
            title: 'Brief edge spike',
            severity: 'warning',
            status: 'resolved',
            opened_at: '2026-11-26T10:00:00Z',
            resolved_at: '2026-11-26T10:15:00Z',
          },
        ],
      },
    } as never)

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/status/:slug', component: PublicStatusView }],
    })
    await router.push('/status/acme-cloud')
    await router.isReady()

    const wrapper = mount(PublicStatusView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('Acme Cloud Status')
    expect(wrapper.text()).toContain('All Systems Operational')
    expect(wrapper.text()).toContain('Public API')
    expect(wrapper.text()).toContain('99.98% (24h)')
    expect(wrapper.text()).toContain('Brief edge spike')
  })

  it('shows not found state when status page is private or missing', async () => {
    vi.spyOn(axios, 'get').mockRejectedValueOnce({ response: { status: 404 } })

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/status/:slug', component: PublicStatusView }],
    })
    await router.push('/status/missing-slug')
    await router.isReady()

    const wrapper = mount(PublicStatusView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('Status page not found')
  })
})
