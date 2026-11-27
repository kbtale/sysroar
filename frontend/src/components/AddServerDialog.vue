<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { Check, CheckCircle2, Copy, Loader2, Plus, Server, Terminal, X } from 'lucide-vue-next'
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
import { Tabs, TabsList, TabsPanel, TabsTab } from '@ui-sdk/vue/tabs'
import { toast } from '@ui-sdk/vue/toast'
import { api, extractApiError, unwrapResults, type ServerRecord } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useTelemetryStore } from '../stores/telemetry'

const open = defineModel<boolean>('open', { default: false })

const auth = useAuthStore()
const telemetry = useTelemetryStore()
const queryClient = useQueryClient()

type WizardStep = 'configure' | 'install' | 'connected'

const step = ref<WizardStep>('configure')
const platformTab = ref<string | null>('linux')
const tokenLabel = ref('production-host')
const maxUses = ref('1')
const manualName = ref('')
const manualTags = ref('')
const submitting = ref(false)
const errorMessage = ref('')

const enrollmentToken = ref('')
const tokenPrefix = ref('')
const copiedTarget = ref<string | null>(null)
const baselineServerIds = ref<Set<string>>(new Set())
const connectedServer = ref<ServerRecord | null>(null)
const pollCount = ref(0)

let pollTimer: ReturnType<typeof setInterval> | null = null

const apiBaseUrl = computed(() => {
  if (typeof window === 'undefined') {
    return 'http://localhost:8000'
  }
  if (window.location.host === 'localhost:5173') {
    return 'http://localhost:8000'
  }
  return window.location.origin
})

const linuxCommand = computed(() => {
  const base = apiBaseUrl.value
  const tk = enrollmentToken.value
  return `curl -fsSL https://raw.githubusercontent.com/kbtale/sysroar/main/scripts/install.sh | sudo SYSROAR_API_BASE_URL="${base}" SYSROAR_ENROLLMENT_TOKEN="${tk}" sh`
})

const windowsCommand = computed(() => {
  const base = apiBaseUrl.value
  const tk = enrollmentToken.value
  return `$env:SYSROAR_API_BASE_URL="${base}"; $env:SYSROAR_ENROLLMENT_TOKEN="${tk}"; irm https://raw.githubusercontent.com/kbtale/sysroar/main/scripts/install.ps1 | iex`
})

const dockerCommand = computed(() => {
  const base = apiBaseUrl.value
  const tk = enrollmentToken.value
  return [
    `ENROLL=$(curl -fsSL -X POST "${base}/api/telemetry/enroll/" -H "Content-Type: application/json" -d "{\\"enrollment_token\\":\\"${tk}\\",\\"name\\":\\"$(hostname)\\"}")`,
    `docker run -d --name sysroar-agent --restart unless-stopped \\`,
    `  -e SYSROAR_API_BASE_URL="${base}" \\`,
    `  -e SYSROAR_SERVER_ID="$(echo "$ENROLL" | sed -n 's/.*"server_id":"\\([^"]*\\)".*/\\1/p')" \\`,
    `  -e SYSROAR_AGENT_KEY="$(echo "$ENROLL" | sed -n 's/.*"agent_key":"\\([^"]*\\)".*/\\1/p')" \\`,
    `  ghcr.io/kbtale/sysroar-agent:latest`,
  ].join('\n')
})

const openIngestSnippet = computed(() => {
  const base = apiBaseUrl.value
  return [
    `# OpenTelemetry Collector exporter`,
    `exporters:`,
    `  otlphttp/sysroar:`,
    `    metrics_endpoint: "${base}/api/telemetry/otlp/v1/metrics"`,
    `    headers:`,
    `      Authorization: "AgentKey <YOUR_AGENT_KEY>"`,
    ``,
    `# Prometheus remote_write`,
    `remote_write:`,
    `  - url: "${base}/api/telemetry/prometheus/remote-write"`,
    `    headers:`,
    `      Authorization: "AgentKey <YOUR_AGENT_KEY>"`,
  ].join('\n')
})

function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function resetWizard() {
  stopPolling()
  step.value = 'configure'
  platformTab.value = 'linux'
  tokenLabel.value = 'production-host'
  maxUses.value = '1'
  manualName.value = ''
  manualTags.value = ''
  errorMessage.value = ''
  enrollmentToken.value = ''
  tokenPrefix.value = ''
  copiedTarget.value = null
  connectedServer.value = null
  pollCount.value = 0
}

