<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  Building2,
  Check,
  ChevronDown,
  Copy,
  FileClock,
  KeyRound,
  LogOut,
  Plus,
  RefreshCw,
  RotateCw,
  Shield,
  Trash2,
  UserPlus,
  Users,
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
import { Tabs, TabsList, TabsPanel, TabsTab } from '@ui-sdk/vue/tabs'
import { toast } from '@ui-sdk/vue/toast'
import {
  api,
  extractApiError,
  unwrapResults,
  type AgentKeyRecord,
  type AuditLogRecord,
  type CompanyInviteRecord,
  type CompanyMemberRecord,
  type CompanyRecord,
  type EnrollmentTokenRecord,
  type ServerRecord,
} from '../api/client'
import { useAuthStore } from '../stores/auth'
import { formatDateTime, formatRelativeTime } from '../utils/format'

const ALL_TABS = ['company', 'members', 'keys', 'audit', 'security'] as const
type SettingsTab = (typeof ALL_TABS)[number]

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const queryClient = useQueryClient()

const isOwner = computed(() => auth.user?.role === 'owner' || Boolean(auth.user?.is_superuser))

const allowedTabs = computed<SettingsTab[]>(() =>
  auth.isAdmin ? ['company', 'members', 'keys', 'audit', 'security'] : ['company', 'security'],
)

const requestedTab = route.query.tab as SettingsTab
const activeTab = ref<string | null>(
  allowedTabs.value.includes(requestedTab) ? requestedTab : 'company',
)

watch(activeTab, (next) => {
  if (next && allowedTabs.value.includes(next as SettingsTab)) {
    router.replace({ query: { ...route.query, tab: next } })
  }
})

const { data: companies, isPending: companyPending } = useQuery<CompanyRecord[]>({
  queryKey: ['companies'],
  queryFn: async () => unwrapResults<CompanyRecord>((await api.get('/api/accounts/companies/')).data),
})

const currentCompany = computed<CompanyRecord | null>(() => {
  const list = companies.value ?? []
  if (!list.length) return null
  if (auth.user?.company_id) {
    return list.find((c) => c.id === auth.user?.company_id) ?? list[0]
  }
  return list[0]
})

const companyName = ref('')
const retentionDays = ref('14')
const savingCompany = ref(false)
const companyError = ref('')

watch(
  currentCompany,
  (company) => {
    if (company) {
      companyName.value = company.name
      retentionDays.value = String(company.retention_days ?? 14)
    }
  },
  { immediate: true },
)

async function handleSaveCompany() {
  if (!currentCompany.value || !auth.isAdmin) return
  companyError.value = ''
  savingCompany.value = true
  try {
    const days = Math.max(1, Math.min(3650, Number.parseInt(retentionDays.value, 10) || 14))
    const resp = await api.patch<CompanyRecord>(`/api/accounts/companies/${currentCompany.value.id}/`, {
      name: companyName.value.trim(),
      retention_days: days,
    })
    if (auth.user && resp.data?.name) {
      auth.user = { ...auth.user, company_name: resp.data.name }
    }
    queryClient.invalidateQueries({ queryKey: ['companies'] })
    toast.success('Workspace settings saved')
  } catch (err) {
    companyError.value = extractApiError(err, 'Could not update workspace settings.')
  } finally {
    savingCompany.value = false
  }
}

const { data: members, isPending: membersPending } = useQuery<CompanyMemberRecord[]>({
  queryKey: ['company-members'],
  enabled: computed(() => auth.isAdmin),
  queryFn: async () => unwrapResults<CompanyMemberRecord>((await api.get('/api/accounts/members/')).data),
})

const { data: invites, isPending: invitesPending } = useQuery<CompanyInviteRecord[]>({
  queryKey: ['company-invites'],
  enabled: computed(() => auth.isAdmin),
  queryFn: async () => unwrapResults<CompanyInviteRecord>((await api.get('/api/accounts/invites/')).data),
})

