<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  Bell,
  BellOff,
  Check,
  CheckCircle2,
  ChevronDown,
  Copy,
  MessageSquare,
  Pencil,
  Plus,
  RefreshCw,
  Send,
  ShieldAlert,
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
  Select,
  SelectContent,
  SelectItem,
  SelectItemText,
  SelectTrigger,
  SelectValue,
} from '@ui-sdk/vue/select'
import { Switch, SwitchThumb } from '@ui-sdk/vue/switch'
import { Tabs, TabsList, TabsPanel, TabsTab } from '@ui-sdk/vue/tabs'
import { Textarea } from '@ui-sdk/vue/textarea'
import { toast } from '@ui-sdk/vue/toast'
import {
  api,
  extractApiError,
  unwrapResults,
  type AlertRuleRecord,
  type AlertSilenceRecord,
  type IncidentRecord,
  type NotificationChannelRecord,
  type ServerRecord,
} from '../api/client'
import { useAuthStore } from '../stores/auth'
import { formatDateTime, formatRelativeTime } from '../utils/format'

const VALID_TABS = ['incidents', 'rules', 'channels', 'silences'] as const
type AlertTab = (typeof VALID_TABS)[number]

const METRIC_LABELS: Record<string, string> = {
  cpu: 'CPU Usage (%)',
  ram: 'RAM Usage (%)',
  disk: 'Disk Usage (%)',
  disk_io: 'Disk I/O (MB)',
  swap: 'Swap Usage (%)',
  load: 'Load Average (1m)',
  no_data: 'Host Offline / No Data',
}