watch(open, (isOpen) => {
  if (!isOpen) {
    stopPolling()
  }
})

onUnmounted(() => {
  stopPolling()
})

async function checkForNewServer() {
  pollCount.value += 1
  try {
    const response = await api.get('/api/monitoring/servers/')
    const servers = unwrapResults<ServerRecord>(response.data)
    const found = servers.find((srv) => !baselineServerIds.value.has(srv.id))
    if (found) {
      connectedServer.value = found
      step.value = 'connected'
      stopPolling()
      queryClient.invalidateQueries({ queryKey: ['servers'] })
      toast.success(`${found.name} connected to your fleet`)
    }
  } catch {
    return
  }
}

watch(
  () => telemetry.sampleVersion,
  () => {
    if (open.value && step.value === 'install') {
      const sample = telemetry.latestSample
      if (sample && !baselineServerIds.value.has(sample.server_id)) {
        checkForNewServer()
      }
    }
  },
)

function startPolling() {
  stopPolling()
  pollTimer = setInterval(() => {
    checkForNewServer()
  }, 3000)
}

async function handleGenerateToken() {
  errorMessage.value = ''
  submitting.value = true
  try {
    const existingResp = await api.get('/api/monitoring/servers/')
    const existingList = unwrapResults<ServerRecord>(existingResp.data)
    baselineServerIds.value = new Set(existingList.map((s) => s.id))

    const parsedUses = Math.max(1, Math.min(1000, Number.parseInt(maxUses.value, 10) || 1))
    const resp = await api.post<{ token: string; prefix: string }>('/api/monitoring/enrollment-tokens/', {
      name: tokenLabel.value.trim() || 'host-enrollment',
      max_uses: parsedUses,
      expires_in_hours: 24,
    })
    enrollmentToken.value = resp.data.token
    tokenPrefix.value = resp.data.prefix
    step.value = 'install'
    startPolling()
  } catch (err) {
    errorMessage.value = extractApiError(err, 'Could not generate enrollment token.')
  } finally {
    submitting.value = false
  }
}

async function handleCreateManualServer() {
  if (!manualName.value.trim()) {
    errorMessage.value = 'Server name is required.'
    return
  }
  errorMessage.value = ''
  submitting.value = true
  try {
    const tags = manualTags.value
      .split(',')
      .map((t) => t.trim().toLowerCase())
      .filter(Boolean)
    const resp = await api.post<ServerRecord>('/api/monitoring/servers/', {
      name: manualName.value.trim(),
      tags,
    })
    connectedServer.value = resp.data
    step.value = 'connected'
    queryClient.invalidateQueries({ queryKey: ['servers'] })
    toast.success(`Server ${resp.data.name} created`)
  } catch (err) {
    errorMessage.value = extractApiError(err, 'Could not create server.')
  } finally {
    submitting.value = false
  }
}

async function copyText(text: string, target: string) {
  try {
    await navigator.clipboard.writeText(text)
    copiedTarget.value = target
    toast.success('Copied to clipboard')
    setTimeout(() => {
      if (copiedTarget.value === target) {
        copiedTarget.value = null
      }
    }, 2000)
  } catch {
    toast.error('Clipboard access denied')
  }
}

function handleOpenChange(nextOpen: boolean) {
  open.value = nextOpen
  if (!nextOpen) {
    resetWizard()
  }
}
</script>