const { data: servers } = useQuery<ServerRecord[]>({
  queryKey: ['servers'],
  enabled: computed(() => auth.isAdmin),
  queryFn: async () => unwrapResults<ServerRecord>((await api.get('/api/monitoring/servers/')).data),
})

const { data: agentKeys, isPending: keysPending } = useQuery<AgentKeyRecord[]>({
  queryKey: ['agent-keys'],
  enabled: computed(() => auth.isAdmin),
  queryFn: async () => unwrapResults<AgentKeyRecord>((await api.get('/api/monitoring/agent-keys/')).data),
})

const { data: enrollmentTokens, isPending: tokensPending } = useQuery<EnrollmentTokenRecord[]>({
  queryKey: ['enrollment-tokens'],
  enabled: computed(() => auth.isAdmin),
  queryFn: async () =>
    unwrapResults<EnrollmentTokenRecord>((await api.get('/api/monitoring/enrollment-tokens/')).data),
})

const auditResourceFilter = ref<string | null>('all')
const {
  data: auditLogs,
  isPending: auditPending,
  refetch: refetchAudit,
} = useQuery<AuditLogRecord[]>({
  queryKey: computed(() => ['audit-logs', auditResourceFilter.value]),
  enabled: computed(() => auth.isAdmin),
  queryFn: async () => {
    const params: Record<string, string> = {}
    if (auditResourceFilter.value && auditResourceFilter.value !== 'all') {
      params.resource_type = auditResourceFilter.value
    }
    return unwrapResults<AuditLogRecord>((await api.get('/api/monitoring/audit-logs/', { params })).data)
  },
})

const serverNameById = computed(() => {
  const map: Record<string, string> = {}
  for (const s of servers.value ?? []) {
    map[s.id] = s.name
  }
  return map
})

async function handleMemberRoleChange(member: CompanyMemberRecord, nextRole: string | null) {
  if (!nextRole || nextRole === member.role) return
  try {
    await api.patch(`/api/accounts/members/${member.id}/`, { role: nextRole })
    queryClient.invalidateQueries({ queryKey: ['company-members'] })
    toast.success(`Updated ${member.username} to ${nextRole}`)
  } catch (err) {
    toast.error(extractApiError(err, 'Could not update member role.'))
    queryClient.invalidateQueries({ queryKey: ['company-members'] })
  }
}

async function handleMemberActiveChange(member: CompanyMemberRecord, checked: boolean) {
  try {
    await api.patch(`/api/accounts/members/${member.id}/`, { is_active: checked })
    queryClient.invalidateQueries({ queryKey: ['company-members'] })
    toast.success(checked ? `${member.username} reactivated` : `${member.username} deactivated`)
  } catch (err) {
    toast.error(extractApiError(err, 'Could not update member status.'))
    queryClient.invalidateQueries({ queryKey: ['company-members'] })
  }
}

const inviteDialogOpen = ref(false)
const inviteEmail = ref('')
const inviteRole = ref<string | null>('member')
const inviteHours = ref('72')
const inviting = ref(false)
const inviteError = ref('')
const createdInviteUrl = ref('')
const createdInviteSent = ref(false)
const copiedValue = ref<string | null>(null)

function openInviteDialog() {
  inviteEmail.value = ''
  inviteRole.value = 'member'
  inviteHours.value = '72'
  inviteError.value = ''
  createdInviteUrl.value = ''
  createdInviteSent.value = false
  inviteDialogOpen.value = true
}

async function handleCreateInvite() {
  inviteError.value = ''
  inviting.value = true
  try {
    const resp = await api.post<{ invite_url: string; email_sent: boolean }>('/api/accounts/invites/', {
      email: inviteEmail.value.trim(),
      role: inviteRole.value || 'member',
      expires_in_hours: Math.max(1, Math.min(720, Number.parseInt(inviteHours.value, 10) || 72)),
    })
    createdInviteUrl.value = resp.data.invite_url
    createdInviteSent.value = Boolean(resp.data.email_sent)
    queryClient.invalidateQueries({ queryKey: ['company-invites'] })
    toast.success('Invitation created')
  } catch (err) {
    inviteError.value = extractApiError(err, 'Could not create invitation.')
  } finally {
    inviting.value = false
  }
}

