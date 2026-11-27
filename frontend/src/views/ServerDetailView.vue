<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  AlertTriangle,
  ArrowLeft,
  ChevronDown,
  Pencil,
  RefreshCw,
  Trash2,
  X,
} from 'lucide-vue-next'
import {
  AlertDialog,
  AlertDialogBackdrop,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
} from '@ui-sdk/vue/alert-dialog'
import { Button } from '@ui-sdk/vue/button'
import {
  Drawer,
  DrawerBackdrop,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerTitle,
} from '@ui-sdk/vue/drawer'
import { Field, FieldDescription, FieldLabel } from '@ui-sdk/vue/field'
import { Input } from '@ui-sdk/vue/input'
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
import { Switch, SwitchThumb } from '@ui-sdk/vue/switch'
import { Tabs, TabsList, TabsPanel, TabsTab } from '@ui-sdk/vue/tabs'
import { toast } from '@ui-sdk/vue/toast'
import {
  api,
  extractApiError,
  type MetricHistoryPoint,
  type MetricHistoryResponse,
  type ServerRecord,
} from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useTelemetryStore } from '../stores/telemetry'
import TimeSeriesChart from '../components/TimeSeriesChart.vue'
import { formatBytes, formatRelativeTime, formatUptime } from '../utils/format'

const VALID_RANGES = ['15m', '1h', '6h', '24h', '7d', '30d'] as const
type RangeKey = (typeof VALID_RANGES)[number]

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const telemetry = useTelemetryStore()
const queryClient = useQueryClient()

const serverId = computed(() => String(route.params.id || ''))
const initialRange = VALID_RANGES.includes(route.query.range as RangeKey)
  ? (route.query.range as RangeKey)
  : '1h'
const selectedRange = ref<string>(initialRange)

watch(selectedRange, (next) => {
  router.replace({ query: { ...route.query, range: next } })
})

const {
  data: server,
  isPending: serverPending,
  isError: serverIsError,
  error: serverError,
  refetch: refetchServer,
} = useQuery<ServerRecord>({
  queryKey: computed(() => ['server', serverId.value]),
  queryFn: async () => {
    const resp = await api.get<ServerRecord>(`/api/monitoring/servers/${serverId.value}/`)
    return resp.data
  },
  refetchInterval: 30000,
})

const {
  data: metricsHistory,
  isPending: metricsPending,
  isFetching: metricsFetching,
  refetch: refetchMetrics,
} = useQuery<MetricHistoryResponse>({
  queryKey: computed(() => ['server-metrics', serverId.value, selectedRange.value]),
  queryFn: async () => {
    const resp = await api.get<MetricHistoryResponse>(
      `/api/telemetry/servers/${serverId.value}/metrics/`,
      { params: { range: selectedRange.value } },
    )
    return resp.data
  },
  refetchInterval: 30000,
})

const mergedPoints = computed<MetricHistoryPoint[]>(() => {
  const base = metricsHistory.value?.points ? [...metricsHistory.value.points] : []
  if (selectedRange.value !== '15m' && selectedRange.value !== '1h') {
    return base
  }
  const liveSamples = telemetry.metrics[serverId.value] ?? []
  if (liveSamples.length === 0) {
    return base
  }
  const lastBaseTs = base.length > 0 ? Date.parse(base[base.length - 1].timestamp) : 0
  for (const sample of liveSamples) {
    const sampleTs = Date.parse(sample.timestamp)
    if (!Number.isNaN(sampleTs) && sampleTs > lastBaseTs) {
      base.push({
        timestamp: sample.timestamp,
        cpu: sample.cpu_usage,
        max_cpu: sample.cpu_usage,
        ram: sample.ram_usage,
        max_ram: sample.ram_usage,
        swap: null,
        disk: null,
        disk_read_bps: null,
        disk_write_bps: null,
        net_rx_bps: null,
        net_tx_bps: null,
        load_1m: null,
        uptime_seconds: null,
      })
    }
  }
  return base
})

const timestamps = computed(() => mergedPoints.value.map((p) => p.timestamp))

const cpuSeries = computed(() => [
  { name: 'Avg CPU', color: '#10b981', data: mergedPoints.value.map((p) => p.cpu ?? null), area: true },
  { name: 'Peak CPU', color: '#f59e0b', data: mergedPoints.value.map((p) => p.max_cpu ?? null), dashed: true },
])