<template>
  <Dialog :open="open" @open-change="handleOpenChange">
    <DialogBackdrop />
    <DialogContent class="wizard-dialog">
      <header class="wizard-head">
        <div>
          <DialogTitle class="wizard-title">Add Server</DialogTitle>
          <DialogDescription class="wizard-desc">
            <template v-if="step === 'configure' && auth.isAdmin">
              Generate a one-time enrollment token and install the Rust agent on your host.
            </template>
            <template v-else-if="step === 'configure'">
              Register a server entry in your workspace. Ask an Admin to issue an agent enrollment token.
            </template>
            <template v-else-if="step === 'install'">
              Run the command below on your target host. This dialog listens live for its first heartbeat.
            </template>
            <template v-else>
              Host enrolled and ready for live telemetry monitoring.
            </template>
          </DialogDescription>
        </div>
        <DialogClose class="icon-close" aria-label="Close dialog">
          <X :size="16" aria-hidden="true" />
        </DialogClose>
      </header>

      <div v-if="errorMessage" class="banner-error" role="alert">
        {{ errorMessage }}
      </div>

      <form v-if="step === 'configure' && auth.isAdmin" class="wizard-form" @submit.prevent="handleGenerateToken">
        <Field name="token-label">
          <FieldLabel>Enrollment label</FieldLabel>
          <Input v-model="tokenLabel" placeholder="e.g. prod-eu-web-01" required />
          <FieldDescription>Helps identify this enrollment token in the audit log.</FieldDescription>
        </Field>

        <Field name="max-uses">
          <FieldLabel>Max hosts allowed</FieldLabel>
          <Input v-model="maxUses" type="number" min="1" max="1000" inputmode="numeric" />
          <FieldDescription>Use 1 for a single host or higher for an autoscaling group.</FieldDescription>
        </Field>

        <div class="wizard-actions">
          <DialogClose class="btn btn-ghost">Cancel</DialogClose>
          <Button type="submit" data-variant="solid" :pending="submitting">
            <Plus :size="15" aria-hidden="true" />
            <span>Generate Enrollment Command</span>
          </Button>
        </div>
      </form>

      <form v-else-if="step === 'configure'" class="wizard-form" @submit.prevent="handleCreateManualServer">
        <Field name="server-name">
          <FieldLabel>Server name</FieldLabel>
          <Input v-model="manualName" placeholder="e.g. web-01" required />
        </Field>

        <Field name="server-tags">
          <FieldLabel>Tags (comma-separated)</FieldLabel>
          <Input v-model="manualTags" placeholder="prod, web, eu-west" />
        </Field>

        <div class="wizard-actions">
          <DialogClose class="btn btn-ghost">Cancel</DialogClose>
          <Button type="submit" data-variant="solid" :pending="submitting">
            <Server :size="15" aria-hidden="true" />
            <span>Create Server</span>
          </Button>
        </div>
      </form>

      <div v-else-if="step === 'install'" class="install-step">
        <div class="token-callout">
          <div class="token-meta">
            <span class="token-label">One-time enrollment token ({{ tokenPrefix }})</span>
            <span class="token-warn">Shown once. Expires in 24 hours.</span>
          </div>
          <div class="token-row">
            <code class="token-value">{{ enrollmentToken }}</code>
            <Button
              type="button"
              data-variant="ghost"
              aria-label="Copy enrollment token"
              @click="copyText(enrollmentToken, 'token')"
            >
              <Check v-if="copiedTarget === 'token'" :size="15" aria-hidden="true" />
              <Copy v-else :size="15" aria-hidden="true" />
              <span>{{ copiedTarget === 'token' ? 'Copied' : 'Copy' }}</span>
            </Button>
          </div>
        </div>

        <Tabs v-model="platformTab">
          <TabsList aria-label="Operating system install commands">
            <TabsTab value="linux">Linux</TabsTab>
            <TabsTab value="windows">Windows</TabsTab>
            <TabsTab value="docker">Docker</TabsTab>
            <TabsTab value="open">OTLP / Prom</TabsTab>
          </TabsList>

          <TabsPanel value="linux" class="cmd-panel">
            <div class="cmd-bar">
              <span class="cmd-hint">
                <Terminal :size="14" aria-hidden="true" />
                Bash / systemd host
              </span>
              <Button type="button" data-variant="ghost" @click="copyText(linuxCommand, 'linux')">
                <Check v-if="copiedTarget === 'linux'" :size="14" aria-hidden="true" />
                <Copy v-else :size="14" aria-hidden="true" />
                <span>{{ copiedTarget === 'linux' ? 'Copied' : 'Copy command' }}</span>
              </Button>
            </div>
            <pre class="code-block"><code>{{ linuxCommand }}</code></pre>
          </TabsPanel>

          <TabsPanel value="windows" class="cmd-panel">
            <div class="cmd-bar">
              <span class="cmd-hint">
                <Terminal :size="14" aria-hidden="true" />
                PowerShell 5.1+
              </span>
              <Button type="button" data-variant="ghost" @click="copyText(windowsCommand, 'windows')">
                <Check v-if="copiedTarget === 'windows'" :size="14" aria-hidden="true" />
                <Copy v-else :size="14" aria-hidden="true" />
                <span>{{ copiedTarget === 'windows' ? 'Copied' : 'Copy command' }}</span>
              </Button>
            </div>
            <pre class="code-block"><code>{{ windowsCommand }}</code></pre>
          </TabsPanel>

          <TabsPanel value="docker" class="cmd-panel">
            <div class="cmd-bar">
              <span class="cmd-hint">
                <Terminal :size="14" aria-hidden="true" />
                Docker container
              </span>
              <Button type="button" data-variant="ghost" @click="copyText(dockerCommand, 'docker')">
                <Check v-if="copiedTarget === 'docker'" :size="14" aria-hidden="true" />
                <Copy v-else :size="14" aria-hidden="true" />
                <span>{{ copiedTarget === 'docker' ? 'Copied' : 'Copy command' }}</span>
              </Button>
            </div>
            <pre class="code-block"><code>{{ dockerCommand }}</code></pre>
          </TabsPanel>

          <TabsPanel value="open" class="cmd-panel">
            <div class="cmd-bar">
              <span class="cmd-hint">
                <Terminal :size="14" aria-hidden="true" />
                OTLP/HTTP &amp; Prometheus remote_write
              </span>
              <Button type="button" data-variant="ghost" @click="copyText(openIngestSnippet, 'open')">
                <Check v-if="copiedTarget === 'open'" :size="14" aria-hidden="true" />
                <Copy v-else :size="14" aria-hidden="true" />
                <span>{{ copiedTarget === 'open' ? 'Copied' : 'Copy config' }}</span>
              </Button>
            </div>
            <pre class="code-block"><code>{{ openIngestSnippet }}</code></pre>
          </TabsPanel>
        </Tabs>

        <div class="heartbeat-wait" role="status" aria-live="polite">
          <Loader2 :size="16" class="spin" aria-hidden="true" />
          <span>Waiting for first heartbeat from the agent...</span>
        </div>

        <div class="wizard-actions">
          <Button type="button" data-variant="ghost" @click="checkForNewServer()">Check Now</Button>
          <DialogClose class="btn">Done</DialogClose>
        </div>
      </div>

      <div v-else class="connected-step">
        <div class="connected-banner">
          <CheckCircle2 :size="28" class="connected-icon" aria-hidden="true" />
          <div>
            <h3>Host Connected</h3>
            <p>
              <strong>{{ connectedServer?.name }}</strong>
              <span v-if="connectedServer?.ip_address"> ({{ connectedServer.ip_address }})</span>
              is registered and streaming telemetry.
            </p>
          </div>
        </div>

        <div class="wizard-actions">
          <Button type="button" data-variant="ghost" @click="resetWizard()">Add Another</Button>
          <router-link
            v-if="connectedServer"
            :to="`/servers/${connectedServer.id}`"
            class="btn btn-primary"
            @click="handleOpenChange(false)"
          >
            Inspect Server
          </router-link>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>

