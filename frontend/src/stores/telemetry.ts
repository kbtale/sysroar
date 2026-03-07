import { defineStore } from 'pinia'

interface TelemetryData {
  cpu_usage: number
  ram_usage: number
  disk_io: number
  timestamp: string
}

export const useTelemetryStore = defineStore('telemetry', {
  state: () => ({
    servers: {} as Record<string, TelemetryData>,
  }),
  actions: {
    updateServer(serverId: string, data: TelemetryData) {
      this.servers[serverId] = data
    }
  }
})
