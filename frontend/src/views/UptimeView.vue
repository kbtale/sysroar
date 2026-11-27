<script setup lang="ts">
import { computed, ref } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  ChevronDown,
  Globe,
  Play,
  Plus,
  RefreshCw,
  ShieldCheck,
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
  Dialog,
  DialogBackdrop,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@ui-sdk/vue/dialog'
import { Field, FieldDescription, FieldLabel } from '@ui-sdk/vue/field'
import { Input } from '@ui-sdk/vue/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectItemText,
  SelectTrigger,
  SelectValue,
} from '@ui-sdk/vue/select'
import { Switch, SwitchThumb } from '@ui-sdk/vue/switch'
import { toast } from '@ui-sdk/vue/toast'
import { api, extractApiError, unwrapResults, type NotificationChannelRecord } from '../api/client'
import { useAuthStore } from '../stores/auth'
import TimeSeriesChart from '../components/TimeSeriesChart.vue'
import { formatRelativeTime } from '../utils/format'

export interface UptimeCheckItem {
  id: string
  name: string
  check_type: 'http' | 'tcp' | 'ping' | 'dns' | 'ssl'
  target: string
  port: number | null
  expected_status: number
  expected_keyword: string
  ssl_expiry_warning_days: number
  interval_seconds: number
  timeout_seconds: number
  allow_private_targets: boolean
  channel: string | null
  tags: string[]
  is_active: boolean
  last_status: 'up' | 'degraded' | 'down' | 'unknown'
  last_latency_ms: number | null
  last_ssl_expiry_days: number | null
  last_error: string
  last_checked_at: string | null
  consecutive_failures: number
  uptime_24h_percent: number | null
  recent_statuses: string[]
  created_at: string
}

interface UptimeResultItem {
  id: string
  status: string
  latency_ms: number | null
  status_code: number | null
  ssl_expiry_days: number | null
  error_message: string
  checked_at: string
}

const auth = useAuthStore()
const queryClient = useQueryClient()

const {
  data: checks,
  isPending,
  isFetching,
  refetch,
} = useQuery<UptimeCheckItem[]>({
  queryKey: ['uptime-checks'],
  queryFn: async () => unwrapResults<UptimeCheckItem>((await api.get('/api/monitoring/uptime-checks/')).data),
  refetchInterval: 30000,
})

const { data: channels } = useQuery<NotificationChannelRecord[]>({
  queryKey: ['notification-channels'],
  queryFn: async () =>
    unwrapResults<NotificationChannelRecord>((await api.get('/api/monitoring/channels/')).data),
})

const selectedCheckId = ref<string | null>(null)
const { data: selectedResults } = useQuery<UptimeResultItem[]>({
  queryKey: computed(() => ['uptime-results', selectedCheckId.value]),
  enabled: computed(() => Boolean(selectedCheckId.value)),
  queryFn: async () => {
    const resp = await api.get<UptimeResultItem[]>(
      `/api/monitoring/uptime-checks/${selectedCheckId.value}/results/`,
    )
    return resp.data
  },
})

const selectedCheck = computed(() => (checks.value ?? []).find((c) => c.id === selectedCheckId.value) ?? null)

const latencyTimestamps = computed(() => (selectedResults.value ?? []).map((r) => r.checked_at))
const latencySeries = computed(() => [
  {
    name: 'Latency (ms)',
    color: '#38bdf8',
    data: (selectedResults.value ?? []).map((r) => r.latency_ms),
    area: true,
  },
])

const summary = computed(() => {
  const counts = { total: 0, up: 0, degraded: 0, down: 0 }
  for (const c of checks.value ?? []) {
    counts.total += 1
    if (c.last_status === 'up') counts.up += 1
    else if (c.last_status === 'degraded') counts.degraded += 1
    else if (c.last_status === 'down') counts.down += 1
  }
  return counts
})

