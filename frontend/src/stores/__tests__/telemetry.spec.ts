import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import axios from 'axios'
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

describe('multiplexed telemetry store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('opens a single multiplexed WebSocket without localStorage token and ingests batches', async () => {
    const postSpy = vi.spyOn(axios, 'post').mockResolvedValue({ data: { ticket: 'ws-ticket-99' } } as never)
    const store = useTelemetryStore()

    await store.connect()
    await store.connect()

    expect(postSpy).toHaveBeenCalledTimes(1)
    expect(postSpy).toHaveBeenCalledWith('/api/accounts/auth/ticket/')
    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(FakeWebSocket.instances[0].url).toContain('/ws/telemetry/?ticket=ws-ticket-99')

    FakeWebSocket.instances[0].onopen?.()
    expect(store.connectionState).toBe('connected')

    FakeWebSocket.instances[0].onmessage?.({
      data: JSON.stringify({
        type: 'telemetry_batch',
        samples: [
          { server_id: 'srv-a', cpu_usage: 42.5, ram_usage: 61.2, timestamp: '2026-11-26T10:00:00Z' },
          { server_id: 'srv-b', cpu_usage: 18.0, ram_usage: 33.4, timestamp: '2026-11-26T10:00:01Z' },
        ],
      }),
    })

    expect(store.metrics['srv-a']).toHaveLength(1)
    expect(store.metrics['srv-a'][0].cpu_usage).toBe(42.5)
    expect(store.metrics['srv-b'][0].ram_usage).toBe(33.4)
    expect(store.liveServerIds['srv-a']).toBe(true)
    expect(store.lastSeen['srv-b']).toBe('2026-11-26T10:00:01Z')
  })

  it('reconnects with backoff on transient drop and stops on 4401', async () => {
    vi.spyOn(axios, 'post').mockResolvedValue({ data: { ticket: 'tk-1' } } as never)
    const store = useTelemetryStore()
    await store.connect()

    const first = FakeWebSocket.instances[0]
    first.onclose?.({ code: 1006 })
    expect(store.connectionState).toBe('reconnecting')

    await vi.advanceTimersByTimeAsync(2500)
    expect(FakeWebSocket.instances).toHaveLength(2)

    FakeWebSocket.instances[1].onclose?.({ code: 4401 })
    expect(store.connectionState).toBe('disconnected')
    await vi.advanceTimersByTimeAsync(10000)
    expect(FakeWebSocket.instances).toHaveLength(2)
  })

  it('cleans up socket, timers, and state on disconnectAll', async () => {
    vi.spyOn(axios, 'post').mockResolvedValue({ data: { ticket: 'tk-2' } } as never)
    const store = useTelemetryStore()
    await store.connect()
    store.ingestSamples([{ server_id: 'srv-1', cpu_usage: 10, ram_usage: 20, timestamp: '2026-11-26T10:00:00Z' }])

    store.disconnectAll()
    expect(store.socket).toBeNull()
    expect(store.connectionState).toBe('disconnected')
    expect(Object.keys(store.metrics)).toHaveLength(0)
    expect(FakeWebSocket.instances[0].closed).toBe(true)
  })
})
