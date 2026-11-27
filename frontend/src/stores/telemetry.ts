import { markRaw } from 'vue'
import { defineStore } from 'pinia'
import axios from 'axios'
import type { ServerRecord } from '../api/client'
import { parseSparkline } from '../utils/format'

export interface MetricSample {
  server_id: string
  cpu_usage: number
  ram_usage: number
  disk_io?: number | null
  timestamp: string
}

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'reconnecting'

interface TelemetryBatchMessage {
  type?: string
  samples?: MetricSample[]
  server_id?: string
  cpu_usage?: number
  ram_usage?: number
  disk_io?: number | null
  timestamp?: string
}

const MAX_POINTS_PER_SERVER = 30
const BASE_RECONNECT_MS = 1000
const MAX_RECONNECT_MS = 30000

export const useTelemetryStore = defineStore('telemetry', {
  state: () => ({
    socket: null as WebSocket | null,
    connectionState: 'disconnected' as ConnectionState,
    metrics: {} as Record<string, MetricSample[]>,
    lastSeen: {} as Record<string, string>,
    liveServerIds: {} as Record<string, boolean>,
    latestSample: null as MetricSample | null,
    sampleVersion: 0,
    reconnectAttempts: 0,
    reconnectTimer: null as ReturnType<typeof setTimeout> | null,
    shouldReconnect: false,
    connectingPromise: null as Promise<void> | null,
  }),
  actions: {
    buildWsUrl(ticket: string): string {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const host = window.location.host === 'localhost:5173' ? 'localhost:8000' : window.location.host
      return `${protocol}//${host}/ws/telemetry/?ticket=${encodeURIComponent(ticket)}`
    },
    async connect() {
      if (this.socket || this.connectingPromise) {
        return
      }
      this.shouldReconnect = true
      this.connectionState = this.reconnectAttempts > 0 ? 'reconnecting' : 'connecting'

      const run = async () => {
        try {
          const response = await axios.post<{ ticket: string }>('/api/accounts/auth/ticket/')
          if (!this.shouldReconnect) {
            this.connectionState = 'disconnected'
            return
          }
          const ticket = response.data?.ticket
          if (!ticket) {
            throw new Error('Missing WebSocket ticket')
          }

          const ws = markRaw(new WebSocket(this.buildWsUrl(ticket)))

          ws.onopen = () => {
            this.reconnectAttempts = 0
            this.connectionState = 'connected'
          }

          ws.onmessage = (event) => {
            try {
              const payload = JSON.parse(event.data) as TelemetryBatchMessage
              if (payload.type === 'telemetry_batch' && Array.isArray(payload.samples)) {
                this.ingestSamples(payload.samples)
              } else if (
                payload.server_id &&
                typeof payload.cpu_usage === 'number' &&
                typeof payload.ram_usage === 'number'
              ) {
                this.ingestSamples([
                  {
                    server_id: payload.server_id,
                    cpu_usage: payload.cpu_usage,
                    ram_usage: payload.ram_usage,
                    disk_io: payload.disk_io ?? null,
                    timestamp: payload.timestamp || new Date().toISOString(),
                  },
                ])
              }
            } catch {
              return
            }
          }

          ws.onclose = (event) => {
            if (this.socket === ws) {
              this.socket = null
            }
            if (!this.shouldReconnect || event?.code === 4401 || event?.code === 4403) {
              this.connectionState = 'disconnected'
              return
            }
            this.scheduleReconnect()
          }

          ws.onerror = () => {
            ws.close()
          }

          this.socket = ws
        } catch (error) {
          const status = axios.isAxiosError(error) ? error.response?.status : undefined
          if (!this.shouldReconnect || status === 401 || status === 403) {
            this.connectionState = 'disconnected'
            return
          }
          this.scheduleReconnect()
        } finally {
          this.connectingPromise = null
        }
      }

      this.connectingPromise = markRaw(run())
      await this.connectingPromise
    },
    scheduleReconnect() {
      if (!this.shouldReconnect) {
        this.connectionState = 'disconnected'
        return
      }
      if (this.reconnectTimer !== null) {
        clearTimeout(this.reconnectTimer)
      }
      this.connectionState = 'reconnecting'
      const expDelay = Math.min(BASE_RECONNECT_MS * Math.pow(2, this.reconnectAttempts), MAX_RECONNECT_MS)
      const jitter = Math.floor(Math.random() * Math.min(expDelay * 0.25, 2000))
      const delay = Math.min(expDelay + jitter, MAX_RECONNECT_MS)
      this.reconnectAttempts = Math.min(this.reconnectAttempts + 1, 10)

      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null
        if (!this.shouldReconnect) {
          return
        }
        this.connect()
      }, delay)
    },
    seedSparklines(servers: ServerRecord[]) {
      for (const server of servers) {
        const existing = this.metrics[server.id]
        if (existing && existing.length > 0) {
          continue
        }
        const points = parseSparkline(server.sparkline)
        if (points.length > 0) {
          this.metrics[server.id] = points.slice(-MAX_POINTS_PER_SERVER).map((pt) => ({
            server_id: server.id,
            cpu_usage: pt.cpu,
            ram_usage: pt.ram,
            timestamp: pt.t,
          }))
        }
      }
    },
    ingestSamples(samples: MetricSample[]) {
      for (const raw of samples) {
        if (!raw || !raw.server_id) {
          continue
        }
        const sample: MetricSample = {
          server_id: raw.server_id,
          cpu_usage: raw.cpu_usage,
          ram_usage: raw.ram_usage,
          disk_io: raw.disk_io ?? null,
          timestamp: raw.timestamp || new Date().toISOString(),
        }
        if (!this.metrics[sample.server_id]) {
          this.metrics[sample.server_id] = []
        }
        this.metrics[sample.server_id].push(sample)
        if (this.metrics[sample.server_id].length > MAX_POINTS_PER_SERVER) {
          this.metrics[sample.server_id].shift()
        }
        this.lastSeen[sample.server_id] = sample.timestamp
        this.liveServerIds[sample.server_id] = true
        this.latestSample = sample
        this.sampleVersion += 1
      }
    },
    disconnectAll() {
      this.shouldReconnect = false
      if (this.reconnectTimer !== null) {
        clearTimeout(this.reconnectTimer)
        this.reconnectTimer = null
      }
      if (this.socket) {
        this.socket.onclose = null
        this.socket.onerror = null
        this.socket.close()
        this.socket = null
      }
      this.connectingPromise = null
      this.connectionState = 'disconnected'
      this.reconnectAttempts = 0
      this.metrics = {}
      this.lastSeen = {}
      this.liveServerIds = {}
      this.latestSample = null
    },
  },
})
