<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'
import { AlertTriangle, CheckCircle2, Clock, RefreshCw, XCircle } from 'lucide-vue-next'
import { formatDateTime } from '../utils/format'

interface PublicComponent {
  id: string
  name: string
  kind: 'server' | 'uptime'
  status: 'operational' | 'degraded' | 'outage' | 'unknown'
  uptime_24h: number | null
  recent_statuses: string[]
}

interface PublicIncident {
  id: string
  title: string
  severity: 'warning' | 'critical'
  status: 'open' | 'acknowledged' | 'resolved'
  opened_at: string
  resolved_at: string | null
}

interface PublicStatusPayload {
  slug: string
  title: string
  description: string
  accent_color: string
  overall_status: 'operational' | 'degraded' | 'partial_outage' | 'major_outage'
  updated_at: string
  components: PublicComponent[]
  incidents: PublicIncident[]
}

const route = useRoute()
const loading = ref(true)
const notFound = ref(false)
const errorMessage = ref('')
const statusData = ref<PublicStatusPayload | null>(null)

const overallLabel = computed(() => {
  switch (statusData.value?.overall_status) {
    case 'operational':
      return 'All Systems Operational'
    case 'degraded':
      return 'Degraded Performance'
    case 'partial_outage':
      return 'Partial System Outage'
    case 'major_outage':
      return 'Major System Outage'
    default:
      return 'Status Unavailable'
  }
})

const overallClass = computed(() => {
  switch (statusData.value?.overall_status) {
    case 'operational':
      return 'banner-ok'
    case 'degraded':
      return 'banner-warn'
    default:
      return 'banner-down'
  }
})

function componentStatusLabel(st: PublicComponent['status']): string {
  if (st === 'operational') return 'Operational'
  if (st === 'degraded') return 'Degraded'
  if (st === 'outage') return 'Outage'
  return 'Unknown'
}

async function fetchStatus() {
  const slug = String(route.params.slug || '').trim()
  if (!slug) {
    notFound.value = true
    loading.value = false
    return
  }
  loading.value = true
  notFound.value = false
  errorMessage.value = ''
  try {
    const resp = await axios.get<PublicStatusPayload>(`/api/public/status/${encodeURIComponent(slug)}/`)
    statusData.value = resp.data
  } catch (err: unknown) {
    const respStatus = (err as { response?: { status?: number } })?.response?.status
    if (respStatus === 404) {
      notFound.value = true
    } else {
      errorMessage.value = 'Unable to load status page right now.'
    }
    statusData.value = null
  } finally {
    loading.value = false
  }
}

onMounted(fetchStatus)
watch(() => route.params.slug, fetchStatus)
</script>

<template>
  <main class="status-shell">
    <div v-if="statusData" class="accent-strip" :style="{ backgroundColor: statusData.accent_color }" />

    <div class="status-container">
      <div v-if="loading" class="card empty-state">Loading status...</div>

      <div v-else-if="notFound" class="card empty-state">
        <h1>Status page not found</h1>
        <p class="muted">This status page does not exist or is currently private.</p>
      </div>

      <div v-else-if="errorMessage" class="card empty-state">
        <h1>Temporary error</h1>
        <p class="muted">{{ errorMessage }}</p>
      </div>

      <template v-else-if="statusData">
        <header class="status-header">
          <div>
            <h1>{{ statusData.title }}</h1>
            <p v-if="statusData.description" class="muted">{{ statusData.description }}</p>
          </div>
          <button type="button" class="refresh-btn" @click="fetchStatus()">
            <RefreshCw :size="14" aria-hidden="true" />
            <span>Refresh</span>
          </button>
        </header>

        <section class="overall-banner" :class="overallClass" role="status">
          <CheckCircle2 v-if="statusData.overall_status === 'operational'" :size="22" aria-hidden="true" />
          <AlertTriangle v-else-if="statusData.overall_status === 'degraded'" :size="22" aria-hidden="true" />
          <XCircle v-else :size="22" aria-hidden="true" />
          <div>
            <strong>{{ overallLabel }}</strong>
            <div class="banner-sub">Last updated {{ formatDateTime(statusData.updated_at) }}</div>
          </div>
        </section>

        <section class="card components-card">
          <h2>Components</h2>
          <p v-if="statusData.components.length === 0" class="muted">No components published yet.</p>
          <ul v-else class="component-list">
            <li v-for="comp in statusData.components" :key="comp.id" class="component-row">
              <div class="component-head">
                <div class="component-name">
                  <strong>{{ comp.name }}</strong>
                  <span class="kind-pill">{{ comp.kind === 'uptime' ? 'Endpoint' : 'Service' }}</span>
                </div>
                <div class="component-right">
                  <span v-if="comp.uptime_24h !== null" class="tabular muted">
                    {{ comp.uptime_24h.toFixed(2) }}% (24h)
                  </span>
                  <span
                    class="status-pill"
                    :class="
                      comp.status === 'operational'
                        ? 'pill-ok'
                        : comp.status === 'degraded'
                          ? 'pill-warn'
                          : comp.status === 'outage'
                            ? 'pill-down'
                            : 'pill-muted'
                    "
                  >
                    {{ componentStatusLabel(comp.status) }}
                  </span>
                </div>
              </div>
              <div v-if="comp.recent_statuses.length > 0" class="bar-strip" aria-label="Recent check history">
                <span
                  v-for="(st, idx) in comp.recent_statuses"
                  :key="idx"
                  class="bar-seg"
                  :class="st === 'up' ? 'seg-ok' : st === 'degraded' ? 'seg-warn' : 'seg-down'"
                  :title="st"
                />
              </div>
            </li>
          </ul>
        </section>

        <section class="card incidents-card">
          <h2>Recent Incidents (7 days)</h2>
          <p v-if="statusData.incidents.length === 0" class="muted">No incidents reported in the last 7 days.</p>
          <ul v-else class="incident-list">
            <li v-for="inc in statusData.incidents" :key="inc.id" class="incident-item">
              <div class="incident-head">
                <strong>{{ inc.title }}</strong>
                <span class="status-pill" :class="inc.status === 'resolved' ? 'pill-ok' : 'pill-warn'">
                  {{ inc.status }}
                </span>
              </div>
              <div class="incident-meta muted tabular">
                <Clock :size="12" aria-hidden="true" />
                <span>Opened {{ formatDateTime(inc.opened_at) }}</span>
                <span v-if="inc.resolved_at"> - Resolved {{ formatDateTime(inc.resolved_at) }}</span>
              </div>
            </li>
          </ul>
        </section>

        <footer class="status-footer muted">Powered by SysRoar</footer>
      </template>
    </div>
  </main>