const issueKeyDialogOpen = ref(false)
const issueKeyServerId = ref<string | null>(null)
const issuingKey = ref(false)
const issueKeyError = ref('')

const revealedCredentialDialogOpen = ref(false)
const revealedCredentialTitle = ref('')
const revealedCredentialValue = ref('')

function openIssueKeyDialog() {
  issueKeyServerId.value = (servers.value && servers.value[0]?.id) || null
  issueKeyError.value = ''
  issueKeyDialogOpen.value = true
}

async function handleIssueKey() {
  if (!issueKeyServerId.value) {
    issueKeyError.value = 'Select a server first.'
    return
  }
  issueKeyError.value = ''
  issuingKey.value = true
  try {
    const resp = await api.post<{ key: string; prefix: string }>('/api/monitoring/agent-keys/', {
      server: issueKeyServerId.value,
    })
    queryClient.invalidateQueries({ queryKey: ['agent-keys'] })
    issueKeyDialogOpen.value = false
    revealedCredentialTitle.value = `New Agent Key (${resp.data.prefix})`
    revealedCredentialValue.value = resp.data.key
    revealedCredentialDialogOpen.value = true
  } catch (err) {
    issueKeyError.value = extractApiError(err, 'Could not issue agent key.')
  } finally {
    issuingKey.value = false
  }
}

async function handleRotateKey(serverId: string) {
  try {
    const resp = await api.post<{ key: string; prefix: string }>('/api/monitoring/agent-keys/rotate/', {
      server: serverId,
    })
    queryClient.invalidateQueries({ queryKey: ['agent-keys'] })
    revealedCredentialTitle.value = `Rotated Agent Key (${resp.data.prefix})`
    revealedCredentialValue.value = resp.data.key
    revealedCredentialDialogOpen.value = true
    toast.success('Agent key rotated')
  } catch (err) {
    toast.error(extractApiError(err, 'Could not rotate agent key.'))
  }
}

const revokeTarget = ref<{ kind: 'invite' | 'agent-key' | 'enrollment-token'; id: string; label: string } | null>(null)
const revokeDialogOpen = ref(false)
const revoking = ref(false)

function requestRevoke(kind: 'invite' | 'agent-key' | 'enrollment-token', id: string, label: string) {
  revokeTarget.value = { kind, id, label }
  revokeDialogOpen.value = true
}

async function confirmRevoke() {
  if (!revokeTarget.value) return
  revoking.value = true
  try {
    const { kind, id } = revokeTarget.value
    if (kind === 'invite') {
      await api.delete(`/api/accounts/invites/${id}/`)
      queryClient.invalidateQueries({ queryKey: ['company-invites'] })
      toast.success('Invite revoked')
    } else if (kind === 'agent-key') {
      await api.post(`/api/monitoring/agent-keys/${id}/revoke/`)
      queryClient.invalidateQueries({ queryKey: ['agent-keys'] })
      toast.success('Agent key revoked')
    } else {
      await api.post(`/api/monitoring/enrollment-tokens/${id}/revoke/`)
      queryClient.invalidateQueries({ queryKey: ['enrollment-tokens'] })
      toast.success('Enrollment token revoked')
    }
    revokeDialogOpen.value = false
    revokeTarget.value = null
  } catch (err) {
    toast.error(extractApiError(err, 'Could not revoke item.'))
  } finally {
    revoking.value = false
  }
}

const logoutAllOpen = ref(false)
const loggingOutAll = ref(false)

async function confirmLogoutAll() {
  loggingOutAll.value = true
  try {
    await auth.logoutAll()
    toast.success('Signed out from all devices')
    logoutAllOpen.value = false
    router.push('/login')
  } finally {
    loggingOutAll.value = false
  }
}