const dialogOpen = ref(false)
const formName = ref('')
const formType = ref<string | null>('http')
const formTarget = ref('')
const formPort = ref('')
const formExpectedStatus = ref('200')
const formKeyword = ref('')
const formSslDays = ref('14')
const formInterval = ref('60')
const formTimeout = ref('10')
const formAllowPrivate = ref(false)
const formChannel = ref<string | null>('none')
const saving = ref(false)
const formError = ref('')

const runningId = ref<string | null>(null)
const deleteTarget = ref<UptimeCheckItem | null>(null)
const deleteOpen = ref(false)
const deleting = ref(false)

function openCreateDialog() {
  formName.value = ''
  formType.value = 'http'
  formTarget.value = ''
  formPort.value = ''
  formExpectedStatus.value = '200'
  formKeyword.value = ''
  formSslDays.value = '14'
  formInterval.value = '60'
  formTimeout.value = '10'
  formAllowPrivate.value = false
  formChannel.value = 'none'
  formError.value = ''
  dialogOpen.value = true
}

async function handleCreateCheck() {
  formError.value = ''
  saving.value = true
  try {
    const payload: Record<string, unknown> = {
      name: formName.value.trim(),
      check_type: formType.value || 'http',
      target: formTarget.value.trim(),
      interval_seconds: Math.max(30, Number.parseInt(formInterval.value, 10) || 60),
      timeout_seconds: Math.max(1, Number.parseInt(formTimeout.value, 10) || 10),
      allow_private_targets: formAllowPrivate.value,
      ssl_expiry_warning_days: Math.max(1, Number.parseInt(formSslDays.value, 10) || 14),
      channel: formChannel.value && formChannel.value !== 'none' ? formChannel.value : null,
    }
    if (formType.value === 'http') {
      payload.expected_status = Number.parseInt(formExpectedStatus.value, 10) || 200
      payload.expected_keyword = formKeyword.value.trim()
    }
    if ((formType.value === 'tcp' || formType.value === 'ssl') && formPort.value.trim()) {
      payload.port = Number.parseInt(formPort.value, 10)
    }
    await api.post('/api/monitoring/uptime-checks/', payload)
    queryClient.invalidateQueries({ queryKey: ['uptime-checks'] })
    dialogOpen.value = false
    toast.success('Uptime check created')
  } catch (err) {
    formError.value = extractApiError(err, 'Could not create uptime check.')
  } finally {
    saving.value = false
  }
}

