import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createMemoryHistory, createRouter } from 'vue-router'
import axios from 'axios'
import SettingsView from '../SettingsView.vue'
import { useAuthStore, type CompanyRole } from '../../stores/auth'

function mockSettingsApis() {
  vi.spyOn(axios, 'get').mockImplementation(async (url: string) => {
    if (url === '/api/accounts/companies/') {
      return {
        data: {
          results: [{ id: 'c-1', name: 'Acme Ops', retention_days: 30, created_at: '2026-11-01T00:00:00Z' }],
        },
      } as never
    }
    if (url === '/api/accounts/members/') {
      return {
        data: {
          results: [
            {
              id: 'u-1',
              username: 'owner',
              email: 'owner@acme.test',
              role: 'owner',
              is_active: true,
              date_joined: '2026-11-01T00:00:00Z',
            },
          ],
        },
      } as never
    }
    if (url === '/api/accounts/invites/') {
      return { data: { results: [] } } as never
    }
    if (url === '/api/monitoring/servers/') {
      return { data: { results: [{ id: 'srv-1', name: 'web-01' }] } } as never
    }
    if (url === '/api/monitoring/agent-keys/') {
      return {
        data: {
          results: [
            {
              id: 'k-1',
              server: 'srv-1',
              prefix: 'srk_1111',
              is_active: true,
              created_at: '2026-11-01T00:00:00Z',
              last_used_at: null,
              revoked_at: null,
            },
          ],
        },
      } as never
    }
    if (url === '/api/monitoring/enrollment-tokens/') {
      return { data: { results: [] } } as never
    }
    if (url === '/api/monitoring/audit-logs/') {
      return { data: { results: [] } } as never
    }
    throw new Error(`Unexpected GET ${url}`)
  })
}

async function mountSettings(role: CompanyRole, initialUrl = '/settings') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.user = {
    id: 'u-1',
    username: 'owner',
    email: 'owner@acme.test',
    role,
    company_id: 'c-1',
    company_name: 'Acme Ops',
    is_superuser: false,
  }

  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/settings', component: SettingsView },
      { path: '/login', component: { template: '<div />' } },
    ],
  })
  await router.push(initialUrl)
  await router.isReady()

  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = mount(SettingsView, {
    global: {
      plugins: [pinia, router, [VueQueryPlugin, { queryClient }]],
    },
    attachTo: document.body,
  })
  await flushPromises()
  return { wrapper, router }
}

describe('SettingsView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('creates an invite with copyable link when SMTP is disabled and rotates agent keys', async () => {
    mockSettingsApis()
    const postSpy = vi.spyOn(axios, 'post').mockImplementation(async (url: string) => {
      if (url === '/api/accounts/invites/') {
        return {
          data: {
            invite_url: 'http://localhost:5173/accept-invite?token=sri_123.secret',
            email_sent: false,
          },
        } as never
      }
      if (url === '/api/monitoring/agent-keys/rotate/') {
        return {
          data: {
            prefix: 'srk_2222',
            key: 'srk_2222.newsecretkey',
          },
        } as never
      }
      throw new Error(`Unexpected POST ${url}`)
    })

    const { wrapper } = await mountSettings('owner', '/settings?tab=members')
    const inviteBtn = wrapper.findAll('button').find((b) => b.text().includes('Invite Member'))
    expect(inviteBtn).toBeTruthy()
    await inviteBtn!.trigger('click')
    await flushPromises()

    const emailInput = document.body.querySelector('input[type="email"]') as HTMLInputElement | null
    expect(emailInput).toBeTruthy()
    emailInput!.value = 'newdev@acme.test'
    emailInput!.dispatchEvent(new Event('input', { bubbles: true }))
    await flushPromises()

    const form = document.body.querySelector('form')
    expect(form).toBeTruthy()
    form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await flushPromises()

    expect(postSpy).toHaveBeenCalledWith(
      '/api/accounts/invites/',
      expect.objectContaining({ email: 'newdev@acme.test' }),
    )
    expect(document.body.textContent).toContain('http://localhost:5173/accept-invite?token=sri_123.secret')

    const closeBtn = Array.from(document.body.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Done',
    )
    closeBtn?.click()
    await flushPromises()

    const keysTab = wrapper.findAll('[role="tab"]').find((t) => t.text().includes('Keys'))
    expect(keysTab).toBeTruthy()
    await keysTab!.trigger('click')
    await flushPromises()

    const rotateBtn = wrapper.findAll('button').find((b) => b.text().includes('Rotate'))
    expect(rotateBtn).toBeTruthy()
    await rotateBtn!.trigger('click')
    await flushPromises()

    expect(postSpy).toHaveBeenCalledWith('/api/monitoring/agent-keys/rotate/', { server: 'srv-1' })
    expect(document.body.textContent).toContain('srk_2222.newsecretkey')

    wrapper.unmount()
  })

  it('hides admin tabs for viewer role', async () => {
    mockSettingsApis()
    const { wrapper } = await mountSettings('viewer')

    expect(wrapper.text()).toContain('Company')
    expect(wrapper.text()).toContain('Security')
    expect(wrapper.text()).not.toContain('Members & Invites')
    expect(wrapper.text()).not.toContain('Keys & Tokens')
    expect(wrapper.text()).not.toContain('Audit Log')
    expect(wrapper.text()).not.toContain('Save Workspace')

    wrapper.unmount()
  })
})
