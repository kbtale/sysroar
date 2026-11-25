import { defineStore } from 'pinia'
import axios from 'axios'

interface MetricData {
  cpu_usage: number
  ram_usage: number
  timestamp: string
}

interface Server {
  id: string
  name: string
  ip_address: string | null
  os_info: string | null
  last_seen: string | null
  status: 'online' | 'offline' | 'unknown'
}

interface RawTelemetryPayload {
  cpu_usage: number
  ram_usage: number
  timestamp?: string
}

export const useTelemetryStore = defineStore('telemetry', {
  state: () => ({
    servers: [] as Server[],
    metrics: {} as Record<string, MetricData[]>,
    sockets: {} as Record<string, WebSocket>,
    reconnectAttempts: {} as Record<string, number>,
    reconnectTimers: {} as Record<string, ReturnType<typeof setTimeout>>,
    shouldReconnect: true,
  }),
  actions: {
    async fetchServers() {
      this.shouldReconnect = true
      try {
        const response = await axios.get('/api/monitoring/servers/')
        this.servers = response.data.results || response.data

        this.servers.forEach((server) => {
          this.subscribeToServer(server.id)
        })
      } catch (error) {
        console.error('Failed to fetch servers', error)
      }
    },
    async subscribeToServer(serverId: string) {
      if (this.sockets[serverId] || !this.shouldReconnect || !localStorage.getItem('sysroar_token')) {
        return
      }

      try {
        const ticketResponse = await axios.post('/api/accounts/auth/ticket/')
        if (!this.shouldReconnect) {
          return
        }
        const ticket = ticketResponse.data.ticket

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
        const host = window.location.host === 'localhost:5173' ? 'localhost:8000' : window.location.host
        const wsUrl = `${protocol}//${host}/ws/telemetry/${serverId}/?ticket=${ticket}`

        const socket = new WebSocket(wsUrl)

        socket.onopen = () => {
          this.reconnectAttempts[serverId] = 0
        }

        socket.onmessage = (event) => {
          const data = JSON.parse(event.data) as RawTelemetryPayload
          this.addMetric(serverId, data)
        }

        socket.onclose = (event) => {
          delete this.sockets[serverId]
          if (this.shouldReconnect && event?.code !== 4401 && event?.code !== 4403) {
            this.handleReconnect(serverId)
          }
        }

        socket.onerror = () => {
          socket.close()
        }

        this.sockets[serverId] = socket
      } catch (error) {
        console.error(`Status check for ticket or socket failed for ${serverId}`, error)
        if (this.shouldReconnect && localStorage.getItem('sysroar_token')) {
          this.handleReconnect(serverId)
        }
      }
    },
    handleReconnect(serverId: string) {
      if (!this.shouldReconnect || !localStorage.getItem('sysroar_token')) {
        return
      }
      const attempts = this.reconnectAttempts[serverId] || 0
      if (attempts > 10) {
        return
      }

      if (this.reconnectTimers[serverId]) {
        clearTimeout(this.reconnectTimers[serverId])
      }

      const delay = Math.min(1000 * Math.pow(2, attempts), 30000)

      this.reconnectTimers[serverId] = setTimeout(() => {
        delete this.reconnectTimers[serverId]
        if (!this.shouldReconnect) {
          return
        }
        this.reconnectAttempts[serverId] = attempts + 1
        this.subscribeToServer(serverId)
      }, delay)
    },
    disconnectAll() {
      this.shouldReconnect = false
      Object.values(this.reconnectTimers).forEach((timer) => clearTimeout(timer))
      this.reconnectTimers = {}

      Object.values(this.sockets).forEach((socket) => {
        socket.onclose = null
        socket.onerror = null
        socket.close()
      })
      this.sockets = {}
      this.reconnectAttempts = {}
      this.servers = []
      this.metrics = {}
    },
    addMetric(serverId: string, data: RawTelemetryPayload) {
      if (!this.metrics[serverId]) {
        this.metrics[serverId] = []
      }

      const metric: MetricData = {
        cpu_usage: data.cpu_usage,
        ram_usage: data.ram_usage,
        timestamp: data.timestamp || new Date().toISOString(),
      }

      this.metrics[serverId].push(metric)

      if (this.metrics[serverId].length > 20) {
        this.metrics[serverId].shift()
      }
    },
  },
})
