<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuery } from '@tanstack/vue-query'
import {
  AlertTriangle,
  ArrowUpRight,
  ChevronDown,
  LayoutGrid,
  RefreshCw,
  Search,
  Server as ServerIcon,
  Table as TableIcon,
  X,
} from 'lucide-vue-next'
import { Button } from '@ui-sdk/vue/button'
import { Input, InputClear, InputGroup } from '@ui-sdk/vue/input'
import {
  SegmentedControl,
  SegmentedControlIndicator,
  SegmentedControlItem,
} from '@ui-sdk/vue/segmented-control'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectItemText,
  SelectTrigger,
  SelectValue,
} from '@ui-sdk/vue/select'
import { api, extractApiError, unwrapResults, type ServerRecord } from '../api/client'
import { useTelemetryStore } from '../stores/telemetry'
import MetricChart from '../components/MetricChart.vue'
import { formatPercent, formatRelativeTime } from '../utils/format'

const route = useRoute()
const router = useRouter()
const telemetry = useTelemetryStore()

const searchQuery = ref(typeof route.query.q === 'string' ? route.query.q : '')
const statusFilter = ref<string | null>(
  typeof route.query.status === 'string' && route.query.status ? route.query.status : 'all',
)
const tagFilter = ref<string | null>(
  typeof route.query.tag === 'string' && route.query.tag ? route.query.tag : 'all',
)
const viewMode = ref<string>(route.query.view === 'table' ? 'table' : 'grid')

const {
  data: rawServers,
  isPending,
  isFetching,
  isError,
  error,
  refetch,
} = useQuery<ServerRecord[]>({
  queryKey: ['servers'],
  queryFn: async () => {
    const response = await api.get('/api/monitoring/servers/')
    return unwrapResults<ServerRecord>(response.data)
  },
  refetchInterval: 30000,
})

watch(
  rawServers,
  (list) => {
    if (list && list.length > 0) {
      telemetry.seedSparklines(list)
    }
  },
  { immediate: true },
)

onMounted(() => {
  telemetry.connect()
})

function syncUrl() {
  const query: Record<string, string> = {}
  const trimmed = searchQuery.value.trim()
  if (trimmed) {
    query.q = trimmed
  }
  if (statusFilter.value && statusFilter.value !== 'all') {
    query.status = statusFilter.value
  }
  if (tagFilter.value && tagFilter.value !== 'all') {
    query.tag = tagFilter.value
  }
  if (viewMode.value === 'table') {
    query.view = 'table'
  }
  router.replace({ query })
}

watch([searchQuery, statusFilter, tagFilter, viewMode], () => {
  syncUrl()
})

interface EnrichedServer {
  record: ServerRecord
  effectiveStatus: string
  effectiveLastSeen: string | null
  cpuSeries: number[]
  ramSeries: number[]
  latestCpu: number | null
  latestRam: number | null
  tags: string[]
}

const enrichedServers = computed<EnrichedServer[]>(() => {
  const list = rawServers.value ?? []
  return list.map((record) => {
    const liveSeries = telemetry.metrics[record.id] ?? []
    const cpuSeries = liveSeries.map((pt) => pt.cpu_usage)
    const ramSeries = liveSeries.map((pt) => pt.ram_usage)
    const liveSeen = telemetry.lastSeen[record.id]
    const effectiveLastSeen = liveSeen || record.last_seen || null
    const effectiveStatus = telemetry.liveServerIds[record.id] ? 'online' : record.status || 'unknown'
    const latestPoint = liveSeries.length > 0 ? liveSeries[liveSeries.length - 1] : null
    const tags = Array.isArray(record.tags) ? record.tags.map(String) : []

    return {
      record,
      effectiveStatus,
      effectiveLastSeen,
      cpuSeries,
      ramSeries,
      latestCpu: latestPoint ? latestPoint.cpu_usage : null,
      latestRam: latestPoint ? latestPoint.ram_usage : null,
      tags,
    }
  })
})

