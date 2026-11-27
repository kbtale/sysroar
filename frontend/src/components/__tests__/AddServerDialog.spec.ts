import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createMemoryHistory, createRouter } from 'vue-router'
import axios from 'axios'
import AddServerDialog from '../AddServerDialog.vue'
import { useAuthStore } from '../../stores/auth'

describe('AddServerDialog onboarding wizard', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('generates enrollment token, shows copyable install command, and transitions on new server heartbeat', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.user = {
      id: 'u-1',
      username: 'owner',
      email: 'owner@example.com',
      role: 'owner',
      company_id: 'c-1',
      company_name: 'Acme',
      is_superuser: false,
    }

    let pollStep = 0
    vi.spyOn(axios, 'get').mockImplementation(async (url: string) => {
      if (url === '/api/monitoring/servers/') {
        pollStep += 1
        if (pollStep === 1) {
          return { data: { results: [] } } as never
        }
        return {
          data: {
            results: [
              {
                id: 'srv-new-1',
                name: 'edge-node-01',
                ip_address: '10.1.0.5',
                status: 'online',
                alert_status: 'ok',
                tags: [],
                sparkline: [],
              },
            ],
          },
        } as never
      }
      throw new Error(`Unexpected GET ${url}`)
    })

    const postSpy = vi.spyOn(axios, 'post').mockResolvedValue({
      data: {
        id: 'et-1',
        prefix: 'sre_abc123',
        token: 'sre_abc123.secretpayload',
      },
    } as never)

    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    })

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div />' } },
        { path: '/servers/:id', component: { template: '<div />' } },
      ],
    })
    await router.push('/')
    await router.isReady()

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = mount(AddServerDialog, {
      props: { open: true },
      global: {
        plugins: [pinia, router, [VueQueryPlugin, { queryClient }]],
      },
      attachTo: document.body,
    })

    await flushPromises()
    const form = document.body.querySelector('form')
    expect(form).toBeTruthy()
    form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await flushPromises()

    expect(postSpy).toHaveBeenCalledWith(
      '/api/monitoring/enrollment-tokens/',
      expect.objectContaining({ name: 'production-host', max_uses: 1 }),
    )
    expect(document.body.textContent).toContain('sre_abc123.secretpayload')
    expect(document.body.textContent).toContain('Waiting for first heartbeat')

    const copyBtn = Array.from(document.body.querySelectorAll('button')).find((b) =>
      b.getAttribute('aria-label')?.includes('Copy enrollment token'),
    )
    expect(copyBtn).toBeTruthy()
    copyBtn!.click()
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith('sre_abc123.secretpayload')

    await vi.advanceTimersByTimeAsync(3100)
    await flushPromises()

    expect(document.body.textContent).toContain('Host Connected')
    expect(document.body.textContent).toContain('edge-node-01')

    wrapper.unmount()
  })
})
