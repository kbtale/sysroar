import { defineStore } from 'pinia'
import axios from 'axios'

interface MetricData {
  cpu_usage: number
  ram_usage: number
  timestamp: string
}

interface Server {
  id: string
  hostname: string
  ip_address: string
  status: string
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
  }),
  actions: {
    async fetchServers() {
      try {
        const response = await axios.get('/api/monitoring/servers/')
        this.servers = response.data.results || response.data
        
        // Start subscriptions for all servers
        this.servers.forEach(server => {
          this.subscribeToServer(server.id)
        })
      } catch (error) {
        console.error('Failed to fetch servers', error)
      }
    },
    async subscribeToServer(serverId: string) {
      if (this.sockets[serverId]) return

      try {
        // Request a one-time ticket
        const ticketResponse = await axios.post('/api/accounts/auth/ticket/')
        const ticket = ticketResponse.data.ticket
        
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
        const host = window.location.host === 'localhost:5173' ? 'localhost:8000' : window.location.host
        const wsUrl = `${protocol}//${host}/ws/telemetry/${serverId}/?ticket=${ticket}`
        
        const socket = new WebSocket(wsUrl)
        
        socket.onopen = () => {
          console.log(`Connected to server ${serverId}`)
          this.reconnectAttempts[serverId] = 0
        }

        socket.onmessage = (event) => {
          const data = JSON.parse(event.data) as RawTelemetryPayload
          this.addMetric(serverId, data)
        }
        
        socket.onclose = () => {
          delete this.sockets[serverId]
          this.handleReconnect(serverId)
        }

        socket.onerror = () => {
          socket.close()
        }
        
        this.sockets[serverId] = socket
      } catch (error) {
        console.error(`Status check for ticket or socket failed for ${serverId}`, error)
        this.handleReconnect(serverId)
      }
    },
    handleReconnect(serverId: string) {
      const attempts = this.reconnectAttempts[serverId] || 0
      if (attempts > 10) {
        console.error(`Max reconnection attempts reached for server ${serverId}`)
        return
      }

      const delay = Math.min(1000 * Math.pow(2, attempts), 30000)
      console.log(`Reconnecting to ${serverId} in ${delay}ms (attempt ${attempts + 1})`)
      
      setTimeout(() => {
        this.reconnectAttempts[serverId] = attempts + 1
        this.subscribeToServer(serverId)
      }, delay)
    },
    addMetric(serverId: string, data: RawTelemetryPayload) {
      if (!this.metrics[serverId]) {
        this.metrics[serverId] = []
      }
      
      const metric: MetricData = {
        cpu_usage: data.cpu_usage,
        ram_usage: data.ram_usage,
        timestamp: data.timestamp || new Date().toISOString()
      }
      
      this.metrics[serverId].push(metric)
      
      // Keep only last 20 points
      if (this.metrics[serverId].length > 20) {
        this.metrics[serverId].shift()
      }
    }
  }
})