const availableTags = computed<string[]>(() => {
  const set = new Set<string>()
  for (const item of enrichedServers.value) {
    for (const tag of item.tags) {
      set.add(tag)
    }
  }
  return Array.from(set).sort()
})

const summaryCounts = computed(() => {
  const counts = { total: 0, online: 0, warning: 0, critical: 0, offline: 0 }
  for (const item of enrichedServers.value) {
    counts.total += 1
    if (item.effectiveStatus === 'online') {
      counts.online += 1
    } else if (item.effectiveStatus === 'offline') {
      counts.offline += 1
    }
    if (item.record.alert_status === 'warning') {
      counts.warning += 1
    } else if (item.record.alert_status === 'critical') {
      counts.critical += 1
    }
  }
  return counts
})

const filteredServers = computed<EnrichedServer[]>(() => {
  const q = searchQuery.value.trim().toLowerCase()
  const status = statusFilter.value || 'all'
  const tag = tagFilter.value || 'all'

  return enrichedServers.value.filter((item) => {
    if (status === 'online' && item.effectiveStatus !== 'online') return false
    if (status === 'offline' && item.effectiveStatus !== 'offline') return false
    if (status === 'unknown' && item.effectiveStatus !== 'unknown') return false
    if (status === 'warning' && item.record.alert_status !== 'warning') return false
    if (status === 'critical' && item.record.alert_status !== 'critical') return false

    if (tag !== 'all' && !item.tags.includes(tag)) return false

    if (q) {
      const hay = [
        item.record.name,
        item.record.hostname || '',
        item.record.ip_address || '',
        item.record.os_info || '',
        ...item.tags,
      ]
        .join(' ')
        .toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  })
})

const hasActiveFilters = computed(
  () =>
    searchQuery.value.trim().length > 0 ||
    (statusFilter.value !== null && statusFilter.value !== 'all') ||
    (tagFilter.value !== null && tagFilter.value !== 'all'),
)

const connectionLabel = computed(() => {
  if (telemetry.connectionState === 'connected') return 'Live stream'
  if (telemetry.connectionState === 'reconnecting') return 'Reconnecting...'
  if (telemetry.connectionState === 'connecting') return 'Connecting...'
  return 'Offline'
})

const errorMessage = computed(() => extractApiError(error.value, 'Could not load fleet inventory.'))

function toggleStatusCard(target: string) {
  statusFilter.value = statusFilter.value === target ? 'all' : target
}

function selectTag(tag: string) {
  tagFilter.value = tagFilter.value === tag ? 'all' : tag
}

function clearFilters() {
  searchQuery.value = ''
  statusFilter.value = 'all'
  tagFilter.value = 'all'
}
</script>

<template>
  <section class="fleet-page">
    <header class="page-header">
      <div class="title-block">
        <h1>Fleet Overview</h1>
        <span class="stream-pill" :data-state="telemetry.connectionState" aria-live="polite">
          <span class="stream-dot" aria-hidden="true" />
          {{ connectionLabel }}
        </span>
      </div>

      <div class="header-actions">
        <Button type="button" variant="ghost" :pending="isFetching && !isPending" @click="refetch()">
          <RefreshCw :size="15" aria-hidden="true" />
          <span>Refresh</span>
        </Button>
      </div>
    </header>

    <div class="summary-strip" role="region" aria-label="Fleet health summary">
      <button
        type="button"
        class="summary-card card"
        :class="{ active: statusFilter === 'all' }"
        :aria-pressed="statusFilter === 'all'"
        @click="statusFilter = 'all'"
      >
        <span class="summary-label">Total</span>
        <strong class="summary-value tabular">{{ summaryCounts.total }}</strong>
      </button>

      <button
        type="button"
        class="summary-card card"
        :class="{ active: statusFilter === 'online' }"
        :aria-pressed="statusFilter === 'online'"
        @click="toggleStatusCard('online')"
      >
        <span class="summary-label">Online</span>
        <strong class="summary-value value-online tabular">{{ summaryCounts.online }}</strong>
      </button>

      <button
        type="button"
        class="summary-card card"
        :class="{ active: statusFilter === 'warning' }"
        :aria-pressed="statusFilter === 'warning'"
        @click="toggleStatusCard('warning')"
      >
        <span class="summary-label">Warning</span>
        <strong class="summary-value value-warning tabular">{{ summaryCounts.warning }}</strong>
      </button>

      <button
        type="button"
        class="summary-card card"
        :class="{ active: statusFilter === 'critical' }"
        :aria-pressed="statusFilter === 'critical'"
        @click="toggleStatusCard('critical')"
      >
        <span class="summary-label">Critical</span>
        <strong class="summary-value value-critical tabular">{{ summaryCounts.critical }}</strong>
      </button>

      <button
        type="button"
        class="summary-card card"
        :class="{ active: statusFilter === 'offline' }"
        :aria-pressed="statusFilter === 'offline'"
        @click="toggleStatusCard('offline')"
      >
        <span class="summary-label">Offline</span>
        <strong class="summary-value value-offline tabular">{{ summaryCounts.offline }}</strong>
      </button>
    </div>

    <div class="toolbar">
      <div class="search-wrap">
        <InputGroup>
          <Search class="input-leading-icon" :size="15" aria-hidden="true" />
          <Input
            v-model="searchQuery"
            type="search"
            class="input-with-leading"
            aria-label="Search servers"
            placeholder="Filter by name, IP, OS, or tag..."
          />
          <InputClear aria-label="Clear search">
            <X :size="14" aria-hidden="true" />
          </InputClear>
        </InputGroup>
      </div>

      <div class="toolbar-controls">
        <Select v-model="statusFilter">
          <SelectTrigger aria-label="Filter by status">
            <SelectValue placeholder="All statuses" />
            <ChevronDown :size="15" aria-hidden="true" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">
              <SelectItemText>All statuses</SelectItemText>
            </SelectItem>
            <SelectItem value="online">
              <SelectItemText>Online</SelectItemText>
            </SelectItem>
            <SelectItem value="offline">
              <SelectItemText>Offline</SelectItemText>
            </SelectItem>
            <SelectItem value="warning">
              <SelectItemText>Warning alerts</SelectItemText>
            </SelectItem>
            <SelectItem value="critical">
              <SelectItemText>Critical alerts</SelectItemText>
            </SelectItem>
            <SelectItem value="unknown">
              <SelectItemText>Unknown</SelectItemText>
            </SelectItem>
          </SelectContent>
        </Select>

        <Select v-model="tagFilter">
          <SelectTrigger aria-label="Filter by tag">
            <SelectValue placeholder="All tags" />
            <ChevronDown :size="15" aria-hidden="true" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">
              <SelectItemText>All tags</SelectItemText>
            </SelectItem>
            <SelectItem v-for="tag in availableTags" :key="tag" :value="tag">
              <SelectItemText>#{{ tag }}</SelectItemText>
            </SelectItem>
          </SelectContent>
        </Select>

        <SegmentedControl v-model="viewMode" aria-label="Display layout">
          <SegmentedControlIndicator />
          <SegmentedControlItem value="grid">
            <LayoutGrid :size="14" aria-hidden="true" />
            <span>Grid</span>
          </SegmentedControlItem>
          <SegmentedControlItem value="table">
            <TableIcon :size="14" aria-hidden="true" />
            <span>Table</span>
          </SegmentedControlItem>
        </SegmentedControl>

        <Button v-if="hasActiveFilters" type="button" variant="ghost" @click="clearFilters">
          Reset
        </Button>
      </div>
    </div>

    <div v-if="isError" class="error-panel banner-error" role="alert">
      <div class="error-copy">
        <AlertTriangle :size="16" aria-hidden="true" />
        <span>{{ errorMessage }}</span>
      </div>
      <Button type="button" @click="refetch()">Retry</Button>
    </div>

    <div v-else-if="isPending" class="server-grid" aria-busy="true" aria-label="Loading fleet">
      <div v-for="n in 3" :key="n" class="server-card card skeleton-card">
        <div class="skeleton skeleton-title" />
        <div class="skeleton skeleton-sub" />
        <div class="skeleton skeleton-chart" />
      </div>
    </div>

    <div v-else-if="enrichedServers.length === 0" class="empty-state card">
      <ServerIcon :size="28" class="empty-icon" aria-hidden="true" />
      <h2>No servers monitored yet</h2>
      <p>Enroll your first Linux or Windows host with the SysRoar Rust agent to stream live telemetry.</p>
    </div>

    <div v-else-if="filteredServers.length === 0" class="empty-state card">
      <h2>No matching servers</h2>
      <p>No hosts match the active search or filter criteria.</p>
      <Button type="button" @click="clearFilters">Reset filters</Button>
    </div>

    <div v-else-if="viewMode === 'grid'" class="server-grid">
      <article v-for="item in filteredServers" :key="item.record.id" class="server-card card">
        <div class="server-head">
          <div class="server-identity">
            <router-link :to="`/servers/${item.record.id}`" class="server-title">
              <span>{{ item.record.name }}</span>
              <ArrowUpRight :size="14" class="title-arrow" aria-hidden="true" />
            </router-link>
            <code class="server-ip">{{ item.record.ip_address || item.record.hostname || 'Pending IP' }}</code>
          </div>

          <div class="badge-group">
            <span class="badge" :class="`badge-${item.effectiveStatus}`">
              {{ item.effectiveStatus }}
            </span>
            <span
              v-if="item.record.alert_status && item.record.alert_status !== 'ok'"
              class="badge"
              :class="`badge-${item.record.alert_status}`"
            >
              {{ item.record.alert_status }}
            </span>
          </div>
        </div>

        <div v-if="item.tags.length > 0" class="tag-row">
          <button
            v-for="tag in item.tags.slice(0, 4)"
            :key="tag"
            type="button"
            class="tag-chip"
            :class="{ active: tagFilter === tag }"
            @click="selectTag(tag)"
          >
            #{{ tag }}
          </button>
          <span v-if="item.tags.length > 4" class="tag-chip tag-overflow">
            +{{ item.tags.length - 4 }}
          </span>
        </div>

        <div class="metrics-row">
          <div class="metric-box">
            <div class="metric-head">
              <span class="metric-label">CPU</span>
              <strong class="metric-val tabular">{{ formatPercent(item.latestCpu) }}</strong>
            </div>
            <MetricChart label="CPU" :data="item.cpuSeries" color="#10b981" height="48px" />
          </div>

          <div class="metric-box">
            <div class="metric-head">
              <span class="metric-label">RAM</span>
              <strong class="metric-val tabular">{{ formatPercent(item.latestRam) }}</strong>
            </div>
            <MetricChart label="RAM" :data="item.ramSeries" color="#38bdf8" height="48px" />
          </div>
        </div>

        <footer class="card-footer">
          <span class="os-label" :title="item.record.os_info || 'OS unknown'">
            {{ item.record.os_info || 'OS unknown' }}
          </span>
          <span class="last-seen tabular">{{ formatRelativeTime(item.effectiveLastSeen) }}</span>
        </footer>
      </article>
    </div>

    <div v-else class="table-wrap card">
      <table class="data-table">
        <thead>
          <tr>
            <th>Server</th>
            <th>Status</th>
            <th>Alerts</th>
            <th class="num">CPU</th>
            <th class="num">RAM</th>
            <th>OS</th>
            <th class="num">Last Seen</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in filteredServers" :key="item.record.id">
            <td>
              <div class="table-server-cell">
                <router-link :to="`/servers/${item.record.id}`" class="server-title">
                  {{ item.record.name }}
                </router-link>
                <code class="server-ip">{{ item.record.ip_address || item.record.hostname || '--' }}</code>
              </div>
              <div v-if="item.tags.length > 0" class="tag-row compact">
                <button
                  v-for="tag in item.tags.slice(0, 3)"
                  :key="tag"
                  type="button"
                  class="tag-chip"
                  @click="selectTag(tag)"
                >
                  #{{ tag }}
                </button>
              </div>
            </td>
            <td>
              <span class="badge" :class="`badge-${item.effectiveStatus}`">
                {{ item.effectiveStatus }}
              </span>
            </td>
            <td>
              <span class="badge" :class="`badge-${item.record.alert_status || 'ok'}`">
                {{ item.record.alert_status || 'ok' }}
              </span>
            </td>
            <td class="num tabular">{{ formatPercent(item.latestCpu) }}</td>
            <td class="num tabular">{{ formatPercent(item.latestRam) }}</td>
            <td class="os-cell">{{ item.record.os_info || '--' }}</td>
            <td class="num tabular">{{ formatRelativeTime(item.effectiveLastSeen) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.fleet-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.title-block {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.title-block h1 {
  font-size: 1.5rem;
}

.stream-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface);
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--ink-muted);
}

.stream-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ink-muted);
}