const memSeries = computed(() => [
  { name: 'RAM', color: '#38bdf8', data: mergedPoints.value.map((p) => p.ram ?? null), area: true },
  { name: 'Swap', color: '#a78bfa', data: mergedPoints.value.map((p) => p.swap ?? null), dashed: true },
])

const diskUsageSeries = computed(() => [
  { name: 'Disk Used', color: '#f59e0b', data: mergedPoints.value.map((p) => p.disk ?? null), area: true },
])

const diskIoSeries = computed(() => [
  { name: 'Read', color: '#10b981', data: mergedPoints.value.map((p) => p.disk_read_bps ?? null) },
  { name: 'Write', color: '#ef4444', data: mergedPoints.value.map((p) => p.disk_write_bps ?? null) },
])

const netIoSeries = computed(() => [
  { name: 'RX', color: '#38bdf8', data: mergedPoints.value.map((p) => p.net_rx_bps ?? null), area: true },
  { name: 'TX', color: '#a78bfa', data: mergedPoints.value.map((p) => p.net_tx_bps ?? null) },
])

const loadSeries = computed(() => [
  { name: 'Load 1m', color: '#10b981', data: mergedPoints.value.map((p) => p.load_1m ?? null), area: true },
])

const latestUptime = computed<number | null>(() => {
  const pts = mergedPoints.value
  for (let i = pts.length - 1; i >= 0; i -= 1) {
    if (typeof pts[i].uptime_seconds === 'number') {
      return pts[i].uptime_seconds
    }
  }
  return null
})

const effectiveStatus = computed(() => {
  if (telemetry.liveServerIds[serverId.value]) {
    return 'online'
  }
  return server.value?.status || 'unknown'
})

const effectiveLastSeen = computed(
  () => telemetry.lastSeen[serverId.value] || server.value?.last_seen || null,
)

const serverTags = computed(() => (Array.isArray(server.value?.tags) ? server.value.tags.map(String) : []))

interface ProcessEntry {
  pid: number
  name: string
  cpu_percent: number
  mem_bytes: number
}

interface DockerEntry {
  id: string
  name: string
  image: string
  state: string
  status: string
  cpu_percent: number
  mem_bytes: number
  mem_limit_bytes: number
  mem_percent: number
}

interface MountEntry {
  mount: string
  used_percent: number
  total_bytes: number
  available_bytes: number
  inodes_used_percent?: number | null
}

interface TempEntry {
  label: string
  celsius: number
}

interface SystemdEntry {
  name: string
  active_state: string
  sub_state: string
}

const detailsTab = ref<string | null>('processes')

const latestDetails = computed<Record<string, unknown>>(() => {
  const raw = (server.value as (ServerRecord & { latest_details?: Record<string, unknown> }) | undefined)
    ?.latest_details
  return raw && typeof raw === 'object' ? raw : {}
})

const topProcesses = computed<ProcessEntry[]>(() =>
  Array.isArray(latestDetails.value.top_processes) ? (latestDetails.value.top_processes as ProcessEntry[]) : [],
)

const processCount = computed<number | null>(() =>
  typeof latestDetails.value.process_count === 'number' ? latestDetails.value.process_count : null,
)

const dockerContainers = computed<DockerEntry[]>(() =>
  Array.isArray(latestDetails.value.docker_containers)
    ? (latestDetails.value.docker_containers as DockerEntry[])
    : [],
)

const mountEntries = computed<MountEntry[]>(() =>
  Array.isArray(latestDetails.value.mounts) ? (latestDetails.value.mounts as MountEntry[]) : [],
)

const tempEntries = computed<TempEntry[]>(() =>
  Array.isArray(latestDetails.value.temperatures) ? (latestDetails.value.temperatures as TempEntry[]) : [],
)

const systemdUnits = computed<SystemdEntry[]>(() =>
  Array.isArray(latestDetails.value.systemd_units) ? (latestDetails.value.systemd_units as SystemdEntry[]) : [],
)

const hasRichDetails = computed(
  () =>
    topProcesses.value.length > 0 ||
    dockerContainers.value.length > 0 ||
    mountEntries.value.length > 0 ||
    tempEntries.value.length > 0 ||
    systemdUnits.value.length > 0,
)

const editOpen = ref(false)
const editName = ref('')
const editCadence = ref('30')
const editLogLevel = ref<string | null>('INFO')
const editTags = ref('')
const editActive = ref(true)
const savingEdit = ref(false)
const editError = ref('')

