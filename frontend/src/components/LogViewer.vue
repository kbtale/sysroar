<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { ChevronDown, Radio, RefreshCw, Search } from 'lucide-vue-next'
import { Button } from '@ui-sdk/vue/button'
import { Input } from '@ui-sdk/vue/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectItemText,
  SelectTrigger,
  SelectValue,
} from '@ui-sdk/vue/select'
import { api, extractApiError, unwrapResults, type ServerRecord } from '../api/client'
import { formatDateTime } from '../utils/format'

export interface LogEntryItem {
  timestamp: string
  level: string
  message: string
  server_id: string
  source: string
  labels: Record<string, string>
}

interface LogsQueryResponse {
  enabled: boolean
  backend: string
  entries: LogEntryItem[]
}

const props = defineProps<{
  serverId?: string
}>()

const rangeKey = ref<string | null>('1h')
const levelFilter = ref<string | null>('ALL')
const selectedServerId = ref<string | null>(props.serverId || 'all')
const searchText = ref('')
const liveTail = ref(false)
const liveLines = ref<LogEntryItem[]>([])
let wsSocket: WebSocket | null = null

const effectiveServerId = computed(() => {
  if (props.serverId) return props.serverId
  return selectedServerId.value && selectedServerId.value !== 'all' ? selectedServerId.value : ''
})

const { data: servers } = useQuery<ServerRecord[]>({
  queryKey: ['servers'],
  enabled: computed(() => !props.serverId),
  queryFn: async () => unwrapResults<ServerRecord>((await api.get('/api/monitoring/servers/')).data),
})

const {
  data: queryResp,
  isPending,
  isFetching,
  isError,
  error,
  refetch,
} = useQuery<LogsQueryResponse>({
  queryKey: computed(() => [
    'logs-query',
    effectiveServerId.value,
    rangeKey.value,
    levelFilter.value,
    searchText.value.trim(),
  ]),
  queryFn: async () => {
    const params: Record<string, string> = {
      range: rangeKey.value || '1h',
      limit: '200',
    }
    if (effectiveServerId.value) params.server_id = effectiveServerId.value
    if (levelFilter.value && levelFilter.value !== 'ALL') params.level = levelFilter.value
    if (searchText.value.trim()) params.q = searchText.value.trim()
    const resp = await api.get<LogsQueryResponse>('/api/logs/query/', { params })
    return resp.data
  },
})

const displayedEntries = computed<LogEntryItem[]>(() => {
  const base = queryResp.value?.entries ?? []
  if (liveLines.value.length === 0) return base
  return [...liveLines.value, ...base].slice(0, 300)
})

function stopLiveTail() {
  if (wsSocket) {
    try {
      wsSocket.close()
    } catch {
      wsSocket = null
    }
    wsSocket = null
  }
}

async function startLiveTail() {
  stopLiveTail()
  liveLines.value = []
  try {
    const resp = await api.post<{ ticket: string }>('/api/accounts/ws-ticket/')
    const ticket = resp.data?.ticket
    if (!ticket) {
      liveTail.value = false
      return
    }
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const params = new URLSearchParams({ ticket })
    if (effectiveServerId.value) params.set('server_id', effectiveServerId.value)
    if (levelFilter.value && levelFilter.value !== 'ALL') params.set('level', levelFilter.value)
    if (searchText.value.trim()) params.set('q', searchText.value.trim())
    const ws = new WebSocket(`${proto}//${window.location.host}/ws/logs/?${params.toString()}`)
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        if (msg?.type === 'log_lines' && Array.isArray(msg.entries)) {
          liveLines.value = [...msg.entries, ...liveLines.value].slice(0, 200)
        }
      } catch {
        return
      }
    }
    ws.onclose = () => {
      if (wsSocket === ws) {
        wsSocket = null
        liveTail.value = false
      }
    }
    wsSocket = ws
  } catch {
    liveTail.value = false
  }
}

function toggleLiveTail() {
  if (liveTail.value) {
    liveTail.value = false
    stopLiveTail()
  } else {
    liveTail.value = true
    startLiveTail()
  }
}

watch([effectiveServerId, levelFilter, searchText], () => {
  if (liveTail.value) {
    startLiveTail()
  }
})

onUnmounted(stopLiveTail)

function levelClass(level: string): string {
  const upper = (level || 'INFO').toUpperCase()
  if (upper === 'CRITICAL' || upper === 'ERROR') return 'badge-critical'
  if (upper === 'WARN' || upper === 'WARNING') return 'badge-warning'
  return 'badge-neutral'
}
</script>

