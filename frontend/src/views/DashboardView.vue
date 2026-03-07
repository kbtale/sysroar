<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useTelemetryStore } from '../stores/telemetry'
import MetricChart from '../components/MetricChart.vue'

const router = useRouter()
const auth = useAuthStore()
const telemetry = useTelemetryStore()

onMounted(async () => {
  await telemetry.fetchServers()
})

function handleLogout() {
  auth.logout()
  router.push('/login')
}

function getCpuData(serverId: string) {
  return (telemetry.metrics[serverId] || []).map(m => m.cpu_usage)
}

function getRamData(serverId: string) {
  return (telemetry.metrics[serverId] || []).map(m => m.ram_usage)
}
</script>

<template>
  <div class="dashboard-layout">
    <nav class="sidebar">
      <div class="logo">
        <span class="roar">SYS</span>ROAR
      </div>
      
      <div class="nav-links">
        <a href="#" class="active">Dashboard</a>
        <a href="#">Servers</a>
        <a href="#">Alerts</a>
        <a href="#">Settings</a>
      </div>
      
      <div class="user-block">
        <button @click="handleLogout" class="logout-btn">Logout</button>
      </div>
    </nav>

    <main class="content">
      <header>
        <h1>Infrastructure Overview</h1>
        <div class="stats-summary">
          <div class="stat">
            <span class="stat-label">Total Servers</span>
            <span class="stat-value">{{ telemetry.servers.length }}</span>
          </div>
          <div class="stat">
            <span class="stat-label">Active Connections</span>
            <span class="stat-value">{{ Object.keys(telemetry.sockets).length }}</span>
          </div>
        </div>
      </header>

      <div class="server-grid">
        <div v-for="server in telemetry.servers" :key="server.id" class="server-card">
          <div class="server-info">
            <div class="status-indicator" :class="server.status"></div>
            <div class="text">
              <h3>{{ server.hostname }}</h3>
              <code>{{ server.ip_address }}</code>
            </div>
          </div>
          
          <div class="charts">
            <MetricChart 
              label="CPU Usage" 
              :data="getCpuData(server.id)" 
              color="#10b981" 
            />
            <MetricChart 
              label="RAM Usage" 
              :data="getRamData(server.id)" 
              color="#3b82f6" 
            />
          </div>
        </div>
        
        <div v-if="telemetry.servers.length === 0" class="empty-state">
          <p>No servers found. Deploy an agent to start monitoring.</p>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.dashboard-layout {
  display: flex;
  min-height: 100vh;
  background: #0f172a;
}

.sidebar {
  width: 260px;
  background: rgba(30, 41, 59, 0.5);
  border-right: 1px solid rgba(255, 255, 255, 0.05);
  display: flex;
  flex-direction: column;
  padding: 2rem;
}

.logo {
  font-size: 1.5rem;
  font-weight: 800;
  margin-bottom: 3rem;
}
.roar { color: #10b981; }

.nav-links {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  flex: 1;
}

.nav-links a {
  padding: 0.75rem 1rem;
  border-radius: 0.75rem;
  color: #94a3b8;
  text-decoration: none;
  font-weight: 500;
  transition: all 0.2s;
}

.nav-links a.active, .nav-links a:hover {
  background: rgba(255, 255, 255, 0.05);
  color: white;
}

.logout-btn {
  width: 100%;
  padding: 0.75rem;
  background: transparent;
  border: 1px solid rgba(239, 68, 68, 0.2);
  color: #ef4444;
  border-radius: 0.75rem;
  cursor: pointer;
  font-weight: 600;
}

.logout-btn:hover {
  background: rgba(239, 68, 68, 0.1);
}

.content {
  flex: 1;
  padding: 3rem;
  overflow-y: auto;
}

header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 3rem;
}

h1 { font-size: 2rem; margin: 0; font-weight: 700; }

.stats-summary { display: flex; gap: 3rem; }
.stat { display: flex; flex-direction: column; }
.stat-label { font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; font-weight: 700; }
.stat-value { font-size: 1.5rem; font-weight: 700; color: #10b981; }

.server-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(450px, 1fr));
  gap: 2rem;
}

.server-card {
  background: rgba(30, 41, 59, 0.4);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 1.5rem;
  padding: 1.5rem;
}

.server-info {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 2rem;
}

.status-indicator {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  box-shadow: 0 0 10px currentColor;
}
.status-indicator.active { color: #10b981; background: #10b981; }
.status-indicator.offline { color: #64748b; background: #64748b; }

.server-info h3 { margin: 0; font-size: 1.125rem; }
.server-info code { color: #94a3b8; font-size: 0.875rem; }

.charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.5rem;
}

.empty-state {
  grid-column: 1 / -1;
  padding: 5rem;
  text-align: center;
  background: rgba(30, 41, 59, 0.2);
  border: 2px dashed rgba(255, 255, 255, 0.05);
  border-radius: 2rem;
  color: #94a3b8;
}
</style>