const OPERATOR_LABELS: Record<string, string> = {
  gt: '>',
  gte: '>=',
  lt: '<',
  lte: '<=',
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const queryClient = useQueryClient()

const initialTab = VALID_TABS.includes(route.query.tab as AlertTab)
  ? (route.query.tab as AlertTab)
  : 'incidents'
const activeTab = ref<string | null>(initialTab)

watch(activeTab, (next) => {
  if (next && VALID_TABS.includes(next as AlertTab)) {
    router.replace({ query: { ...route.query, tab: next } })
  }
})

const incidentStatusFilter = ref<string | null>('all')
const incidentSeverityFilter = ref<string | null>('all')

const { data: servers } = useQuery<ServerRecord[]>({
  queryKey: ['servers'],
  queryFn: async () => unwrapResults<ServerRecord>((await api.get('/api/monitoring/servers/')).data),
})

const {
  data: incidents,
  isPending: incidentsPending,
  refetch: refetchIncidents,
} = useQuery<IncidentRecord[]>({
  queryKey: computed(() => ['incidents', incidentStatusFilter.value, incidentSeverityFilter.value]),
  queryFn: async () => {
    const params: Record<string, string> = {}
    if (incidentStatusFilter.value && incidentStatusFilter.value !== 'all') {
      params.status = incidentStatusFilter.value
    }
    if (incidentSeverityFilter.value && incidentSeverityFilter.value !== 'all') {
      params.severity = incidentSeverityFilter.value
    }
    const resp = await api.get('/api/monitoring/incidents/', { params })
    return unwrapResults<IncidentRecord>(resp.data)
  },
  refetchInterval: 30000,
})

const {
  data: rules,
  isPending: rulesPending,
  refetch: refetchRules,
} = useQuery<AlertRuleRecord[]>({
  queryKey: ['alert-rules'],
  queryFn: async () => unwrapResults<AlertRuleRecord>((await api.get('/api/monitoring/rules/')).data),
})

const {
  data: channels,
  isPending: channelsPending,
  refetch: refetchChannels,
} = useQuery<NotificationChannelRecord[]>({
  queryKey: ['notification-channels'],
  queryFn: async () =>
    unwrapResults<NotificationChannelRecord>((await api.get('/api/monitoring/channels/')).data),
})

const {
  data: silences,
  isPending: silencesPending,
  refetch: refetchSilences,
} = useQuery<AlertSilenceRecord[]>({
  queryKey: ['alert-silences'],
  queryFn: async () =>
    unwrapResults<AlertSilenceRecord>((await api.get('/api/monitoring/silences/')).data),
})

const openIncidentCount = computed(
  () => (incidents.value ?? []).filter((inc) => inc.status === 'open').length,
)

const serverNameById = computed(() => {
  const map: Record<string, string> = {}
  for (const s of servers.value ?? []) {
    map[s.id] = s.name
  }
  return map
})

const channelNameById = computed(() => {
  const map: Record<string, string> = {}
  for (const c of channels.value ?? []) {
    map[c.id] = c.name
  }
  return map
})

const selectedIncidentId = ref<string | null>(null)
const incidentDrawerOpen = ref(false)
const commentBody = ref('')
const postingComment = ref(false)
const silenceDuration = ref<string | null>('60')
const silencingIncident = ref(false)
const mutatingIncidentId = ref<string | null>(null)

const selectedIncident = computed<IncidentRecord | null>(() => {
  if (!selectedIncidentId.value) return null
  return (incidents.value ?? []).find((inc) => inc.id === selectedIncidentId.value) ?? null
})

function openIncidentDrawer(inc: IncidentRecord) {
  selectedIncidentId.value = inc.id
  commentBody.value = ''
  silenceDuration.value = '60'
  incidentDrawerOpen.value = true
}

async function handleAcknowledge(inc: IncidentRecord) {
  mutatingIncidentId.value = inc.id
  try {
    await api.post(`/api/monitoring/incidents/${inc.id}/acknowledge/`)
    queryClient.invalidateQueries({ queryKey: ['incidents'] })
    queryClient.invalidateQueries({ queryKey: ['servers'] })
    toast.success('Incident acknowledged')
  } catch (err) {
    toast.error(extractApiError(err, 'Could not acknowledge incident.'))
  } finally {
    mutatingIncidentId.value = null
  }
}

async function handleResolve(inc: IncidentRecord) {
  mutatingIncidentId.value = inc.id
  try {
    await api.post(`/api/monitoring/incidents/${inc.id}/resolve/`)
    queryClient.invalidateQueries({ queryKey: ['incidents'] })
    queryClient.invalidateQueries({ queryKey: ['servers'] })
    toast.success('Incident resolved')
  } catch (err) {
    toast.error(extractApiError(err, 'Could not resolve incident.'))
  } finally {
    mutatingIncidentId.value = null
  }
}

async function handlePostComment() {
  if (!selectedIncident.value || !commentBody.value.trim()) return
  postingComment.value = true
  try {
    await api.post(`/api/monitoring/incidents/${selectedIncident.value.id}/comments/`, {
      body: commentBody.value.trim(),
    })
    commentBody.value = ''
    queryClient.invalidateQueries({ queryKey: ['incidents'] })
    toast.success('Comment posted')
  } catch (err) {
    toast.error(extractApiError(err, 'Could not post comment.'))
  } finally {
    postingComment.value = false
  }
}

async function handleSilenceIncident() {
  if (!selectedIncident.value) return
  silencingIncident.value = true
  try {
    const minutes = Number.parseInt(silenceDuration.value || '60', 10) || 60
    await api.post(`/api/monitoring/incidents/${selectedIncident.value.id}/silence/`, {
      duration_minutes: minutes,
      reason: `Silenced for ${minutes}m from incident view`,
    })
    queryClient.invalidateQueries({ queryKey: ['alert-silences'] })
    toast.success(`Silenced alerts for ${minutes} minutes`)
  } catch (err) {
    toast.error(extractApiError(err, 'Could not create silence.'))
  } finally {
    silencingIncident.value = false
  }
}

const ruleDialogOpen = ref(false)
const editingRuleId = ref<string | null>(null)
const ruleScope = ref<string | null>('server')
const ruleServerId = ref<string | null>(null)
const ruleTagFilter = ref('')
const ruleMetric = ref<string | null>('cpu')
const ruleOperator = ref<string | null>('gt')
const ruleAggregation = ref<string | null>('avg')
const ruleThreshold = ref('85')
const ruleDuration = ref('5')
const ruleSeverity = ref<string | null>('warning')
const ruleChannelId = ref<string | null>('inline')
const ruleNotifyType = ref<string | null>('EMAIL')
const ruleNotifyTarget = ref('')
const ruleSaving = ref(false)
const ruleError = ref('')
const revealedSecret = ref('')
const copiedSecret = ref(false)

const deleteTarget = ref<{ kind: 'rule' | 'channel' | 'silence'; id: string; label: string } | null>(null)
const deleteDialogOpen = ref(false)
const deletingItem = ref(false)

function openCreateRuleDialog() {
  editingRuleId.value = null
  ruleScope.value = 'server'
  ruleServerId.value = (servers.value && servers.value[0]?.id) || null
  ruleTagFilter.value = ''
  ruleMetric.value = 'cpu'
  ruleOperator.value = 'gt'
  ruleAggregation.value = 'avg'
  ruleThreshold.value = '85'
  ruleDuration.value = '5'
  ruleSeverity.value = 'warning'
  ruleChannelId.value = (channels.value && channels.value[0]?.id) || 'inline'
  ruleNotifyType.value = 'EMAIL'
  ruleNotifyTarget.value = ''
  ruleError.value = ''
  ruleDialogOpen.value = true
}

function openEditRuleDialog(rule: AlertRuleRecord) {
  editingRuleId.value = rule.id
  ruleScope.value = rule.scope || 'server'
  ruleServerId.value = rule.server ?? null
  ruleTagFilter.value = rule.tag_filter || ''
  ruleMetric.value = rule.metric_type
  ruleOperator.value = rule.operator || 'gt'
  ruleAggregation.value = rule.aggregation || 'avg'
  ruleThreshold.value = String(rule.threshold_value)
  ruleDuration.value = String(rule.duration_minutes ?? 5)
  ruleSeverity.value = rule.severity || 'warning'
  ruleChannelId.value = rule.channel ?? 'inline'
  ruleNotifyType.value = rule.notification_type || 'EMAIL'
  ruleNotifyTarget.value = rule.notification_target || ''
  ruleError.value = ''
  ruleDialogOpen.value = true
}

async function handleSaveRule() {
  ruleError.value = ''
  ruleSaving.value = true
  try {
    const scope = ruleScope.value || 'server'
    const payload: Record<string, unknown> = {
      scope,
      server: scope === 'server' ? ruleServerId.value : null,
      tag_filter: scope === 'tag' ? ruleTagFilter.value.trim().toLowerCase() : '',
      metric_type: ruleMetric.value || 'cpu',
      operator: ruleOperator.value || 'gt',
      aggregation: ruleAggregation.value || 'avg',
      threshold_value: Number.parseFloat(ruleThreshold.value) || 0,
      duration_minutes: Math.max(1, Number.parseInt(ruleDuration.value, 10) || 1),
      severity: ruleSeverity.value || 'warning',
    }
    if (ruleChannelId.value && ruleChannelId.value !== 'inline') {
      payload.channel = ruleChannelId.value
    } else {
      payload.channel = null
      payload.notification_type = ruleNotifyType.value || 'EMAIL'
      payload.notification_target = ruleNotifyTarget.value.trim()
    }

    if (editingRuleId.value) {
      await api.patch(`/api/monitoring/rules/${editingRuleId.value}/`, payload)
      toast.success('Alert rule updated')
    } else {
      const resp = await api.post<AlertRuleRecord & { webhook_secret?: string }>(
        '/api/monitoring/rules/',
        payload,
      )
      if (resp.data?.webhook_secret) {
        revealedSecret.value = resp.data.webhook_secret
      }
      toast.success('Alert rule created')
    }
    queryClient.invalidateQueries({ queryKey: ['alert-rules'] })
    ruleDialogOpen.value = false
  } catch (err) {
    ruleError.value = extractApiError(err, 'Could not save alert rule.')
  } finally {
    ruleSaving.value = false
  }
}

async function toggleRuleActive(rule: AlertRuleRecord, checked: boolean) {
  try {
    await api.patch(`/api/monitoring/rules/${rule.id}/`, { is_active: checked })
    queryClient.invalidateQueries({ queryKey: ['alert-rules'] })
    toast.success(checked ? 'Rule enabled' : 'Rule paused')
  } catch (err) {
    toast.error(extractApiError(err, 'Could not toggle rule.'))
  }
}

const channelDialogOpen = ref(false)
const channelName = ref('')
const channelType = ref<string | null>('WEBHOOK')
const channelTarget = ref('')
const channelSecret = ref('')
const channelDefault = ref(false)
const channelSaving = ref(false)
const channelError = ref('')
const testingChannelId = ref<string | null>(null)

const CHANNEL_META: Record<
  string,
  { label: string; targetLabel: string; targetPlaceholder: string; secretLabel?: string; secretRequired?: boolean }
> = {
  WEBHOOK: {
    label: 'Generic Webhook',
    targetLabel: 'Webhook URL',
    targetPlaceholder: 'https://hooks.example.com/sysroar',
  },
  EMAIL: {
    label: 'Email',
    targetLabel: 'Email Address',
    targetPlaceholder: 'alerts@example.com',
  },
  SLACK: {
    label: 'Slack',
    targetLabel: 'Slack Incoming Webhook URL',
    targetPlaceholder: 'https://hooks.slack.com/services/...',
  },
  DISCORD: {
    label: 'Discord',
    targetLabel: 'Discord Webhook URL',
    targetPlaceholder: 'https://discord.com/api/webhooks/...',
  },
  TEAMS: {
    label: 'Microsoft Teams',
    targetLabel: 'Teams Webhook URL',
    targetPlaceholder: 'https://outlook.office.com/webhook/...',
  },
  TELEGRAM: {
    label: 'Telegram',
    targetLabel: 'Chat ID',
    targetPlaceholder: '-1001234567890',
    secretLabel: 'Telegram Bot Token',
    secretRequired: true,
  },
  PAGERDUTY: {
    label: 'PagerDuty',
    targetLabel: 'Events API URL (optional)',
    targetPlaceholder: 'https://events.pagerduty.com/v2/enqueue',
    secretLabel: 'Routing Key (Integration Key)',
    secretRequired: true,
  },
  OPSGENIE: {
    label: 'Opsgenie',
    targetLabel: 'Alerts API URL (optional)',
    targetPlaceholder: 'https://api.opsgenie.com/v2/alerts',
    secretLabel: 'GenieKey API Key',
    secretRequired: true,
  },
  NTFY: {
    label: 'ntfy',
    targetLabel: 'Topic URL',
    targetPlaceholder: 'https://ntfy.sh/my-ops-alerts',
    secretLabel: 'Bearer Token (optional)',
  },
  GOTIFY: {
    label: 'Gotify',
    targetLabel: 'Gotify Server URL',
    targetPlaceholder: 'https://gotify.example.com',
    secretLabel: 'Application Token',
    secretRequired: true,
  },
}

const activeChannelMeta = computed(() => CHANNEL_META[channelType.value || 'WEBHOOK'] || CHANNEL_META.WEBHOOK)

function openCreateChannelDialog() {
  channelName.value = ''
  channelType.value = 'WEBHOOK'
  channelTarget.value = ''
  channelSecret.value = ''
  channelDefault.value = false
  channelError.value = ''
  channelDialogOpen.value = true
}

async function handleCreateChannel() {
  channelError.value = ''
  channelSaving.value = true
  try {
    const payload: Record<string, unknown> = {
      name: channelName.value.trim(),
      channel_type: channelType.value || 'WEBHOOK',
      target: channelTarget.value.trim(),
      is_default: channelDefault.value,
    }
    if (channelSecret.value.trim()) {
      payload.webhook_secret = channelSecret.value.trim()
    }
    const resp = await api.post<NotificationChannelRecord & { webhook_secret?: string }>(
      '/api/monitoring/channels/',
      payload,
    )
    queryClient.invalidateQueries({ queryKey: ['notification-channels'] })
    channelDialogOpen.value = false
    if (resp.data?.webhook_secret) {
      revealedSecret.value = resp.data.webhook_secret
    }
    toast.success('Notification channel created')
  } catch (err) {
    channelError.value = extractApiError(err, 'Could not create notification channel.')
  } finally {
    channelSaving.value = false
  }
}

async function handleTestChannel(channel: NotificationChannelRecord) {
  testingChannelId.value = channel.id
  try {
    const resp = await api.post<{ delivered: boolean; detail?: string }>(
      `/api/monitoring/channels/${channel.id}/test/`,
    )
    toast.success(`Test sent to ${channel.name} (${resp.data.detail || 'OK'})`)
  } catch (err) {
    toast.error(extractApiError(err, `Test delivery failed for ${channel.name}.`))
  } finally {
    testingChannelId.value = null
  }
}

const silenceDialogOpen = ref(false)
const silenceServerId = ref<string | null>('all')
const silenceRuleId = ref<string | null>('all')
const silenceMinutes = ref<string | null>('60')
const silenceReason = ref('')
const silenceSaving = ref(false)
const silenceError = ref('')

function openCreateSilenceDialog() {
  silenceServerId.value = 'all'
  silenceRuleId.value = 'all'
  silenceMinutes.value = '60'
  silenceReason.value = ''
  silenceError.value = ''
  silenceDialogOpen.value = true
}

async function handleCreateSilence() {
  silenceError.value = ''
  silenceSaving.value = true
  try {
    const minutes = Number.parseInt(silenceMinutes.value || '60', 10) || 60
    const now = new Date()
    const ends = new Date(now.getTime() + minutes * 60000)
    await api.post('/api/monitoring/silences/', {
      server: silenceServerId.value && silenceServerId.value !== 'all' ? silenceServerId.value : null,
      rule: silenceRuleId.value && silenceRuleId.value !== 'all' ? silenceRuleId.value : null,
      reason: silenceReason.value.trim() || 'Scheduled maintenance window',
      starts_at: now.toISOString(),
      ends_at: ends.toISOString(),
    })
    queryClient.invalidateQueries({ queryKey: ['alert-silences'] })
    silenceDialogOpen.value = false
    toast.success('Maintenance silence created')
  } catch (err) {
    silenceError.value = extractApiError(err, 'Could not create silence.')
  } finally {
    silenceSaving.value = false
  }
}

function requestDelete(kind: 'rule' | 'channel' | 'silence', id: string, label: string) {
  deleteTarget.value = { kind, id, label }
  deleteDialogOpen.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deletingItem.value = true
  try {
    const { kind, id } = deleteTarget.value
    if (kind === 'rule') {
      await api.delete(`/api/monitoring/rules/${id}/`)
      queryClient.invalidateQueries({ queryKey: ['alert-rules'] })
      toast.success('Alert rule deleted')
    } else if (kind === 'channel') {
      await api.delete(`/api/monitoring/channels/${id}/`)
      queryClient.invalidateQueries({ queryKey: ['notification-channels'] })
      toast.success('Notification channel deleted')
    } else {
      await api.delete(`/api/monitoring/silences/${id}/`)
      queryClient.invalidateQueries({ queryKey: ['alert-silences'] })
      toast.success('Silence removed')
    }
    deleteDialogOpen.value = false
    deleteTarget.value = null
  } catch (err) {
    toast.error(extractApiError(err, 'Could not delete item.'))
  } finally {
    deletingItem.value = false
  }
}

async function copySecret() {
  try {
    await navigator.clipboard.writeText(revealedSecret.value)
    copiedSecret.value = true
    toast.success('Webhook secret copied')
    setTimeout(() => {
      copiedSecret.value = false
    }, 2000)
  } catch {
    toast.error('Clipboard access denied')
  }
}

function ruleTargetLabel(rule: AlertRuleRecord): string {
  if (rule.scope === 'all') return 'All servers'
  if (rule.scope === 'tag') return `#${rule.tag_filter || 'tag'}`
  return rule.server_name || (rule.server ? serverNameById.value[rule.server] : 'Unassigned') || 'Server'
}

function refreshCurrent() {
  refetchIncidents()
  refetchRules()
  refetchChannels()
  refetchSilences()
}
</script>

<template>
  <section class="alerts-page">
    <header class="page-header">
      <div class="title-block">
        <h1>Alerts &amp; Incidents</h1>
        <span v-if="openIncidentCount > 0" class="badge badge-critical tabular">
          {{ openIncidentCount }} open
        </span>
      </div>
      <div class="header-actions">
        <Button type="button" data-variant="ghost" @click="refreshCurrent()">
          <RefreshCw :size="15" aria-hidden="true" />
          <span>Refresh</span>
        </Button>
        <Button v-if="auth.canWrite" type="button" data-variant="solid" @click="openCreateRuleDialog()">
          <Plus :size="15" aria-hidden="true" />
          <span>New Rule</span>
        </Button>
      </div>
    </header>

    <div v-if="revealedSecret" class="secret-banner card" role="status">
      <div>
        <strong>One-time Webhook Signing Secret</strong>
        <p class="muted">Save this HMAC-SHA256 secret now. It will not be shown again.</p>
        <code class="secret-val">{{ revealedSecret }}</code>
      </div>
      <div class="secret-actions">
        <Button type="button" data-variant="ghost" @click="copySecret()">
          <Check v-if="copiedSecret" :size="14" aria-hidden="true" />
          <Copy v-else :size="14" aria-hidden="true" />
          <span>{{ copiedSecret ? 'Copied' : 'Copy' }}</span>
        </Button>
        <Button type="button" data-variant="ghost" @click="revealedSecret = ''">Dismiss</Button>
      </div>
    </div>

    <Tabs v-model="activeTab">
      <TabsList aria-label="Alerts sections">
        <TabsTab value="incidents">
          <ShieldAlert :size="14" aria-hidden="true" />
          <span>Incidents</span>
        </TabsTab>
        <TabsTab value="rules">
          <Bell :size="14" aria-hidden="true" />
          <span>Rules ({{ rules?.length ?? 0 }})</span>
        </TabsTab>
        <TabsTab value="channels">
          <Send :size="14" aria-hidden="true" />
          <span>Channels ({{ channels?.length ?? 0 }})</span>
        </TabsTab>
        <TabsTab value="silences">
          <BellOff :size="14" aria-hidden="true" />
          <span>Silences ({{ silences?.length ?? 0 }})</span>
        </TabsTab>
      </TabsList>

      <TabsPanel value="incidents" class="tab-panel">
        <div class="filter-bar">
          <Select v-model="incidentStatusFilter">
            <SelectTrigger aria-label="Filter incidents by status">
              <SelectValue placeholder="All statuses" />
              <ChevronDown :size="15" aria-hidden="true" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all"><SelectItemText>All statuses</SelectItemText></SelectItem>
              <SelectItem value="open"><SelectItemText>Open</SelectItemText></SelectItem>
              <SelectItem value="acknowledged"><SelectItemText>Acknowledged</SelectItemText></SelectItem>
              <SelectItem value="resolved"><SelectItemText>Resolved</SelectItemText></SelectItem>
            </SelectContent>
          </Select>

          <Select v-model="incidentSeverityFilter">
            <SelectTrigger aria-label="Filter incidents by severity">
              <SelectValue placeholder="All severities" />
              <ChevronDown :size="15" aria-hidden="true" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all"><SelectItemText>All severities</SelectItemText></SelectItem>
              <SelectItem value="critical"><SelectItemText>Critical</SelectItemText></SelectItem>
              <SelectItem value="warning"><SelectItemText>Warning</SelectItemText></SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div v-if="incidentsPending" class="card empty-box">Loading incidents...</div>
        <div v-else-if="!incidents || incidents.length === 0" class="card empty-box">
          <CheckCircle2 :size="24" class="ok-icon" aria-hidden="true" />
          <p>No incidents match the active filter.</p>
        </div>
        <div v-else class="card table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>Incident</th>
                <th>Server</th>
                <th>Severity</th>
                <th>Status</th>
                <th class="num">Value</th>
                <th class="num">Opened</th>
                <th class="num">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="inc in incidents" :key="inc.id">
                <td>
                  <button type="button" class="link-btn" @click="openIncidentDrawer(inc)">
                    {{ inc.title }}
                  </button>
                  <span v-if="inc.comments && inc.comments.length > 0" class="comment-pill tabular">
                    <MessageSquare :size="12" aria-hidden="true" />
                    {{ inc.comments.length }}
                  </span>
                </td>
                <td>
                  <router-link :to="`/servers/${inc.server}`" class="server-link">
                    {{ inc.server_name || serverNameById[inc.server] || inc.server }}
                  </router-link>
                </td>
                <td>
                  <span class="badge" :class="`badge-${inc.severity}`">{{ inc.severity }}</span>
                </td>
                <td>
                  <span
                    class="badge"
                    :class="
                      inc.status === 'resolved'
                        ? 'badge-ok'
                        : inc.status === 'acknowledged'
                          ? 'badge-warning'
                          : 'badge-critical'
                    "
                  >
                    {{ inc.status }}
                  </span>
                </td>
                <td class="num tabular">
                  {{ inc.trigger_value !== null && inc.trigger_value !== undefined ? inc.trigger_value.toFixed(1) : '--' }}
                </td>
                <td class="num tabular">{{ formatRelativeTime(inc.opened_at) }}</td>
                <td class="num actions-cell">
                  <Button type="button" data-variant="ghost" @click="openIncidentDrawer(inc)">Details</Button>
                  <Button
                    v-if="auth.canWrite && inc.status === 'open'"
                    type="button"
                    :pending="mutatingIncidentId === inc.id"
                    @click="handleAcknowledge(inc)"
                  >
                    Acknowledge
                  </Button>
                  <Button
                    v-if="auth.canWrite && inc.status !== 'resolved'"
                    type="button"
                    data-variant="solid"
                    :pending="mutatingIncidentId === inc.id"
                    @click="handleResolve(inc)"
                  >
                    Resolve
                  </Button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </TabsPanel>

      <TabsPanel value="rules" class="tab-panel">
        <div v-if="rulesPending" class="card empty-box">Loading alert rules...</div>
        <div v-else-if="!rules || rules.length === 0" class="card empty-box">
          <p>No alert rules configured yet.</p>
          <Button v-if="auth.canWrite" type="button" data-variant="solid" @click="openCreateRuleDialog()">
            <Plus :size="15" aria-hidden="true" />
            <span>Create First Rule</span>
          </Button>
        </div>
        <div v-else class="card table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>Target</th>
                <th>Condition</th>
                <th>Severity</th>
                <th>Delivery</th>
                <th>Active</th>
                <th v-if="auth.canWrite" class="num">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="rule in rules" :key="rule.id">
                <td>
                  <strong>{{ ruleTargetLabel(rule) }}</strong>
                  <span class="scope-tag">{{ rule.scope || 'server' }}</span>
                </td>
                <td class="mono tabular">
                  {{ METRIC_LABELS[rule.metric_type] || rule.metric_type }}
                  ({{ rule.aggregation || 'avg' }})
                  {{ OPERATOR_LABELS[rule.operator || 'gt'] || '>' }}
                  {{ rule.threshold_value }}
                  for {{ rule.duration_minutes ?? 5 }}m
                </td>
                <td>
                  <span class="badge" :class="`badge-${rule.severity || 'warning'}`">
                    {{ rule.severity || 'warning' }}
                  </span>
                </td>
                <td class="muted">
                  {{
                    rule.channel
                      ? channelNameById[rule.channel] || 'Saved Channel'
                      : `${rule.notification_type || 'EMAIL'}: ${rule.notification_target || '--'}`
                  }}
                </td>
                <td>
                  <Switch
                    :checked="rule.is_active !== false"
                    :disabled="!auth.canWrite"
                    :aria-label="`Toggle rule ${rule.metric_type}`"
                    @checked-change="(val: boolean) => toggleRuleActive(rule, val)"
                  >
                    <SwitchThumb />
                  </Switch>
                </td>
                <td v-if="auth.canWrite" class="num actions-cell">
                  <Button type="button" data-variant="ghost" aria-label="Edit rule" @click="openEditRuleDialog(rule)">
                    <Pencil :size="14" aria-hidden="true" />
                  </Button>
                  <Button
                    type="button"
                    data-variant="danger"
                    aria-label="Delete rule"
                    @click="requestDelete('rule', rule.id, `${rule.metric_type} rule`)"
                  >
                    <Trash2 :size="14" aria-hidden="true" />
                  </Button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </TabsPanel>

      <TabsPanel value="channels" class="tab-panel">
        <div class="sub-bar">
          <p class="muted">Reusable Email and HMAC-signed Webhook destinations with SSRF protection.</p>
          <Button v-if="auth.canWrite" type="button" data-variant="solid" @click="openCreateChannelDialog()">
            <Plus :size="15" aria-hidden="true" />
            <span>Add Channel</span>
          </Button>
        </div>

        <div v-if="channelsPending" class="card empty-box">Loading channels...</div>
        <div v-else-if="!channels || channels.length === 0" class="card empty-box">
          <p>No notification channels configured yet.</p>
        </div>
        <div v-else class="card table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Target</th>
                <th>Status</th>
                <th v-if="auth.canWrite" class="num">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="ch in channels" :key="ch.id">
                <td>
                  <strong>{{ ch.name }}</strong>
                  <span v-if="ch.is_default" class="badge badge-ok">Default</span>
                </td>
                <td><span class="badge badge-neutral">{{ ch.channel_type }}</span></td>
                <td><code class="target-code">{{ ch.target }}</code></td>
                <td>
                  <span class="badge" :class="ch.is_active !== false ? 'badge-ok' : 'badge-neutral'">
                    {{ ch.is_active !== false ? 'Active' : 'Disabled' }}
                  </span>
                </td>
                <td v-if="auth.canWrite" class="num actions-cell">
                  <Button
                    type="button"
                    :pending="testingChannelId === ch.id"
                    @click="handleTestChannel(ch)"
                  >
                    <Send :size="14" aria-hidden="true" />
                    <span>Send Test</span>
                  </Button>
                  <Button
                    type="button"
                    data-variant="danger"
                    aria-label="Delete channel"
                    @click="requestDelete('channel', ch.id, ch.name)"
                  >
                    <Trash2 :size="14" aria-hidden="true" />
                  </Button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </TabsPanel>

      <TabsPanel value="silences" class="tab-panel">
        <div class="sub-bar">
          <p class="muted">Suppress alert firing during planned deployments or maintenance windows.</p>
          <Button v-if="auth.canWrite" type="button" data-variant="solid" @click="openCreateSilenceDialog()">
            <Plus :size="15" aria-hidden="true" />
            <span>Create Silence</span>
          </Button>
        </div>

        <div v-if="silencesPending" class="card empty-box">Loading silences...</div>
        <div v-else-if="!silences || silences.length === 0" class="card empty-box">
          <p>No active or scheduled alert silences.</p>
        </div>
        <div v-else class="card table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>Scope</th>
                <th>Reason</th>
                <th>Starts</th>
                <th>Ends</th>
                <th v-if="auth.canWrite" class="num">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="sil in silences" :key="sil.id">
                <td>
                  {{ sil.server ? serverNameById[sil.server] || sil.server : 'All servers' }}
                </td>
                <td>{{ sil.reason || '--' }}</td>
                <td class="tabular muted">{{ formatDateTime(sil.starts_at) }}</td>
                <td class="tabular">{{ formatDateTime(sil.ends_at) }}</td>
                <td v-if="auth.canWrite" class="num actions-cell">
                  <Button
                    type="button"
                    data-variant="danger"
                    aria-label="Remove silence"
                    @click="requestDelete('silence', sil.id, sil.reason || 'this silence')"
                  >
                    <Trash2 :size="14" aria-hidden="true" />
                  </Button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </TabsPanel>
    </Tabs>

    <Drawer v-model:open="incidentDrawerOpen" side="right">
      <DrawerBackdrop />
      <DrawerContent side="right">
        <div v-if="selectedIncident" class="inc-drawer">
          <div class="drawer-head">
            <div>
              <DrawerTitle>{{ selectedIncident.title }}</DrawerTitle>
              <DrawerDescription class="muted">
                {{ selectedIncident.server_name || serverNameById[selectedIncident.server] }}
                - Opened {{ formatDateTime(selectedIncident.opened_at) }}
              </DrawerDescription>
            </div>
            <DrawerClose class="icon-close" aria-label="Close drawer">
              <X :size="16" aria-hidden="true" />
            </DrawerClose>
          </div>

          <div class="inc-badges">
            <span class="badge" :class="`badge-${selectedIncident.severity}`">
              {{ selectedIncident.severity }}
            </span>
            <span class="badge badge-neutral">{{ selectedIncident.status }}</span>
            <span v-if="selectedIncident.trigger_value !== null && selectedIncident.trigger_value !== undefined" class="badge badge-neutral tabular">
              Trigger: {{ selectedIncident.trigger_value.toFixed(1) }}
            </span>
          </div>

          <div v-if="auth.canWrite" class="inc-actions">
            <Button
              v-if="selectedIncident.status === 'open'"
              type="button"
              :pending="mutatingIncidentId === selectedIncident.id"
              @click="handleAcknowledge(selectedIncident)"
            >
              Acknowledge
            </Button>
            <Button
              v-if="selectedIncident.status !== 'resolved'"
              type="button"
              data-variant="solid"
              :pending="mutatingIncidentId === selectedIncident.id"
              @click="handleResolve(selectedIncident)"
            >
              Resolve
            </Button>
          </div>

          <div v-if="auth.canWrite" class="silence-bar card">
            <span class="section-label">Quick Silence</span>
            <div class="silence-controls">
              <Select v-model="silenceDuration">
                <SelectTrigger aria-label="Silence duration">
                  <SelectValue />
                  <ChevronDown :size="14" aria-hidden="true" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="30"><SelectItemText>30 minutes</SelectItemText></SelectItem>
                  <SelectItem value="60"><SelectItemText>1 hour</SelectItemText></SelectItem>
                  <SelectItem value="240"><SelectItemText>4 hours</SelectItemText></SelectItem>
                  <SelectItem value="1440"><SelectItemText>24 hours</SelectItemText></SelectItem>
                </SelectContent>
              </Select>
              <Button type="button" :pending="silencingIncident" @click="handleSilenceIncident()">
                <BellOff :size="14" aria-hidden="true" />
                <span>Silence</span>
              </Button>
            </div>
          </div>

          <div class="comments-section">
            <span class="section-label">Activity &amp; Comments</span>
            <div v-if="!selectedIncident.comments || selectedIncident.comments.length === 0" class="muted">
              No comments yet.
            </div>
            <ul v-else class="comment-list">
              <li v-for="c in selectedIncident.comments" :key="c.id" class="comment-item">
                <div class="comment-meta">
                  <strong>{{ c.author_username || 'Operator' }}</strong>
                  <span class="muted tabular">{{ formatRelativeTime(c.created_at) }}</span>
                </div>
                <p>{{ c.body }}</p>
              </li>
            </ul>

            <form v-if="auth.canWrite" class="comment-form" @submit.prevent="handlePostComment">
              <Field name="comment">
                <FieldLabel>Add a note</FieldLabel>
                <Textarea
                  v-model="commentBody"
                  rows="3"
                  placeholder="Document investigation findings or remediation steps..."
                />
              </Field>
              <Button type="submit" data-variant="solid" :pending="postingComment">Post Comment</Button>
            </form>
          </div>
        </div>
      </DrawerContent>
    </Drawer>

    <Dialog v-model:open="ruleDialogOpen">
      <DialogBackdrop />
      <DialogContent class="modal-form-dialog">
        <div class="drawer-head">
          <div>
            <DialogTitle>{{ editingRuleId ? 'Edit Alert Rule' : 'New Alert Rule' }}</DialogTitle>
            <DialogDescription class="muted">
              Define threshold conditions and routing for automated incident creation.
            </DialogDescription>
          </div>
          <DialogClose class="icon-close" aria-label="Close dialog">
            <X :size="16" aria-hidden="true" />
          </DialogClose>
        </div>

        <form class="form-stack" @submit.prevent="handleSaveRule">
          <div v-if="ruleError" class="banner-error" role="alert">{{ ruleError }}</div>

          <div class="form-row-2">
            <Field name="scope">
              <FieldLabel>Target Scope</FieldLabel>
              <Select v-model="ruleScope">
                <SelectTrigger aria-label="Rule scope">
                  <SelectValue />
                  <ChevronDown :size="14" aria-hidden="true" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="server"><SelectItemText>Single Server</SelectItemText></SelectItem>
                  <SelectItem value="tag"><SelectItemText>Server Tag</SelectItemText></SelectItem>
                  <SelectItem value="all"><SelectItemText>All Servers</SelectItemText></SelectItem>
                </SelectContent>
              </Select>
            </Field>

            <Field v-if="ruleScope === 'server'" name="server">
              <FieldLabel>Server</FieldLabel>
              <Select v-model="ruleServerId">
                <SelectTrigger aria-label="Target server">
                  <SelectValue placeholder="Choose server" />
                  <ChevronDown :size="14" aria-hidden="true" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="srv in servers ?? []" :key="srv.id" :value="srv.id">
                    <SelectItemText>{{ srv.name }}</SelectItemText>
                  </SelectItem>
                </SelectContent>
              </Select>
            </Field>

            <Field v-else-if="ruleScope === 'tag'" name="tag-filter">
              <FieldLabel>Tag Name</FieldLabel>
              <Input v-model="ruleTagFilter" placeholder="e.g. prod" required />
            </Field>
          </div>

          <div class="form-row-3">
            <Field name="metric">
              <FieldLabel>Metric</FieldLabel>
              <Select v-model="ruleMetric">
                <SelectTrigger aria-label="Metric">
                  <SelectValue />
                  <ChevronDown :size="14" aria-hidden="true" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="(label, key) in METRIC_LABELS" :key="key" :value="key">
                    <SelectItemText>{{ label }}</SelectItemText>
                  </SelectItem>
                </SelectContent>
              </Select>
            </Field>

            <Field name="operator">
              <FieldLabel>Operator</FieldLabel>
              <Select v-model="ruleOperator">
                <SelectTrigger aria-label="Operator">
                  <SelectValue />
                  <ChevronDown :size="14" aria-hidden="true" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="gt"><SelectItemText>&gt; Greater than</SelectItemText></SelectItem>
                  <SelectItem value="gte"><SelectItemText>&gt;= Greater or equal</SelectItemText></SelectItem>
                  <SelectItem value="lt"><SelectItemText>&lt; Less than</SelectItemText></SelectItem>
                  <SelectItem value="lte"><SelectItemText>&lt;= Less or equal</SelectItemText></SelectItem>
                </SelectContent>
              </Select>
            </Field>

            <Field name="threshold">
              <FieldLabel>Threshold</FieldLabel>
              <Input v-model="ruleThreshold" type="number" step="0.1" required />
            </Field>
          </div>

          <div class="form-row-3">
            <Field name="aggregation">
              <FieldLabel>Aggregation</FieldLabel>
              <Select v-model="ruleAggregation">
                <SelectTrigger aria-label="Aggregation">
                  <SelectValue />
                  <ChevronDown :size="14" aria-hidden="true" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="avg"><SelectItemText>Average</SelectItemText></SelectItem>
                  <SelectItem value="max"><SelectItemText>Maximum</SelectItemText></SelectItem>
                  <SelectItem value="min"><SelectItemText>Minimum</SelectItemText></SelectItem>
                </SelectContent>
              </Select>
            </Field>

            <Field name="duration">
              <FieldLabel>Duration (min)</FieldLabel>
              <Input v-model="ruleDuration" type="number" min="1" max="1440" required />
            </Field>

            <Field name="severity">
              <FieldLabel>Severity</FieldLabel>
              <Select v-model="ruleSeverity">
                <SelectTrigger aria-label="Severity">
                  <SelectValue />
                  <ChevronDown :size="14" aria-hidden="true" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="warning"><SelectItemText>Warning</SelectItemText></SelectItem>
                  <SelectItem value="critical"><SelectItemText>Critical</SelectItemText></SelectItem>
                </SelectContent>
              </Select>
            </Field>
          </div>

          <Field name="channel">
            <FieldLabel>Notification Channel</FieldLabel>
            <Select v-model="ruleChannelId">
              <SelectTrigger aria-label="Notification channel">
                <SelectValue />
                <ChevronDown :size="14" aria-hidden="true" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="inline"><SelectItemText>Inline target (Email / Webhook)</SelectItemText></SelectItem>
                <SelectItem v-for="ch in channels ?? []" :key="ch.id" :value="ch.id">
                  <SelectItemText>{{ ch.name }} ({{ ch.channel_type }})</SelectItemText>
                </SelectItem>
              </SelectContent>
            </Select>
          </Field>

          <div v-if="ruleChannelId === 'inline'" class="form-row-2">
            <Field name="notify-type">
              <FieldLabel>Delivery Type</FieldLabel>
              <Select v-model="ruleNotifyType">
                <SelectTrigger aria-label="Delivery type">
                  <SelectValue />
                  <ChevronDown :size="14" aria-hidden="true" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="EMAIL"><SelectItemText>Email</SelectItemText></SelectItem>
                  <SelectItem value="WEBHOOK"><SelectItemText>Webhook</SelectItemText></SelectItem>
                </SelectContent>
              </Select>
            </Field>

            <Field name="notify-target">
              <FieldLabel>{{ ruleNotifyType === 'WEBHOOK' ? 'Webhook URL' : 'Email Address' }}</FieldLabel>
              <Input
                v-model="ruleNotifyTarget"
                :type="ruleNotifyType === 'WEBHOOK' ? 'url' : 'email'"
                :placeholder="ruleNotifyType === 'WEBHOOK' ? 'https://hooks.example.com/alert' : 'ops@example.com'"
              />
            </Field>
          </div>

          <div class="dialog-actions">
            <DialogClose class="btn btn-ghost">Cancel</DialogClose>
            <Button type="submit" data-variant="solid" :pending="ruleSaving">
              {{ editingRuleId ? 'Save Rule' : 'Create Rule' }}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="channelDialogOpen">
      <DialogBackdrop />
      <DialogContent class="modal-form-dialog">
        <div class="drawer-head">
          <div>
            <DialogTitle>Add Notification Channel</DialogTitle>
            <DialogDescription class="muted">
              Webhooks are signed with HMAC-SHA256 and guarded against SSRF.
            </DialogDescription>
          </div>
          <DialogClose class="icon-close" aria-label="Close dialog">
            <X :size="16" aria-hidden="true" />
          </DialogClose>
        </div>

        <form class="form-stack" @submit.prevent="handleCreateChannel">
          <div v-if="channelError" class="banner-error" role="alert">{{ channelError }}</div>

          <Field name="ch-name">
            <FieldLabel>Channel Name</FieldLabel>
            <Input v-model="channelName" placeholder="e.g. Ops PagerDuty Webhook" required />
          </Field>

          <Field name="ch-type">
            <FieldLabel>Channel Type</FieldLabel>
            <Select v-model="channelType">
              <SelectTrigger aria-label="Channel type">
                <SelectValue />
                <ChevronDown :size="14" aria-hidden="true" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="(meta, key) in CHANNEL_META" :key="key" :value="key">
                  <SelectItemText>{{ meta.label }}</SelectItemText>
                </SelectItem>
              </SelectContent>
            </Select>
          </Field>

          <Field name="ch-target">
            <FieldLabel>{{ activeChannelMeta.targetLabel }}</FieldLabel>
            <Input
              v-model="channelTarget"
              :type="channelType === 'EMAIL' ? 'email' : channelType === 'TELEGRAM' ? 'text' : 'url'"
              :placeholder="activeChannelMeta.targetPlaceholder"
              :required="channelType !== 'PAGERDUTY' && channelType !== 'OPSGENIE'"
            />
            <FieldDescription v-if="channelType !== 'EMAIL' && channelType !== 'TELEGRAM'">
              Public HTTP/HTTPS endpoint required. Private, loopback, and metadata IP ranges are blocked.
            </FieldDescription>
          </Field>

          <Field v-if="activeChannelMeta.secretLabel" name="ch-secret">
            <FieldLabel>{{ activeChannelMeta.secretLabel }}</FieldLabel>
            <Input
              v-model="channelSecret"
              type="password"
              autocomplete="off"
              :required="Boolean(activeChannelMeta.secretRequired)"
            />
            <FieldDescription>Stored write-only on the server and never returned in API responses.</FieldDescription>
          </Field>

          <label class="switch-row">
            <span>Set as default channel</span>
            <Switch :checked="channelDefault" @checked-change="(v: boolean) => (channelDefault = v)">
              <SwitchThumb />
            </Switch>
          </label>

          <div class="dialog-actions">
            <DialogClose class="btn btn-ghost">Cancel</DialogClose>
            <Button type="submit" data-variant="solid" :pending="channelSaving">Create Channel</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="silenceDialogOpen">
      <DialogBackdrop />
      <DialogContent class="modal-form-dialog">
        <div class="drawer-head">
          <div>
            <DialogTitle>Create Alert Silence</DialogTitle>
            <DialogDescription class="muted">
              Temporarily suppress notifications for a server, rule, or the whole workspace.
            </DialogDescription>
          </div>
          <DialogClose class="icon-close" aria-label="Close dialog">
            <X :size="16" aria-hidden="true" />
          </DialogClose>
        </div>

        <form class="form-stack" @submit.prevent="handleCreateSilence">
          <div v-if="silenceError" class="banner-error" role="alert">{{ silenceError }}</div>

          <Field name="sil-server">
            <FieldLabel>Server Scope</FieldLabel>
            <Select v-model="silenceServerId">
              <SelectTrigger aria-label="Silence server scope">
                <SelectValue />
                <ChevronDown :size="14" aria-hidden="true" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all"><SelectItemText>All servers</SelectItemText></SelectItem>
                <SelectItem v-for="srv in servers ?? []" :key="srv.id" :value="srv.id">
                  <SelectItemText>{{ srv.name }}</SelectItemText>
                </SelectItem>
              </SelectContent>
            </Select>
          </Field>

          <Field name="sil-duration">
            <FieldLabel>Duration</FieldLabel>
            <Select v-model="silenceMinutes">
              <SelectTrigger aria-label="Silence duration">
                <SelectValue />
                <ChevronDown :size="14" aria-hidden="true" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="30"><SelectItemText>30 minutes</SelectItemText></SelectItem>
                <SelectItem value="60"><SelectItemText>1 hour</SelectItemText></SelectItem>
                <SelectItem value="240"><SelectItemText>4 hours</SelectItemText></SelectItem>
                <SelectItem value="1440"><SelectItemText>24 hours</SelectItemText></SelectItem>
                <SelectItem value="10080"><SelectItemText>7 days</SelectItemText></SelectItem>
              </SelectContent>
            </Select>
          </Field>

          <Field name="sil-reason">
            <FieldLabel>Reason</FieldLabel>
            <Input v-model="silenceReason" placeholder="e.g. Database kernel upgrade" required />
          </Field>

          <div class="dialog-actions">
            <DialogClose class="btn btn-ghost">Cancel</DialogClose>
            <Button type="submit" data-variant="solid" :pending="silenceSaving">Create Silence</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>

    <AlertDialog v-model:open="deleteDialogOpen">
      <AlertDialogBackdrop />
      <AlertDialogContent class="confirm-dialog">
        <AlertDialogTitle>Delete {{ deleteTarget?.label }}?</AlertDialogTitle>
        <AlertDialogDescription class="muted">
          This action cannot be undone.
        </AlertDialogDescription>
        <div class="dialog-actions">
          <AlertDialogClose class="btn btn-ghost">Cancel</AlertDialogClose>
          <Button type="button" data-variant="danger" :pending="deletingItem" @click="confirmDelete()">
            Delete
          </Button>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  </section>
</template>

<style scoped>
.alerts-page {
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

.secret-banner {
  padding: 14px 16px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  border-color: var(--accent);
  background: var(--accent-soft);
}

.secret-val {
  display: inline-block;
  margin-top: 6px;
  font-size: 0.82rem;
  color: var(--accent);
}

.secret-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.tab-panel {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.filter-bar,
.sub-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.filter-bar {
  justify-content: flex-start;
}

.table-wrap {
  overflow-x: auto;
}

.empty-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  text-align: center;
  color: var(--ink-muted);
}

.ok-icon {
  color: var(--accent);
}

.muted {
  color: var(--ink-muted);
  font-size: 0.84rem;
  margin: 0;
}

.link-btn {
  border: none;
  background: transparent;
  color: var(--ink);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
  padding: 0;
  text-align: left;
}

.link-btn:hover {
  color: var(--accent);
  text-decoration: underline;
}

.server-link {
  color: var(--ink);
  text-decoration: none;
}

.server-link:hover {
  color: var(--accent);
}

.comment-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 8px;
  font-size: 0.75rem;
  color: var(--ink-muted);
}

.scope-tag {
  margin-left: 8px;
  font-size: 0.72rem;
  text-transform: uppercase;
  color: var(--ink-muted);
}

.target-code {
  font-size: 0.8rem;
  color: var(--ink-muted);
}

.actions-cell {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  width: 100%;
}

.inc-drawer {
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

.inc-badges,
.inc-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.silence-bar {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.silence-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-label {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-muted);
}

.comments-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.comment-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.comment-item {
  padding: 10px 12px;
  border-radius: var(--radius-md);
  background: var(--surface-raised);
  border: 1px solid var(--border);
}

.comment-meta {
  display: flex;
  justify-content: space-between;
  font-size: 0.8rem;
  margin-bottom: 4px;
}

.comment-item p {
  margin: 0;
  font-size: 0.875rem;
}

.comment-form,
.form-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.modal-form-dialog {
  width: min(620px, calc(100vw - 32px));
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-row-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.form-row-3 {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
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

@media (max-width: 640px) {
  .form-row-2,
  .form-row-3 {
    grid-template-columns: 1fr;
  }
}
</style>