<style scoped>
.wizard-dialog {
  width: min(640px, calc(100vw - 32px));
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.wizard-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.wizard-title {
  font-size: 1.15rem;
  font-weight: 700;
}

.wizard-desc {
  margin: 4px 0 0;
  font-size: 0.85rem;
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

.icon-close:hover {
  background: var(--surface-hover);
  color: var(--ink);
}

.wizard-form,
.install-step,
.connected-step {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.token-callout {
  padding: 12px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-strong);
  background: var(--surface-raised);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.token-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.token-label {
  font-size: 0.78rem;
  font-weight: 600;
}

.token-warn {
  font-size: 0.74rem;
  color: var(--warning);
}

.token-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.token-value {
  font-size: 0.8rem;
  overflow-x: auto;
  white-space: nowrap;
  color: var(--accent);
}

.cmd-panel {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.cmd-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.cmd-hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.78rem;
  color: var(--ink-muted);
}

.heartbeat-wait {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  border: 1px solid var(--info-soft);
  background: var(--info-soft);
  color: var(--info);
  font-size: 0.84rem;
  font-weight: 500;
}

.spin {
  animation: spin 1.2s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.connected-banner {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 16px;
  border-radius: var(--radius-md);
  border: 1px solid var(--accent);
  background: var(--accent-soft);
}

.connected-icon {
  color: var(--accent);
  flex-shrink: 0;
}

.connected-banner h3 {
  font-size: 1rem;
  color: var(--ink);
}

.connected-banner p {
  margin: 4px 0 0;
  font-size: 0.875rem;
  color: var(--ink-muted);
}

.wizard-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 4px;
}
</style>