async function handleRunNow(item: UptimeCheckItem) {
  runningId.value = item.id
  try {
    const resp = await api.post<UptimeResultItem>(`/api/monitoring/uptime-checks/${item.id}/run/`)
    queryClient.invalidateQueries({ queryKey: ['uptime-checks'] })
    if (selectedCheckId.value === item.id) {
      queryClient.invalidateQueries({ queryKey: ['uptime-results', item.id] })
    }
    toast.success(`${item.name}: ${resp.data.status.toUpperCase()}`)
  } catch (err) {
    toast.error(extractApiError(err, 'Could not run check.'))
  } finally {
    runningId.value = null
  }
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await api.delete(`/api/monitoring/uptime-checks/${deleteTarget.value.id}/`)
    if (selectedCheckId.value === deleteTarget.value.id) {
      selectedCheckId.value = null
    }
    queryClient.invalidateQueries({ queryKey: ['uptime-checks'] })
    deleteOpen.value = false
    deleteTarget.value = null
    toast.success('Uptime check deleted')
  } catch (err) {
    toast.error(extractApiError(err, 'Could not delete check.'))
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <section class="uptime-page">
    <header class="page-header">
      <div class="title-block">
        <h1>Uptime Monitoring</h1>
        <span class="badge badge-neutral tabular">{{ summary.total }} checks</span>
      </div>
      <div class="header-actions">
        <Button type="button" data-variant="ghost" :pending="isFetching && !isPending" @click="refetch()">
          <RefreshCw :size="15" aria-hidden="true" />
          <span>Refresh</span>
        </Button>
        <Button v-if="auth.canWrite" type="button" data-variant="solid" @click="openCreateDialog()">
          <Plus :size="15" aria-hidden="true" />
          <span>Add Check</span>
        </Button>
      </div>
    </header>

    <div class="summary-strip" role="region" aria-label="Uptime summary">
      <div class="summary-card card">
        <span class="summary-label">Total</span>
        <strong class="summary-value tabular">{{ summary.total }}</strong>
      </div>
      <div class="summary-card card">
        <span class="summary-label">Up</span>
        <strong class="summary-value val-up tabular">{{ summary.up }}</strong>
      </div>
      <div class="summary-card card">
        <span class="summary-label">Degraded</span>
        <strong class="summary-value val-warn tabular">{{ summary.degraded }}</strong>
      </div>
      <div class="summary-card card">
        <span class="summary-label">Down</span>
        <strong class="summary-value val-down tabular">{{ summary.down }}</strong>
      </div>
    </div>

    <div v-if="isPending" class="card empty-box">Loading uptime checks...</div>
    <div v-else-if="!checks || checks.length === 0" class="card empty-box">
      <Globe :size="28" class="muted-icon" aria-hidden="true" />
      <h2>No uptime checks configured</h2>
      <p>Monitor HTTP endpoints, TCP ports, DNS resolution, ICMP ping, and TLS certificate expiration.</p>
      <Button v-if="auth.canWrite" type="button" data-variant="solid" @click="openCreateDialog()">
        <Plus :size="15" aria-hidden="true" />
        <span>Create First Check</span>
      </Button>
    </div>

    <div v-else class="check-list">
      <article v-for="item in checks" :key="item.id" class="check-card card">
        <div class="check-top">
          <div class="check-meta">
            <div class="check-title-row">
              <button
                type="button"
                class="check-title-btn"
                @click="selectedCheckId = selectedCheckId === item.id ? null : item.id"
              >
                {{ item.name }}
              </button>
              <span class="badge badge-neutral mono">{{ item.check_type.toUpperCase() }}</span>
              <span
                class="badge"
                :class="
                  item.last_status === 'up'
                    ? 'badge-online'
                    : item.last_status === 'degraded'
                      ? 'badge-warning'
                      : item.last_status === 'down'
                        ? 'badge-critical'
                        : 'badge-neutral'
                "
              >
                {{ item.last_status }}
              </span>
              <span
                v-if="item.last_ssl_expiry_days !== null"
                class="badge tabular"
                :class="item.last_ssl_expiry_days <= item.ssl_expiry_warning_days ? 'badge-warning' : 'badge-ok'"
              >
                <ShieldCheck :size="12" aria-hidden="true" />
                SSL {{ item.last_ssl_expiry_days }}d
              </span>
            </div>
            <code class="target-text">{{ item.target }}<template v-if="item.port">:{{ item.port }}</template></code>
            <p v-if="item.last_error" class="error-inline">{{ item.last_error }}</p>
          </div>

          <div class="check-stats tabular">
            <div class="stat-col">
              <span class="stat-lbl">24h Uptime</span>
              <strong>{{ item.uptime_24h_percent !== null ? `${item.uptime_24h_percent.toFixed(2)}%` : '--' }}</strong>
            </div>
            <div class="stat-col">
              <span class="stat-lbl">Latency</span>
              <strong>{{ item.last_latency_ms !== null ? `${item.last_latency_ms.toFixed(0)} ms` : '--' }}</strong>
            </div>
            <div class="stat-col">
              <span class="stat-lbl">Checked</span>
              <span>{{ formatRelativeTime(item.last_checked_at) }}</span>
            </div>
            <div class="check-actions">
              <Button
                v-if="auth.canWrite"
                type="button"
                :pending="runningId === item.id"
                @click="handleRunNow(item)"
              >
                <Play :size="13" aria-hidden="true" />
                <span>Run</span>
              </Button>
              <Button
                v-if="auth.canWrite"
                type="button"
                data-variant="danger"
                aria-label="Delete check"
                @click="
                  deleteTarget = item;
                  deleteOpen = true
                "
              >
                <Trash2 :size="14" aria-hidden="true" />
              </Button>
            </div>
          </div>
        </div>

        <div v-if="item.recent_statuses.length > 0" class="bars-row" aria-label="Recent check history">
          <span
            v-for="(st, idx) in item.recent_statuses"
            :key="idx"
            class="status-bar"
            :data-status="st"
            :title="st"
          />
        </div>
      </article>
    </div>

    <TimeSeriesChart
      v-if="selectedCheck"
      :title="`Response Latency - ${selectedCheck.name}`"
      :subtitle="selectedCheck.target"
      :timestamps="latencyTimestamps"
      :series="latencySeries"
      unit="number"
      height="220px"
    />

    <Dialog v-model:open="dialogOpen">
      <DialogBackdrop />
      <DialogContent class="modal-form-dialog">
        <div class="drawer-head">
          <div>
            <DialogTitle>New Uptime Check</DialogTitle>
            <DialogDescription class="muted">
              Schedule HTTP, TCP, DNS, Ping, or SSL certificate monitoring.
            </DialogDescription>
          </div>
          <DialogClose class="icon-close" aria-label="Close dialog">
            <X :size="16" aria-hidden="true" />
          </DialogClose>
        </div>

        <form class="form-stack" @submit.prevent="handleCreateCheck">
          <div v-if="formError" class="banner-error" role="alert">{{ formError }}</div>

          <div class="form-row-2">
            <Field name="up-name">
              <FieldLabel>Check Name</FieldLabel>
              <Input v-model="formName" placeholder="e.g. Public API Health" required />
            </Field>
            <Field name="up-type">
              <FieldLabel>Check Type</FieldLabel>
              <Select v-model="formType">
                <SelectTrigger aria-label="Check type">
                  <SelectValue />
                  <ChevronDown :size="14" aria-hidden="true" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="http"><SelectItemText>HTTP / HTTPS</SelectItemText></SelectItem>
                  <SelectItem value="tcp"><SelectItemText>TCP Port</SelectItemText></SelectItem>
                  <SelectItem value="ssl"><SelectItemText>SSL Certificate</SelectItemText></SelectItem>
                  <SelectItem value="dns"><SelectItemText>DNS Lookup</SelectItemText></SelectItem>
                  <SelectItem value="ping"><SelectItemText>Ping</SelectItemText></SelectItem>
                </SelectContent>
              </Select>
            </Field>
          </div>

          <Field name="up-target">
            <FieldLabel>{{ formType === 'http' ? 'Endpoint URL' : 'Hostname or IP' }}</FieldLabel>
            <Input
              v-model="formTarget"
              :placeholder="formType === 'http' ? 'https://api.example.com/health' : 'db.example.com'"
              required
            />
          </Field>

          <div v-if="formType === 'http'" class="form-row-2">
            <Field name="up-status">
              <FieldLabel>Expected HTTP Status</FieldLabel>
              <Input v-model="formExpectedStatus" type="number" min="100" max="599" />
            </Field>
            <Field name="up-keyword">
              <FieldLabel>Required Keyword (optional)</FieldLabel>
              <Input v-model="formKeyword" placeholder="e.g. ok" />
            </Field>
          </div>

          <div v-if="formType === 'tcp' || formType === 'ssl'" class="form-row-2">
            <Field name="up-port">
              <FieldLabel>Port</FieldLabel>
              <Input v-model="formPort" type="number" min="1" max="65535" placeholder="443" />
            </Field>
            <Field v-if="formType === 'ssl'" name="up-ssl-days">
              <FieldLabel>Expiry Warning (days)</FieldLabel>
              <Input v-model="formSslDays" type="number" min="1" max="365" />
            </Field>
          </div>

          <div class="form-row-2">
            <Field name="up-interval">
              <FieldLabel>Interval (seconds)</FieldLabel>
              <Input v-model="formInterval" type="number" min="30" max="3600" />
            </Field>
            <Field name="up-timeout">
              <FieldLabel>Timeout (seconds)</FieldLabel>
              <Input v-model="formTimeout" type="number" min="1" max="60" />
            </Field>
          </div>

          <Field name="up-channel">
            <FieldLabel>Notification Channel</FieldLabel>
            <Select v-model="formChannel">
              <SelectTrigger aria-label="Notification channel">
                <SelectValue />
                <ChevronDown :size="14" aria-hidden="true" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none"><SelectItemText>Incidents only (no external channel)</SelectItemText></SelectItem>
                <SelectItem v-for="ch in channels ?? []" :key="ch.id" :value="ch.id">
                  <SelectItemText>{{ ch.name }} ({{ ch.channel_type }})</SelectItemText>
                </SelectItem>
              </SelectContent>
            </Select>
          </Field>

          <label class="switch-row">
            <div>
              <span>Allow private / LAN targets</span>
              <FieldDescription>Enable only if probing internal RFC1918 hosts inside your own network.</FieldDescription>
            </div>
            <Switch :checked="formAllowPrivate" @checked-change="(v: boolean) => (formAllowPrivate = v)">
              <SwitchThumb />
            </Switch>
          </label>

          <div class="dialog-actions">
            <DialogClose class="btn btn-ghost">Cancel</DialogClose>
            <Button type="submit" data-variant="solid" :pending="saving">Create Check</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>

    <AlertDialog v-model:open="deleteOpen">
      <AlertDialogBackdrop />
      <AlertDialogContent class="confirm-dialog">
        <AlertDialogTitle>Delete {{ deleteTarget?.name }}?</AlertDialogTitle>
        <AlertDialogDescription class="muted">
          Check history and scheduled probes for this target will be permanently removed.
        </AlertDialogDescription>
        <div class="dialog-actions">
          <AlertDialogClose class="btn btn-ghost">Cancel</AlertDialogClose>
          <Button type="button" data-variant="danger" :pending="deleting" @click="confirmDelete()">
            Delete Check
          </Button>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  </section>
</template>

<style scoped>
.uptime-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
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
}