<template>
  <div class="log-viewer">
    <div class="log-toolbar card">
      <div class="search-wrap">
        <Search :size="15" class="search-icon" aria-hidden="true" />
        <Input v-model="searchText" placeholder="Filter log messages..." aria-label="Search logs" />
      </div>

      <Select v-if="!serverId" v-model="selectedServerId">
        <SelectTrigger aria-label="Filter logs by server">
          <SelectValue placeholder="All servers" />
          <ChevronDown :size="14" aria-hidden="true" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all"><SelectItemText>All servers</SelectItemText></SelectItem>
          <SelectItem v-for="srv in servers ?? []" :key="srv.id" :value="srv.id">
            <SelectItemText>{{ srv.name }}</SelectItemText>
          </SelectItem>
        </SelectContent>
      </Select>

      <Select v-model="levelFilter">
        <SelectTrigger aria-label="Filter logs by level">
          <SelectValue placeholder="All levels" />
          <ChevronDown :size="14" aria-hidden="true" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="ALL"><SelectItemText>All levels</SelectItemText></SelectItem>
          <SelectItem value="CRITICAL"><SelectItemText>CRITICAL</SelectItemText></SelectItem>
          <SelectItem value="ERROR"><SelectItemText>ERROR</SelectItemText></SelectItem>
          <SelectItem value="WARN"><SelectItemText>WARN</SelectItemText></SelectItem>
          <SelectItem value="INFO"><SelectItemText>INFO</SelectItemText></SelectItem>
          <SelectItem value="DEBUG"><SelectItemText>DEBUG</SelectItemText></SelectItem>
        </SelectContent>
      </Select>

      <Select v-model="rangeKey">
        <SelectTrigger aria-label="Log time range">
          <SelectValue />
          <ChevronDown :size="14" aria-hidden="true" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="15m"><SelectItemText>Last 15m</SelectItemText></SelectItem>
          <SelectItem value="1h"><SelectItemText>Last 1h</SelectItemText></SelectItem>
          <SelectItem value="6h"><SelectItemText>Last 6h</SelectItemText></SelectItem>
          <SelectItem value="24h"><SelectItemText>Last 24h</SelectItemText></SelectItem>
          <SelectItem value="7d"><SelectItemText>Last 7d</SelectItemText></SelectItem>
        </SelectContent>
      </Select>

      <Button
        type="button"
        :data-variant="liveTail ? 'solid' : 'ghost'"
        @click="toggleLiveTail()"
      >
        <Radio :size="14" aria-hidden="true" />
        <span>{{ liveTail ? 'Live Tail On' : 'Live Tail' }}</span>
      </Button>

      <Button type="button" data-variant="ghost" :pending="isFetching && !isPending" @click="refetch()">
        <RefreshCw :size="14" aria-hidden="true" />
        <span>Refresh</span>
      </Button>
    </div>

    <div v-if="isError" class="banner-error" role="alert">
      {{ extractApiError(error, 'Failed to query logs.') }}
    </div>

    <div v-else-if="isPending" class="card empty-box">Querying logs...</div>
    <div v-else-if="displayedEntries.length === 0" class="card empty-box">
      <p>No log entries matched the current filters.</p>
    </div>

    <div v-else class="card log-table-wrap">
      <table class="log-table">
        <thead>
          <tr>
            <th>Timestamp</th>
            <th>Level</th>
            <th>Source</th>
            <th>Message</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, idx) in displayedEntries" :key="`${row.timestamp}-${idx}`">
            <td class="tabular muted ts-col">{{ formatDateTime(row.timestamp) }}</td>
            <td>
              <span class="badge" :class="levelClass(row.level)">{{ row.level }}</span>
            </td>
            <td class="mono muted">{{ row.source }}</td>
            <td class="mono msg-col">{{ row.message }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.log-viewer {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.log-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 12px 14px;
}

.search-wrap {
  position: relative;
  flex: 1 1 220px;
  min-width: 180px;
}

.search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--ink-muted);
  pointer-events: none;
}

.search-wrap :deep(input) {
  padding-left: 32px;
}

.log-table-wrap {
  overflow-x: auto;
}

.log-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
}

.log-table th,
.log-table td {
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}

.log-table th {
  font-size: 0.74rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-muted);
}

.ts-col {
  white-space: nowrap;
}

.msg-col {
  word-break: break-word;
  white-space: pre-wrap;
}

.mono {
  font-family: var(--font-mono);
}

.muted {
  color: var(--ink-muted);
}

.empty-box {
  padding: 32px 20px;
  text-align: center;
  color: var(--ink-muted);
}
</style>