const deleteOpen = ref(false)
const deleting = ref(false)

function openEditDrawer() {
  if (!server.value) return
  editName.value = server.value.name
  editCadence.value = String(server.value.telemetry_cadence ?? 30)
  editLogLevel.value = server.value.log_level || 'INFO'
  editTags.value = serverTags.value.join(', ')
  editActive.value = server.value.is_active !== false
  editError.value = ''
  editOpen.value = true
}

async function handleSaveEdit() {
  editError.value = ''
  savingEdit.value = true
  try {
    const cadence = Math.max(5, Math.min(3600, Number.parseInt(editCadence.value, 10) || 30))
    const tags = editTags.value
      .split(',')
      .map((t) => t.trim().toLowerCase())
      .filter(Boolean)
    await api.patch(`/api/monitoring/servers/${serverId.value}/`, {
      name: editName.value.trim(),
      telemetry_cadence: cadence,
      log_level: editLogLevel.value || 'INFO',
      tags,
      is_active: editActive.value,
    })
    queryClient.invalidateQueries({ queryKey: ['server', serverId.value] })
    queryClient.invalidateQueries({ queryKey: ['servers'] })
    editOpen.value = false
    toast.success('Server configuration saved')
  } catch (err) {
    editError.value = extractApiError(err, 'Could not update server.')
  } finally {
    savingEdit.value = false
  }
}

async function handleDeleteConfirm() {
  deleting.value = true
  try {
    await api.delete(`/api/monitoring/servers/${serverId.value}/`)
    queryClient.invalidateQueries({ queryKey: ['servers'] })
    toast.success('Server removed from fleet')
    deleteOpen.value = false
    router.push('/')
  } catch (err) {
    toast.error(extractApiError(err, 'Could not delete server.'))
  } finally {
    deleting.value = false
  }
}

function handleRefreshAll() {
  refetchServer()
  refetchMetrics()
}
</script>

