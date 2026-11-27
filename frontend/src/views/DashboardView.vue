<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'
import MetricChart from '../components/MetricChart.vue'

const telemetry = useTelemetryStore()

onMounted(async () => {
  await telemetry.fetchServers()
})

onUnmounted(() => {
  telemetry.disconnectAll()
})

function getCpuData(serverId: string) {
  return (telemetry.metrics[serverId] || []).map((m) => m.cpu_usage)
}

function getRamData(serverId: string) {
  return (telemetry.metrics[serverId] || []).map((m) => m.ram_usage)
}
</script>

<template>
  <section class="fleet-page">
    <header class="page-header">
      <h1>Fleet Overview</h1>
      <div class="summary-strip tabular">
        <span class="badge badge-neutral">Servers: {{ telemetry.servers.length }}</span>
      </div>
    </header>

    <div class="server-grid">
      <article v-for="server in telemetry.servers" :key="server.id" class="server-card card">
        <div class="server-head">
          <div>
            <h2>{{ server.name }}</h2>
            <code class="muted">{{ server.ip_address || 'Unknown IP' }}</code>
          </div>
          <span class="badge" :class="`badge-${server.status}`">{{ server.status }}</span>
        </div>

        <div class="charts">
          <MetricChart label="CPU Usage" :data="getCpuData(server.id)" color="#10b981" />
          <MetricChart label="RAM Usage" :data="getRamData(server.id)" color="#38bdf8" />
        </div>
      </article>

      <div v-if="telemetry.servers.length === 0" class="empty-state card">
        <p>No servers found. Add a server to start monitoring.</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}

.summary-strip {
  display: flex;
  gap: 8px;
}

.server-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 16px;
}

.server-card {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.server-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.server-head h2 {
  font-size: 1rem;
}

.muted {
  color: var(--ink-muted);
  font-size: 0.8125rem;
}

.charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.empty-state {
  grid-column: 1 / -1;
  padding: 40px 24px;
  text-align: center;
  color: var(--ink-muted);
}
</style>