async function copyText(val: string, key: string) {
  try {
    await navigator.clipboard.writeText(val)
    copiedValue.value = key
    toast.success('Copied to clipboard')
    setTimeout(() => {
      if (copiedValue.value === key) {
        copiedValue.value = null
      }
    }, 2000)
  } catch {
    toast.error('Clipboard access denied')
  }
}
</script>

<template>
  <section class="settings-page">
    <header class="page-header">
      <h1>Workspace Settings</h1>
      <span v-if="auth.user?.role" class="badge badge-neutral">{{ auth.user.role }}</span>
    </header>

    <Tabs v-model="activeTab">
      <TabsList aria-label="Settings sections">
        <TabsTab value="company">
          <Building2 :size="14" aria-hidden="true" />
          <span>Company</span>
        </TabsTab>
        <TabsTab v-if="auth.isAdmin" value="members">
          <Users :size="14" aria-hidden="true" />
          <span>Members &amp; Invites</span>
        </TabsTab>
        <TabsTab v-if="auth.isAdmin" value="keys">
          <KeyRound :size="14" aria-hidden="true" />
          <span>Keys &amp; Tokens</span>
        </TabsTab>
        <TabsTab v-if="auth.isAdmin" value="audit">
          <FileClock :size="14" aria-hidden="true" />
          <span>Audit Log</span>
        </TabsTab>
        <TabsTab value="security">
          <Shield :size="14" aria-hidden="true" />
          <span>Security</span>
        </TabsTab>
      </TabsList>

      <TabsPanel value="company" class="tab-panel">
        <div class="card panel-card">
          <h2>Company Profile</h2>
          <p class="muted">Configure your tenant workspace identity and telemetry retention policy.</p>

          <div v-if="companyPending" class="muted">Loading workspace details...</div>
          <form v-else class="form-stack narrow" @submit.prevent="handleSaveCompany">
            <div v-if="companyError" class="banner-error" role="alert">{{ companyError }}</div>

            <Field name="company-id">
              <FieldLabel>Tenant ID</FieldLabel>
              <Input :value="currentCompany?.id || ''" read-only />
            </Field>

            <Field name="company-name" :disabled="!auth.isAdmin">
              <FieldLabel>Workspace Name</FieldLabel>
              <Input v-model="companyName" required />
            </Field>

            <Field name="retention-days" :disabled="!auth.isAdmin">
              <FieldLabel>Metric Retention (days)</FieldLabel>
              <Input v-model="retentionDays" type="number" min="1" max="3650" inputmode="numeric" required />
              <FieldDescription>TimescaleDB retention window for raw and aggregated host metrics.</FieldDescription>
            </Field>

            <div v-if="auth.isAdmin" class="actions-left">
              <Button type="submit" data-variant="solid" :pending="savingCompany">Save Workspace</Button>
            </div>
          </form>
        </div>
      </TabsPanel>

      <TabsPanel v-if="auth.isAdmin" value="members" class="tab-panel">
        <div class="section-head">
          <div>
            <h2>Workspace Members</h2>
            <p class="muted">Manage roles and access for operators in {{ currentCompany?.name }}.</p>
          </div>
          <Button type="button" data-variant="solid" @click="openInviteDialog()">
            <UserPlus :size="15" aria-hidden="true" />
            <span>Invite Member</span>
          </Button>
        </div>

        <div v-if="membersPending" class="card empty-box">Loading members...</div>
        <div v-else class="card table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>User</th>
                <th>Email</th>
                <th>Role</th>
                <th>Active</th>
                <th class="num">Joined</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="m in members ?? []" :key="m.id">
                <td>
                  <strong>{{ m.username }}</strong>
                  <span v-if="m.id === auth.user?.id" class="badge badge-ok">You</span>
                </td>
                <td class="muted">{{ m.email || '--' }}</td>
                <td>
                  <Select
                    :model-value="m.role"
                    :disabled="m.role === 'owner' && !isOwner"
                    @update:model-value="(val) => handleMemberRoleChange(m, val)"
                  >
                    <SelectTrigger :aria-label="`Role for ${m.username}`">
                      <SelectValue />
                      <ChevronDown :size="14" aria-hidden="true" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem v-if="isOwner" value="owner"><SelectItemText>owner</SelectItemText></SelectItem>
                      <SelectItem value="admin"><SelectItemText>admin</SelectItemText></SelectItem>
                      <SelectItem value="member"><SelectItemText>member</SelectItemText></SelectItem>
                      <SelectItem value="viewer"><SelectItemText>viewer</SelectItemText></SelectItem>
                    </SelectContent>
                  </Select>
                </td>
                <td>
                  <Switch
                    :checked="m.is_active !== false"
                    :disabled="m.id === auth.user?.id || (m.role === 'owner' && !isOwner)"
                    :aria-label="`Active status for ${m.username}`"
                    @checked-change="(val: boolean) => handleMemberActiveChange(m, val)"
                  >
                    <SwitchThumb />
                  </Switch>
                </td>
                <td class="num tabular muted">{{ formatDateTime(m.date_joined) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="section-head">
          <h3>Invitations</h3>
        </div>
        <div v-if="invitesPending" class="card empty-box">Loading invitations...</div>
        <div v-else-if="!invites || invites.length === 0" class="card empty-box">No pending invitations.</div>
        <div v-else class="card table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>Email</th>
                <th>Role</th>
                <th>Status</th>
                <th class="num">Expires</th>
                <th class="num">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="inv in invites" :key="inv.id">
                <td>{{ inv.email }}</td>
                <td><span class="badge badge-neutral">{{ inv.role }}</span></td>
                <td>
                  <span
                    class="badge"
                    :class="inv.accepted_at ? 'badge-ok' : inv.revoked_at ? 'badge-offline' : 'badge-warning'"
                  >
                    {{ inv.accepted_at ? 'Accepted' : inv.revoked_at ? 'Revoked' : 'Pending' }}
                  </span>
                </td>
                <td class="num tabular muted">{{ formatDateTime(inv.expires_at) }}</td>
                <td class="num">
                  <Button
                    v-if="!inv.accepted_at && !inv.revoked_at"
                    type="button"
                    data-variant="danger"
                    @click="requestRevoke('invite', inv.id, `invite for ${inv.email}`)"
                  >
                    Revoke
                  </Button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </TabsPanel>

      <TabsPanel v-if="auth.isAdmin" value="keys" class="tab-panel">
        <div class="section-head">
          <div>
            <h2>Agent Keys</h2>
            <p class="muted">Per-server bearer credentials used by the SysRoar Rust agent.</p>
          </div>
          <Button type="button" data-variant="solid" @click="openIssueKeyDialog()">
            <Plus :size="15" aria-hidden="true" />
            <span>Issue Key</span>
          </Button>
        </div>

        <div v-if="keysPending" class="card empty-box">Loading agent keys...</div>
        <div v-else-if="!agentKeys || agentKeys.length === 0" class="card empty-box">
          No agent keys issued yet.
        </div>
        <div v-else class="card table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>Prefix</th>
                <th>Server</th>
                <th>Status</th>
                <th class="num">Last Used</th>
                <th class="num">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="k in agentKeys" :key="k.id">
                <td><code class="mono">{{ k.prefix }}</code></td>
                <td>{{ serverNameById[k.server] || k.server }}</td>
                <td>
                  <span class="badge" :class="k.is_active && !k.revoked_at ? 'badge-ok' : 'badge-offline'">
                    {{ k.is_active && !k.revoked_at ? 'Active' : 'Revoked' }}
                  </span>
                </td>
                <td class="num tabular muted">{{ formatRelativeTime(k.last_used_at) }}</td>
                <td class="num actions-cell">
                  <Button
                    v-if="k.is_active && !k.revoked_at"
                    type="button"
                    @click="handleRotateKey(k.server)"
                  >
                    <RotateCw :size="14" aria-hidden="true" />
                    <span>Rotate</span>
                  </Button>
                  <Button
                    v-if="k.is_active && !k.revoked_at"
                    type="button"
                    data-variant="danger"
                    @click="requestRevoke('agent-key', k.id, `agent key ${k.prefix}`)"
                  >
                    <Trash2 :size="14" aria-hidden="true" />
                    <span>Revoke</span>
                  </Button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="section-head">
          <h3>Enrollment Tokens</h3>
        </div>
        <div v-if="tokensPending" class="card empty-box">Loading enrollment tokens...</div>
        <div v-else-if="!enrollmentTokens || enrollmentTokens.length === 0" class="card empty-box">
          No enrollment tokens generated yet.
        </div>
        <div v-else class="card table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>Label</th>
                <th>Prefix</th>
                <th class="num">Uses</th>
                <th>Status</th>
                <th class="num">Expires</th>
                <th class="num">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="tk in enrollmentTokens" :key="tk.id">
                <td><strong>{{ tk.name }}</strong></td>
                <td><code class="mono">{{ tk.prefix }}</code></td>
                <td class="num tabular">{{ tk.uses_count }} / {{ tk.max_uses ?? 'unlimited' }}</td>
                <td>
                  <span class="badge" :class="tk.revoked_at ? 'badge-offline' : 'badge-ok'">
                    {{ tk.revoked_at ? 'Revoked' : 'Active' }}
                  </span>
                </td>
                <td class="num tabular muted">{{ formatDateTime(tk.expires_at) }}</td>
                <td class="num">
                  <Button
                    v-if="!tk.revoked_at"
                    type="button"
                    data-variant="danger"
                    @click="requestRevoke('enrollment-token', tk.id, `enrollment token ${tk.name}`)"
                  >
                    Revoke
                  </Button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </TabsPanel>

      <TabsPanel v-if="auth.isAdmin" value="audit" class="tab-panel">
        <div class="section-head">
          <div class="filter-inline">
            <Select v-model="auditResourceFilter">
              <SelectTrigger aria-label="Filter audit logs by resource">
                <SelectValue placeholder="All resources" />
                <ChevronDown :size="14" aria-hidden="true" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all"><SelectItemText>All resources</SelectItemText></SelectItem>
                <SelectItem value="server"><SelectItemText>Servers</SelectItemText></SelectItem>
                <SelectItem value="alert_rule"><SelectItemText>Alert Rules</SelectItemText></SelectItem>
                <SelectItem value="incident"><SelectItemText>Incidents</SelectItemText></SelectItem>
                <SelectItem value="agent_key"><SelectItemText>Agent Keys</SelectItemText></SelectItem>
                <SelectItem value="company_invite"><SelectItemText>Invites</SelectItemText></SelectItem>
                <SelectItem value="user"><SelectItemText>Members</SelectItemText></SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button type="button" data-variant="ghost" @click="refetchAudit()">
            <RefreshCw :size="14" aria-hidden="true" />
            <span>Refresh</span>
          </Button>
        </div>

        <div v-if="auditPending" class="card empty-box">Loading audit trail...</div>
        <div v-else-if="!auditLogs || auditLogs.length === 0" class="card empty-box">
          No audit events recorded yet.
        </div>
        <div v-else class="card table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Resource</th>
                <th>IP</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="entry in auditLogs" :key="entry.id">
                <td class="tabular muted">{{ formatDateTime(entry.created_at) }}</td>
                <td>{{ entry.actor_username || 'system' }}</td>
                <td><code class="mono">{{ entry.action }}</code></td>
                <td class="muted">{{ entry.resource_type }} ({{ entry.resource_id?.slice(0, 8) || '--' }})</td>
                <td class="mono muted">{{ entry.ip_address || '--' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </TabsPanel>

      <TabsPanel value="security" class="tab-panel">
        <div class="card panel-card">
          <h2>Session Security</h2>
          <p class="muted">
            Signed in as <strong>{{ auth.user?.username }}</strong> ({{ auth.user?.email || 'no email' }})
            with HttpOnly cookie session protection.
          </p>

          <div class="danger-zone">
            <div>
              <strong>Sign out everywhere</strong>
              <p class="muted">
                Rotates your session epoch and immediately revokes all active browser sessions and WebSocket tickets.
              </p>
            </div>
            <Button type="button" data-variant="danger" @click="logoutAllOpen = true">
              <LogOut :size="15" aria-hidden="true" />
              <span>Sign Out Everywhere</span>
            </Button>
          </div>
        </div>
      </TabsPanel>
    </Tabs>

    <Dialog v-model:open="inviteDialogOpen">
      <DialogBackdrop />
      <DialogContent class="modal-dialog">
        <div class="drawer-head">
          <div>
            <DialogTitle>Invite Team Member</DialogTitle>
            <DialogDescription class="muted">
              Create an invitation link scoped to {{ currentCompany?.name }}.
            </DialogDescription>
          </div>
          <DialogClose class="icon-close" aria-label="Close dialog">
            <X :size="16" aria-hidden="true" />
          </DialogClose>
        </div>

        <div v-if="createdInviteUrl" class="invite-result">
          <p v-if="createdInviteSent" class="muted">
            Invitation email dispatched. You can also share this direct link:
          </p>
          <p v-else class="muted">
            SMTP is not configured on this instance. Copy and share this one-time invitation link directly:
          </p>
          <div class="copy-box">
            <code class="copy-code">{{ createdInviteUrl }}</code>
            <Button type="button" data-variant="solid" @click="copyText(createdInviteUrl, 'invite')">
              <Check v-if="copiedValue === 'invite'" :size="14" aria-hidden="true" />
              <Copy v-else :size="14" aria-hidden="true" />
              <span>{{ copiedValue === 'invite' ? 'Copied' : 'Copy Link' }}</span>
            </Button>
          </div>
          <div class="dialog-actions">
            <DialogClose class="btn">Done</DialogClose>
          </div>
        </div>

        <form v-else class="form-stack" @submit.prevent="handleCreateInvite">
          <div v-if="inviteError" class="banner-error" role="alert">{{ inviteError }}</div>

          <Field name="invite-email">
            <FieldLabel>Email Address</FieldLabel>
            <Input v-model="inviteEmail" type="email" placeholder="teammate@company.com" required />
          </Field>

          <Field name="invite-role">
            <FieldLabel>Role</FieldLabel>
            <Select v-model="inviteRole">
              <SelectTrigger aria-label="Invite role">
                <SelectValue />
                <ChevronDown :size="14" aria-hidden="true" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-if="isOwner" value="owner"><SelectItemText>Owner</SelectItemText></SelectItem>
                <SelectItem value="admin"><SelectItemText>Admin</SelectItemText></SelectItem>
                <SelectItem value="member"><SelectItemText>Member</SelectItemText></SelectItem>
                <SelectItem value="viewer"><SelectItemText>Viewer (Read-only)</SelectItemText></SelectItem>
              </SelectContent>
            </Select>
          </Field>

          <Field name="invite-hours">
            <FieldLabel>Expires in (hours)</FieldLabel>
            <Input v-model="inviteHours" type="number" min="1" max="720" inputmode="numeric" />
          </Field>

          <div class="dialog-actions">
            <DialogClose class="btn btn-ghost">Cancel</DialogClose>
            <Button type="submit" data-variant="solid" :pending="inviting">Create Invitation</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="issueKeyDialogOpen">
      <DialogBackdrop />
      <DialogContent class="modal-dialog">
        <div class="drawer-head">
          <div>
            <DialogTitle>Issue Agent Key</DialogTitle>
            <DialogDescription class="muted">
              Generate a dedicated bearer key scoped to a single server.
            </DialogDescription>
          </div>
          <DialogClose class="icon-close" aria-label="Close dialog">
            <X :size="16" aria-hidden="true" />
          </DialogClose>
        </div>

        <form class="form-stack" @submit.prevent="handleIssueKey">
          <div v-if="issueKeyError" class="banner-error" role="alert">{{ issueKeyError }}</div>

          <Field name="key-server">
            <FieldLabel>Server</FieldLabel>
            <Select v-model="issueKeyServerId">
              <SelectTrigger aria-label="Select server for key">
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

          <div class="dialog-actions">
            <DialogClose class="btn btn-ghost">Cancel</DialogClose>
            <Button type="submit" data-variant="solid" :pending="issuingKey">Issue Key</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="revealedCredentialDialogOpen">
      <DialogBackdrop />
      <DialogContent class="modal-dialog">
        <div class="drawer-head">
          <div>
            <DialogTitle>{{ revealedCredentialTitle }}</DialogTitle>
            <DialogDescription class="muted">
              Copy this credential now. SysRoar only stores a salted hash and cannot display it again.
            </DialogDescription>
          </div>
          <DialogClose class="icon-close" aria-label="Close dialog">
            <X :size="16" aria-hidden="true" />
          </DialogClose>
        </div>

        <div class="copy-box">
          <code class="copy-code">{{ revealedCredentialValue }}</code>
          <Button type="button" data-variant="solid" @click="copyText(revealedCredentialValue, 'cred')">
            <Check v-if="copiedValue === 'cred'" :size="14" aria-hidden="true" />
            <Copy v-else :size="14" aria-hidden="true" />
            <span>{{ copiedValue === 'cred' ? 'Copied' : 'Copy Key' }}</span>
          </Button>
        </div>

        <div class="dialog-actions">
          <DialogClose class="btn">I Saved It</DialogClose>
        </div>
      </DialogContent>
    </Dialog>

    <AlertDialog v-model:open="revokeDialogOpen">
      <AlertDialogBackdrop />
      <AlertDialogContent class="confirm-dialog">
        <AlertDialogTitle>Revoke {{ revokeTarget?.label }}?</AlertDialogTitle>
        <AlertDialogDescription class="muted">
          This credential or invitation will stop working immediately.
        </AlertDialogDescription>
        <div class="dialog-actions">
          <AlertDialogClose class="btn btn-ghost">Cancel</AlertDialogClose>
          <Button type="button" data-variant="danger" :pending="revoking" @click="confirmRevoke()">
            Revoke
          </Button>
        </div>
      </AlertDialogContent>
    </AlertDialog>

    <AlertDialog v-model:open="logoutAllOpen">
      <AlertDialogBackdrop />
      <AlertDialogContent class="confirm-dialog">
        <AlertDialogTitle>Sign out from all devices?</AlertDialogTitle>
        <AlertDialogDescription class="muted">
          Every browser session and live WebSocket connection for your account will be invalidated immediately.
        </AlertDialogDescription>
        <div class="dialog-actions">
          <AlertDialogClose class="btn btn-ghost">Cancel</AlertDialogClose>
          <Button type="button" data-variant="danger" :pending="loggingOutAll" @click="confirmLogoutAll()">
            Sign Out Everywhere
          </Button>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  </section>
</template>

<style scoped>
.settings-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.page-header h1 {
  font-size: 1.5rem;
}

.tab-panel {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-card {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.section-head h2,
.section-head h3,
.panel-card h2 {
  font-size: 1.05rem;
}

.muted {
  color: var(--ink-muted);
  font-size: 0.84rem;
  margin: 0;
}

.form-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.narrow {
  max-width: 480px;
}

.actions-left {
  display: flex;
  gap: 10px;
}

.table-wrap {
  overflow-x: auto;
}

.empty-box {
  padding: 32px 20px;
  text-align: center;
  color: var(--ink-muted);
}

.actions-cell {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  width: 100%;
}

.danger-zone {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding: 16px;
  border-radius: var(--radius-md);
  border: 1px solid var(--danger);
  background: var(--danger-soft);
}

.modal-dialog,
.confirm-dialog {
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

.invite-result {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.copy-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-strong);
  background: var(--bg);
}

.copy-code {
  font-size: 0.8rem;
  color: var(--accent);
  overflow-x: auto;
  white-space: nowrap;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.filter-inline {
  display: flex;
  align-items: center;
  gap: 10px;
}
</style>