.title-block h1 {
  font-size: 1.5rem;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.summary-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.summary-card {
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.summary-label {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-muted);
}

.summary-value {
  font-size: 1.5rem;
  font-weight: 700;
}

.val-up {
  color: var(--accent);
}

.val-warn {
  color: var(--warning);
}

.val-down {
  color: var(--danger);
}

.check-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.check-card {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.check-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.check-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.check-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.check-title-btn {
  border: none;
  background: transparent;
  padding: 0;
  font: inherit;
  font-size: 1rem;
  font-weight: 600;
  color: var(--ink);
  cursor: pointer;
}

.check-title-btn:hover {
  color: var(--accent);
}

.target-text {
  font-size: 0.8rem;
  color: var(--ink-muted);
}

.error-inline {
  margin: 2px 0 0;
  font-size: 0.8rem;
  color: var(--danger);
}

.check-stats {
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
}

.stat-col {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  font-size: 0.85rem;
}

.stat-lbl {
  font-size: 0.7rem;
  text-transform: uppercase;
  color: var(--ink-muted);
}

.check-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.bars-row {
  display: flex;
  gap: 3px;
  height: 18px;
  align-items: stretch;
}

.status-bar {
  flex: 1;
  max-width: 14px;
  border-radius: 3px;
  background: var(--border);
}

.status-bar[data-status='up'] {
  background: var(--accent);
}

.status-bar[data-status='degraded'] {
  background: var(--warning);
}

.status-bar[data-status='down'] {
  background: var(--danger);
}

.empty-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 44px 20px;
  text-align: center;
  color: var(--ink-muted);
}

.empty-box h2 {
  font-size: 1.05rem;
  color: var(--ink);
}

.muted {
  color: var(--ink-muted);
  font-size: 0.84rem;
  margin: 0;
}

.muted-icon {
  color: var(--ink-muted);
}

.modal-form-dialog {
  width: min(580px, calc(100vw - 32px));
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.drawer-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
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

.form-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-row-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 0.875rem;
  cursor: pointer;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.confirm-dialog {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

@media (max-width: 760px) {
  .summary-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .form-row-2 {
    grid-template-columns: 1fr;
  }
}
</style>