<template>
  <section class="detail-page">
    <nav class="breadcrumb" aria-label="Breadcrumb">
      <router-link to="/" class="back-link">
        <ArrowLeft :size="15" aria-hidden="true" />
        <span>Back to Fleet</span>
      </router-link>
    </nav>

    <div v-if="serverIsError" class="banner-error error-row" role="alert">
      <span class="error-copy">
        <AlertTriangle :size="16" aria-hidden="true" />
        {{ extractApiError(serverError, 'Could not load server details.') }}
      </span>
      <Button type="button" @click="refetchServer()">Retry</Button>
    </div>

    <template v-else>
      <header class="detail-header">
        <div class="header-main">
          <div class="title-row">
            <h1>{{ server?.name || (serverPending ? 'Loading server...' : 'Server') }}</h1>
            <span v-if="server" class="badge" :class="`badge-${effectiveStatus}`">
              {{ effectiveStatus }}
            </span>
            <span
              v-if="server?.alert_status && server.alert_status !== 'ok'"
              class="badge"
              :class="`badge-${server.alert_status}`"
            >
              {{ server.alert_status }}
            </span>
          </div>

          <div v-if="serverTags.length > 0" class="tag-row">
            <span v-for="tag in serverTags" :key="tag" class="tag-chip tag-overflow">#{{ tag }}</span>
          </div>
        </div>

        <div class="header-controls">
          <SegmentedControl v-model="selectedRange" aria-label="Time range">
            <SegmentedControlIndicator />
            <SegmentedControlItem v-for="key in VALID_RANGES" :key="key" :value="key">
              {{ key }}
            </SegmentedControlItem>
          </SegmentedControl>

          <Button type="button" data-variant="ghost" :pending="metricsFetching && !metricsPending" @click="handleRefreshAll">
            <RefreshCw :size="15" aria-hidden="true" />
            <span>Refresh</span>
          </Button>

          <Button v-if="auth.canWrite && server" type="button" @click="openEditDrawer">
            <Pencil :size="15" aria-hidden="true" />
            <span>Edit</span>
          </Button>

          <Button v-if="auth.canWrite && server" type="button" data-variant="danger" @click="deleteOpen = true">
            <Trash2 :size="15" aria-hidden="true" />
            <span>Delete</span>
          </Button>
        </div>
      </header>

      <section class="inventory-grid card" aria-label="Host inventory">
        <div class="inv-item">
          <span class="inv-label">Hostname</span>
          <code class="inv-val">{{ server?.hostname || '--' }}</code>
        </div>
        <div class="inv-item">
          <span class="inv-label">IP Address</span>
          <code class="inv-val">{{ server?.ip_address || '--' }}</code>
        </div>
        <div class="inv-item">
          <span class="inv-label">Operating System</span>
          <span class="inv-val">{{ server?.os_info || '--' }}</span>
        </div>
        <div class="inv-item">
          <span class="inv-label">Kernel</span>
          <code class="inv-val">{{ server?.kernel || '--' }}</code>
        </div>
        <div class="inv-item">
          <span class="inv-label">CPU</span>
          <span class="inv-val">
            {{ server?.cpu_model || '--' }}
            <template v-if="server?.cpu_cores"> ({{ server.cpu_cores }} cores)</template>
          </span>
        </div>
        <div class="inv-item">
          <span class="inv-label">Memory</span>
          <span class="inv-val tabular">{{ formatBytes(server?.total_ram_bytes) }}</span>
        </div>
        <div class="inv-item">
          <span class="inv-label">Uptime</span>
          <span class="inv-val tabular">{{ formatUptime(latestUptime) }}</span>
        </div>
        <div class="inv-item">
          <span class="inv-label">Agent / Cadence</span>
          <span class="inv-val tabular">
            {{ server?.agent_version || 'n/a' }} / {{ server?.telemetry_cadence ?? '--' }}s
          </span>
        </div>
        <div class="inv-item">
          <span class="inv-label">Last Heartbeat</span>
          <span class="inv-val tabular">{{ formatRelativeTime(effectiveLastSeen) }}</span>
        </div>
      </section>

      <div v-if="metricsPending" class="charts-grid" aria-busy="true">
        <div v-for="n in 4" :key="n" class="card skeleton-chart-card">
          <div class="skeleton skeleton-head" />
          <div class="skeleton skeleton-body" />
        </div>
      </div>

      <div v-else class="charts-grid">
        <TimeSeriesChart
          title="CPU Usage"
          :subtitle="`Bucket: ${metricsHistory?.bucket || 'raw'}`"
          :timestamps="timestamps"
          :series="cpuSeries"
          unit="percent"
          :y-max="100"
        />
        <TimeSeriesChart
          title="Memory & Swap"
          :subtitle="`Total RAM: ${formatBytes(server?.total_ram_bytes)}`"
          :timestamps="timestamps"
          :series="memSeries"
          unit="percent"
          :y-max="100"
        />
        <TimeSeriesChart
          title="Disk Utilization"
          :timestamps="timestamps"
          :series="diskUsageSeries"
          unit="percent"
          :y-max="100"
        />
        <TimeSeriesChart
          title="Disk I/O Throughput"
          :timestamps="timestamps"
          :series="diskIoSeries"
          unit="bytes_rate"
        />
        <TimeSeriesChart
          title="Network I/O"
          :timestamps="timestamps"
          :series="netIoSeries"
          unit="bytes_rate"
        />
        <TimeSeriesChart
          title="Load Average (1m)"
          :timestamps="timestamps"
          :series="loadSeries"
          unit="number"
        />
      </div>

      <section v-if="hasRichDetails" class="details-section card" aria-label="Host process and container details">
        <header class="details-head">
          <div>
            <h2>Host Diagnostics</h2>
            <p class="drawer-sub">
              <template v-if="processCount !== null">Processes: {{ processCount }}</template>
              <template v-if="typeof latestDetails.cpu_iowait_percent === 'number'">
                &middot; IOWait: {{ Number(latestDetails.cpu_iowait_percent).toFixed(1) }}%
              </template>
              <template v-if="typeof latestDetails.cpu_steal_percent === 'number'">
                &middot; Steal: {{ Number(latestDetails.cpu_steal_percent).toFixed(1) }}%
              </template>
              <template v-if="typeof latestDetails.disk_iops_read === 'number'">
                &middot; Disk IOPS: {{ Number(latestDetails.disk_iops_read).toFixed(0) }}R /
                {{ Number(latestDetails.disk_iops_write || 0).toFixed(0) }}W
              </template>
            </p>
          </div>
        </header>

        <Tabs v-model="detailsTab">
          <TabsList aria-label="Host diagnostic tabs">
            <TabsTab value="processes">Processes ({{ topProcesses.length }})</TabsTab>
            <TabsTab value="docker">Docker ({{ dockerContainers.length }})</TabsTab>
            <TabsTab value="disks">Disks &amp; Temps ({{ mountEntries.length }})</TabsTab>
            <TabsTab value="systemd">Systemd ({{ systemdUnits.length }})</TabsTab>
          </TabsList>

          <TabsPanel value="processes" class="diag-panel">
            <div v-if="topProcesses.length === 0" class="drawer-sub">No process data reported yet.</div>
            <div v-else class="table-wrap">
              <table class="data-table">
                <thead>
                  <tr>
                    <th>PID</th>
                    <th>Process</th>
                    <th class="num">CPU</th>
                    <th class="num">Memory</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="proc in topProcesses" :key="proc.pid">
                    <td class="mono tabular">{{ proc.pid }}</td>
                    <td><strong>{{ proc.name }}</strong></td>
                    <td class="num tabular">{{ proc.cpu_percent.toFixed(1) }}%</td>
                    <td class="num tabular">{{ formatBytes(proc.mem_bytes) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </TabsPanel>

          <TabsPanel value="docker" class="diag-panel">
            <div v-if="dockerContainers.length === 0" class="drawer-sub">No Docker containers detected on this host.</div>
            <div v-else class="table-wrap">
              <table class="data-table">
                <thead>
                  <tr>
                    <th>Container</th>
                    <th>Image</th>
                    <th>State</th>
                    <th class="num">CPU</th>
                    <th class="num">Memory</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="c in dockerContainers" :key="c.id">
                    <td>
                      <strong>{{ c.name }}</strong>
                      <div class="drawer-sub mono">{{ c.id }}</div>
                    </td>
                    <td class="mono">{{ c.image }}</td>
                    <td>
                      <span class="badge" :class="c.state === 'running' ? 'badge-online' : 'badge-neutral'">
                        {{ c.state }}
                      </span>
                    </td>
                    <td class="num tabular">{{ c.cpu_percent.toFixed(1) }}%</td>
                    <td class="num tabular">
                      {{ formatBytes(c.mem_bytes) }}
                      <span v-if="c.mem_limit_bytes > 0" class="drawer-sub">({{ c.mem_percent.toFixed(1) }}%)</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </TabsPanel>

          <TabsPanel value="disks" class="diag-panel">
            <div v-if="mountEntries.length > 0" class="table-wrap">
              <table class="data-table">
                <thead>
                  <tr>
                    <th>Mount</th>
                    <th class="num">Used %</th>
                    <th class="num">Inodes %</th>
                    <th class="num">Available / Total</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="m in mountEntries" :key="m.mount">
                    <td class="mono">{{ m.mount }}</td>
                    <td class="num tabular">{{ m.used_percent.toFixed(1) }}%</td>
                    <td class="num tabular">
                      {{ typeof m.inodes_used_percent === 'number' ? `${m.inodes_used_percent.toFixed(1)}%` : '--' }}
                    </td>
                    <td class="num tabular">
                      {{ formatBytes(m.available_bytes) }} / {{ formatBytes(m.total_bytes) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-if="tempEntries.length > 0" class="temp-strip">
              <span v-for="t in tempEntries" :key="t.label" class="badge badge-neutral tabular">
                {{ t.label }}: {{ t.celsius.toFixed(1) }}°C
              </span>
            </div>
          </TabsPanel>

          <TabsPanel value="systemd" class="diag-panel">
            <div v-if="systemdUnits.length === 0" class="drawer-sub">No systemd services reported for this host.</div>
            <div v-else class="table-wrap">
              <table class="data-table">
                <thead>
                  <tr>
                    <th>Unit</th>
                    <th>State</th>
                    <th>Sub-state</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="u in systemdUnits" :key="u.name">
                    <td class="mono">{{ u.name }}</td>
                    <td>
                      <span class="badge" :class="u.active_state === 'failed' ? 'badge-critical' : 'badge-online'">
                        {{ u.active_state }}
                      </span>
                    </td>
                    <td class="mono">{{ u.sub_state }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </TabsPanel>
        </Tabs>
      </section>
    </template>

    <Drawer v-model:open="editOpen" side="right">
      <DrawerBackdrop />
      <DrawerContent side="right">
        <div class="drawer-head">
          <div>
            <DrawerTitle>Edit Server</DrawerTitle>
            <DrawerDescription class="drawer-sub">
              Update display metadata and remote agent telemetry cadence.
            </DrawerDescription>
          </div>
          <DrawerClose class="icon-close" aria-label="Close drawer">
            <X :size="16" aria-hidden="true" />
          </DrawerClose>
        </div>

        <form class="drawer-form" @submit.prevent="handleSaveEdit">
          <div v-if="editError" class="banner-error" role="alert">{{ editError }}</div>

          <Field name="name">
            <FieldLabel>Server Name</FieldLabel>
            <Input v-model="editName" required />
          </Field>

          <Field name="cadence">
            <FieldLabel>Telemetry Cadence (seconds)</FieldLabel>
            <Input v-model="editCadence" type="number" min="5" max="3600" inputmode="numeric" required />
            <FieldDescription>How frequently the Rust agent collects samples (5 to 3600s).</FieldDescription>
          </Field>

          <Field name="log-level">
            <FieldLabel>Agent Log Level</FieldLabel>
            <Select v-model="editLogLevel">
              <SelectTrigger aria-label="Agent log level">
                <SelectValue />
                <ChevronDown :size="15" aria-hidden="true" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="DEBUG"><SelectItemText>DEBUG</SelectItemText></SelectItem>
                <SelectItem value="INFO"><SelectItemText>INFO</SelectItemText></SelectItem>
                <SelectItem value="WARNING"><SelectItemText>WARNING</SelectItemText></SelectItem>
                <SelectItem value="ERROR"><SelectItemText>ERROR</SelectItemText></SelectItem>
              </SelectContent>
            </Select>
          </Field>

          <Field name="tags">
            <FieldLabel>Tags (comma-separated)</FieldLabel>
            <Input v-model="editTags" placeholder="prod, web, us-east" />
            <FieldDescription>Lowercase letters, digits, dots, underscores, or hyphens.</FieldDescription>
          </Field>

          <label class="switch-row">
            <span>Monitoring active</span>
            <Switch :checked="editActive" @checked-change="(val: boolean) => (editActive = val)">
              <SwitchThumb />
            </Switch>
          </label>

          <div class="drawer-actions">
            <DrawerClose class="btn btn-ghost">Cancel</DrawerClose>
            <Button type="submit" data-variant="solid" :pending="savingEdit">Save Changes</Button>
          </div>
        </form>
      </DrawerContent>
    </Drawer>

    <AlertDialog v-model:open="deleteOpen">
      <AlertDialogBackdrop />
      <AlertDialogContent class="confirm-dialog">
        <AlertDialogTitle>Delete {{ server?.name }}?</AlertDialogTitle>
        <AlertDialogDescription class="drawer-sub">
          This permanently removes the server record and revokes its monitoring configuration. Active agents will no longer ingest telemetry for this host.
        </AlertDialogDescription>
        <div class="drawer-actions">
          <AlertDialogClose class="btn btn-ghost">Cancel</AlertDialogClose>
          <Button type="button" data-variant="danger" :pending="deleting" @click="handleDeleteConfirm">
            Delete Server
          </Button>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  </section>
</template>

<style scoped>
.detail-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--ink-muted);
  text-decoration: none;
}

.back-link:hover {
  color: var(--ink);
}

.detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.header-main {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.title-row h1 {
  font-size: 1.5rem;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.header-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.inventory-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: 14px;
  padding: 16px;
}

.inv-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.inv-label {
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-muted);
}

.inv-val {
  font-size: 0.86rem;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.charts-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.skeleton-chart-card {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.skeleton-head {
  width: 40%;
  height: 16px;
}

.skeleton-body {
  width: 100%;
  height: 220px;
}

.error-row {
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

.drawer-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 18px;
}

.drawer-sub {
  margin: 4px 0 0;
  font-size: 0.84rem;
  color: var(--ink-muted);
}

.icon-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: transparent;
  color: var(--ink-muted);
  cursor: pointer;
}

.drawer-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 0;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
}

.drawer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 12px;
}

.confirm-dialog {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.details-section {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.details-head h2 {
  font-size: 1.05rem;
}

.diag-panel {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.table-wrap {
  overflow-x: auto;
}

.temp-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

@media (max-width: 960px) {
  .charts-grid {
    grid-template-columns: 1fr;
  }
}
</style>