.stream-pill[data-state='connected'] {
  color: var(--accent);
  border-color: var(--accent-soft);
}

.stream-pill[data-state='connected'] .stream-dot {
  background: var(--accent);
}

.stream-pill[data-state='reconnecting'],
.stream-pill[data-state='connecting'] {
  color: var(--warning);
}

.stream-pill[data-state='reconnecting'] .stream-dot,
.stream-pill[data-state='connecting'] .stream-dot {
  background: var(--warning);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.summary-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}

.summary-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 14px 16px;
  text-align: left;
  cursor: pointer;
  color: var(--ink);
  font: inherit;
  transition: border-color 140ms var(--ease-out), background-color 140ms var(--ease-out),
    transform 120ms var(--ease-out);
}

.summary-card:hover {
  border-color: var(--border-strong);
  background: var(--surface-raised);
}

.summary-card:active {
  transform: scale(0.98);
}

.summary-card.active {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.summary-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--ink-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.summary-value {
  font-size: 1.5rem;
  font-weight: 700;
  line-height: 1.15;
}

.value-online {
  color: var(--accent);
}

.value-warning {
  color: var(--warning);
}

.value-critical,
.value-offline {
  color: var(--danger);
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.search-wrap {
  flex: 1;
  min-width: 240px;
  max-width: 420px;
}

.input-leading-icon {
  position: absolute;
  left: 12px;
  color: var(--ink-muted);
  pointer-events: none;
}

.input-with-leading {
  padding-left: 34px;
  padding-right: 36px;
}

.toolbar-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.error-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.error-copy {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.server-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}

.server-card {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  transition: border-color 140ms var(--ease-out);
}

.server-card:hover {
  border-color: var(--border-strong);
}

.server-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.server-identity {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.server-title {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--ink);
  text-decoration: none;
}

.server-title:hover {
  color: var(--accent);
}

.title-arrow {
  color: var(--ink-muted);
  flex-shrink: 0;
}

.server-ip {
  font-size: 0.78rem;
  color: var(--ink-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.badge-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag-row.compact {
  margin-top: 4px;
}

.metrics-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.metric-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  background: var(--surface-raised);
  border: 1px solid var(--border);
  min-width: 0;
}

.metric-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
}

.metric-label {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--ink-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.metric-val {
  font-size: 0.875rem;
  font-weight: 700;
}

.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
  font-size: 0.78rem;
  color: var(--ink-muted);
}

.os-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.last-seen {
  flex-shrink: 0;
}

.table-wrap {
  overflow-x: auto;
}

.table-server-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.os-cell {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ink-muted);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 48px 24px;
  text-align: center;
  color: var(--ink-muted);
}

.empty-state h2 {
  font-size: 1.05rem;
  color: var(--ink);
}

.empty-state p {
  margin: 0;
  max-width: 460px;
  font-size: 0.875rem;
}

.empty-icon {
  color: var(--ink-muted);
}

.skeleton-card {
  gap: 12px;
}

.skeleton-title {
  width: 55%;
  height: 18px;
}

.skeleton-sub {
  width: 35%;
  height: 12px;
}

.skeleton-chart {
  width: 100%;
  height: 76px;
}

@media (max-width: 900px) {
  .summary-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 480px) {
  .server-grid {
    grid-template-columns: 1fr;
  }
}
</style>
