import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import axios from 'axios'
import { ejectAuthInterceptor, setupAuthInterceptor, useAuthStore } from '../auth'
import { useTelemetryStore } from '../telemetry'
import { useThemeStore } from '../theme'

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  url: string
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: ((event?: { code?: number }) => void) | null = null
  onerror: (() => void) | null = null
  closed = false

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  close() {
    this.closed = true
    if (this.onclose) {
      this.onclose({ code: 1000 })
    }
  }
}

describe('auth, theme, and telemetry lifecycle', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.useFakeTimers()
  })

  afterEach(() => {
    ejectAuthInterceptor()
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('hydrates session from HttpOnly cookie via /auth/me without using localStorage', async () => {
    const getSpy = vi.spyOn(axios, 'get').mockImplementation(async (url: string) => {
      if (url === '/api/accounts/auth/csrf/') {
        return { data: { csrfToken: 'csrf-123' } } as never
      }
      if (url === '/api/accounts/setup/status/') {
        return { data: { needs_setup: false, open_registration: false } } as never
      }
      if (url === '/api/accounts/auth/me/') {
        return {
          data: {
            user: {
              id: 'u-1',
              username: 'alice',
              email: 'alice@example.com',
              role: 'admin',
              company_id: 'c-1',
              company_name: 'Acme',
              is_superuser: false,
            },
          },
        } as never
      }
      throw new Error(`Unexpected GET ${url}`)
    })

    const auth = useAuthStore()
    await auth.initAuth()

    expect(axios.defaults.withCredentials).toBe(true)
    expect(axios.defaults.xsrfCookieName).toBe('csrftoken')
    expect(axios.defaults.xsrfHeaderName).toBe('X-CSRFToken')
    expect(auth.isAuthenticated).toBe(true)
    expect(auth.isAdmin).toBe(true)
    expect(auth.canWrite).toBe(true)
    expect(auth.user?.username).toBe('alice')
    expect(localStorage.getItem('sysroar_token')).toBeNull()
    expect(getSpy).toHaveBeenCalledTimes(3)
  })

  it('detects first-run setup needed and skips /auth/me', async () => {
    vi.spyOn(axios, 'get').mockImplementation(async (url: string) => {
      if (url === '/api/accounts/auth/csrf/') {
        return { data: { csrfToken: 'csrf-123' } } as never
      }
      if (url === '/api/accounts/setup/status/') {
        return { data: { needs_setup: true, open_registration: false } } as never
      }
      throw new Error(`Unexpected GET ${url}`)
    })

    const auth = useAuthStore()
    await auth.initAuth()

    expect(auth.needsSetup).toBe(true)
    expect(auth.isAuthenticated).toBe(false)
  })

  it('clears session, closes sockets, and triggers callback on 401 response', async () => {
    const auth = useAuthStore()
    auth.user = {
      id: 'u-1',
      username: 'alice',
      email: 'alice@example.com',
      role: 'viewer',
      company_id: 'c-1',
      company_name: 'Acme',
      is_superuser: false,
    }
    expect(auth.canWrite).toBe(false)

    const telemetry = useTelemetryStore()
    const socket = new FakeWebSocket('ws://localhost:8000/ws/telemetry/srv-1/?ticket=t1')
    telemetry.sockets['srv-1'] = socket as unknown as WebSocket

    const onUnauthorized = vi.fn()
    setupAuthInterceptor(onUnauthorized)

    const adapter = vi.fn().mockRejectedValue({
      response: { status: 401 },
      config: { url: '/api/monitoring/servers/' },
      isAxiosError: true,
    })

    await expect(axios.get('/api/monitoring/servers/', { adapter })).rejects.toBeTruthy()

    expect(auth.isAuthenticated).toBe(false)
    expect(auth.user).toBeNull()
    expect(socket.closed).toBe(true)
    expect(Object.keys(telemetry.sockets)).toHaveLength(0)
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })

  it('logoutAll posts to logout-all endpoint and closes sockets', async () => {
    const postSpy = vi.spyOn(axios, 'post').mockResolvedValue({ status: 204 } as never)
    const auth = useAuthStore()
    auth.user = {
      id: 'u-1',
      username: 'alice',
      email: 'alice@example.com',
      role: 'owner',
      company_id: 'c-1',
      company_name: 'Acme',
      is_superuser: false,
    }

    const telemetry = useTelemetryStore()
    const socket = new FakeWebSocket('ws://localhost:8000/ws/telemetry/srv-1/?ticket=t1')
    telemetry.sockets['srv-1'] = socket as unknown as WebSocket

    await auth.logoutAll()

    expect(postSpy).toHaveBeenCalledWith('/api/accounts/auth/logout-all/')
    expect(auth.isAuthenticated).toBe(false)
    expect(socket.closed).toBe(true)
  })

  it('persists and applies dark and light theme attributes', () => {
    const theme = useThemeStore()
    theme.setTheme('light')
    expect(theme.isDark).toBe(false)
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem('sysroar_theme')).toBe('light')

    theme.toggleTheme()
    expect(theme.isDark).toBe(true)
    expect(document.documentElement.dataset.theme).toBe('dark')
  })
})
