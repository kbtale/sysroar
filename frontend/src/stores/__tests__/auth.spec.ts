import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import axios from 'axios'
import { ejectAuthInterceptor, setupAuthInterceptor, useAuthStore } from '../auth'
import { useTelemetryStore } from '../telemetry'

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

describe('auth and telemetry lifecycle', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    delete axios.defaults.headers.common['Authorization']
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.useFakeTimers()
  })

  afterEach(() => {
    ejectAuthInterceptor()
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('restores Authorization header from stored token on initAuth', () => {
    localStorage.setItem('sysroar_token', 'persisted-token-123')
    const auth = useAuthStore()

    auth.initAuth()

    expect(auth.isAuthenticated).toBe(true)
    expect(axios.defaults.headers.common['Authorization']).toBe('Token persisted-token-123')
  })

  it('logs out, closes sockets, and triggers callback on 401 response', async () => {
    localStorage.setItem('sysroar_token', 'expired-token')
    const auth = useAuthStore()
    auth.initAuth()

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

    expect(auth.token).toBeNull()
    expect(localStorage.getItem('sysroar_token')).toBeNull()
    expect(axios.defaults.headers.common['Authorization']).toBeUndefined()
    expect(socket.closed).toBe(true)
    expect(Object.keys(telemetry.sockets)).toHaveLength(0)
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })

  it('cancels reconnect timers and closes sockets on disconnectAll', () => {
    localStorage.setItem('sysroar_token', 'valid-token')
    const telemetry = useTelemetryStore()
    const subscribeSpy = vi.spyOn(telemetry, 'subscribeToServer').mockResolvedValue()

    const socket = new FakeWebSocket('ws://localhost:8000/ws/telemetry/srv-1/?ticket=t1')
    telemetry.sockets['srv-1'] = socket as unknown as WebSocket
    telemetry.handleReconnect('srv-1')

    telemetry.disconnectAll()
    vi.advanceTimersByTime(60000)

    expect(socket.closed).toBe(true)
    expect(Object.keys(telemetry.sockets)).toHaveLength(0)
    expect(subscribeSpy).not.toHaveBeenCalled()
  })
})