</template>

<style scoped>
.status-shell {
  min-height: 100vh;
  background: var(--bg);
  color: var(--ink);
}

.accent-strip {
  height: 4px;
  width: 100%;
}

.status-container {
  max-width: 820px;
  margin: 0 auto;
  padding: 36px 20px 56px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.status-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.status-header h1 {
  margin: 0 0 6px;
  font-size: 1.65rem;
  letter-spacing: -0.02em;
}

.refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--ink);
  font-size: 0.84rem;
  cursor: pointer;
}

.overall-banner {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 20px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
}

.overall-banner strong {
  font-size: 1.05rem;
}

.banner-sub {
  font-size: 0.82rem;
  opacity: 0.85;
  margin-top: 2px;
}

.banner-ok {
  background: var(--ok-soft);
  color: var(--ok);
  border-color: var(--ok);
}

.banner-warn {
  background: var(--warning-soft);
  color: var(--warning);
  border-color: var(--warning);
}

.banner-down {
  background: var(--danger-soft);
  color: var(--danger);
  border-color: var(--danger);
}

.components-card,
.incidents-card {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.components-card h2,
.incidents-card h2 {
  margin: 0;
  font-size: 1.02rem;
}

.component-list,
.incident-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.component-row,
.incident-item {
  padding-top: 12px;
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.component-row:first-child,
.incident-item:first-child {
  padding-top: 0;
  border-top: none;
}

.component-head,
.incident-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.component-name,
.component-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.kind-pill {
  font-size: 0.72rem;
  padding: 2px 7px;
  border-radius: 999px;
  background: var(--bg-subtle);
  color: var(--ink-muted);
  border: 1px solid var(--border);
}

.status-pill {
  font-size: 0.76rem;
  font-weight: 600;
  padding: 3px 9px;
  border-radius: 999px;
  text-transform: capitalize;
}

.pill-ok {
  background: var(--ok-soft);
  color: var(--ok);
}

.pill-warn {
  background: var(--warning-soft);
  color: var(--warning);
}

.pill-down {
  background: var(--danger-soft);
  color: var(--danger);
}

.pill-muted {
  background: var(--bg-subtle);
  color: var(--ink-muted);
}

.bar-strip {
  display: flex;
  gap: 3px;
  height: 18px;
  align-items: stretch;
}

.bar-seg {
  flex: 1;
  min-width: 4px;
  border-radius: 2px;
}

.seg-ok {
  background: var(--ok);
}

.seg-warn {
  background: var(--warning);
}

.seg-down {
  background: var(--danger);
}

.incident-meta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
}

.empty-state {
  padding: 40px 24px;
  text-align: center;
}

.status-footer {
  text-align: center;
  font-size: 0.8rem;
  padding-top: 8px;
}

.muted {
  color: var(--ink-muted);
  margin: 0;
}
</style>
