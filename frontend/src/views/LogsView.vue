<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { ScrollText } from 'lucide-vue-next'
import { api } from '../api/client'
import LogViewer from '../components/LogViewer.vue'

interface LogStatusResp {
  enabled: boolean
  backend: string
  healthy: boolean
}

const { data: logStatus, isPending } = useQuery<LogStatusResp>({
  queryKey: ['logs-status'],
  queryFn: async () => (await api.get<LogStatusResp>('/api/logs/status/')).data,
})
</script>

<template>
  <section class="logs-page">
    <header class="page-header">
      <div class="title-row">
        <h1>Logs Explorer</h1>
        <span v-if="logStatus?.enabled" class="badge badge-ok">{{ logStatus.backend }}</span>
        <span v-else-if="logStatus" class="badge badge-neutral">disabled</span>
      </div>
    </header>

    <div v-if="isPending" class="card empty-box">Checking log backend status...</div>
    <div v-else-if="!logStatus?.enabled" class="card empty-box">
      <ScrollText :size="28" aria-hidden="true" />
      <h2>Log storage is turned off</h2>
      <p class="muted">
        Start SysRoar with <code>docker compose --profile logs up</code> and set <code>LOG_BACKEND=loki</code>
        (or <code>--profile elk</code> with <code>LOG_BACKEND=elasticsearch</code>) to enable multi-tenant logs.
      </p>
    </div>
    <LogViewer v-else />
  </section>
</template>

<style scoped>
.logs-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.empty-box {
  padding: 40px 24px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.muted {
  color: var(--ink-muted);
  max-width: 560px;
  margin: 0;
}
</style>
