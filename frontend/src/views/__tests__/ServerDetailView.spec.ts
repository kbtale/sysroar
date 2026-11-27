import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createMemoryHistory, createRouter } from 'vue-router'
import axios from 'axios'
import ServerDetailView from '../ServerDetailView.vue'
import { useAuthStore } from '../../stores/auth'

vi.mock('../../components/TimeSeriesChart.vue', () => ({
  default: {
    name: 'TimeSeriesChart',
    props: ['title', 'timestamps', 'series', 'unit'],
    template: '<div class="ts-chart-stub">{{ title }}:{{ timestamps.length }}</div>',
  },
}))

describe('ServerDetailView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('loads host inventory and metrics, switches range, and saves edits', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.user = {
      id: 'u-1',
      username: 'admin',
      email: 'admin@example.com',
      role: 'admin',
      company_id: 'c-1',
      company_name: 'Acme',
      is_superuser: false,
    }

    const getSpy = vi.spyOn(axios, 'get').mockImplementation(async (url: string, config?: { params?: Record<string, string> }) => {
      if (url === '/api/monitoring/servers/srv-1/') {
        return {
          data: {
            id: 'srv-1',
            name: 'prod-api-01',
            hostname: 'prod-api-01.internal',
            ip_address: '10.0.1.50',
            os_info: 'Ubuntu 24.04 LTS',
            kernel: '6.8.0-45-generic',
            cpu_model: 'AMD EPYC 7763',
            cpu_cores: 8,
            total_ram_bytes: 17179869184,
            agent_version: '0.1.0',
            is_active: true,
            telemetry_cadence: 15,
            log_level: 'INFO',
            tags: ['prod', 'api'],
            last_seen: new Date().toISOString(),
            status: 'online',
            alert_status: 'ok',
            sparkline: [],
            latest_details: {
              process_count: 92,
              cpu_iowait_percent: 1.4,
              disk_iops_read: 55,
              disk_iops_write: 20,
              top_processes: [{ pid: 101, name: 'postgres', cpu_percent: 12.5, mem_bytes: 268435456 }],
              docker_containers: [
                {
                  id: 'abc123456789',
                  name: 'web-proxy',
                  image: 'nginx:1.27',
                  state: 'running',
                  status: 'Up 2h',
                  cpu_percent: 2.1,
                  mem_bytes: 33554432,
                  mem_limit_bytes: 268435456,
                  mem_percent: 12.5,
                },
              ],
            },
            created_at: '2026-11-26T00:00:00Z',
          },
        } as never
      }
      if (url === '/api/telemetry/servers/srv-1/metrics/') {
        return {
          data: {
            server_id: 'srv-1',
            range: config?.params?.range || '1h',
            bucket: '1 minute',
            start: '2026-11-26T09:00:00Z',
            end: '2026-11-26T10:00:00Z',
            points: [
              {
                timestamp: '2026-11-26T09:55:00Z',
                cpu: 35.2,
                max_cpu: 42.1,
                ram: 64.0,
                max_ram: 65.0,
                swap: 2.0,
                disk: 48.0,
                disk_read_bps: 102400,
                disk_write_bps: 51200,
                net_rx_bps: 204800,
                net_tx_bps: 102400,
                load_1m: 1.4,
                uptime_seconds: 90000,
              },
            ],
          },
        } as never
      }
      throw new Error(`Unexpected GET ${url}`)
    })

    const patchSpy = vi.spyOn(axios, 'patch').mockResolvedValue({ data: {} } as never)

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div />' } },
        { path: '/servers/:id', component: ServerDetailView },
      ],
    })
    await router.push('/servers/srv-1')
    await router.isReady()

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = mount(ServerDetailView, {
      global: {
        plugins: [pinia, router, [VueQueryPlugin, { queryClient }]],
      },
      attachTo: document.body,
    })

    await flushPromises()
    expect(wrapper.text()).toContain('prod-api-01')
    expect(wrapper.text()).toContain('AMD EPYC 7763')
    expect(wrapper.text()).toContain('16.0 GiB')
    expect(wrapper.text()).toContain('1d 1h 0m')
    expect(wrapper.text()).toContain('CPU Usage:1')
    expect(wrapper.text()).toContain('Host Diagnostics')
    expect(wrapper.text()).toContain('postgres')

    const dockerTab = wrapper.findAll('[role="tab"]').find((t) => t.text().includes('Docker'))
    expect(dockerTab).toBeTruthy()
    await dockerTab!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('web-proxy')

    const range24h = wrapper.findAll('[data-slot="segmented-control-item"]').find((el) => el.text().trim() === '24h')
    expect(range24h).toBeTruthy()
    await range24h!.trigger('click')
    await flushPromises()
    expect(getSpy).toHaveBeenCalledWith('/api/telemetry/servers/srv-1/metrics/', { params: { range: '24h' } })

    const editBtn = wrapper.findAll('button').find((b) => b.text().trim() === 'Edit')
    expect(editBtn).toBeTruthy()
    await editBtn!.trigger('click')
    await flushPromises()

    const form = document.body.querySelector('form')
    expect(form).toBeTruthy()
    form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await flushPromises()

    expect(patchSpy).toHaveBeenCalledWith(
      '/api/monitoring/servers/srv-1/',
      expect.objectContaining({ name: 'prod-api-01', telemetry_cadence: 15 }),
    )

    wrapper.unmount()
  })
})
