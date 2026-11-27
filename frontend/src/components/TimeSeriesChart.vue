<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'
import { useThemeStore } from '../stores/theme'
import { formatPercent, formatRateBps } from '../utils/format'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent])

export interface ChartSeriesInput {
  name: string
  color: string
  data: Array<number | null>
  area?: boolean
  dashed?: boolean
}

const props = defineProps<{
  title: string
  subtitle?: string
  timestamps: string[]
  series: ChartSeriesInput[]
  unit: 'percent' | 'bytes_rate' | 'number'
  yMax?: number
  height?: string
}>()

const theme = useThemeStore()

const timeFmt = new Intl.DateTimeFormat('en', {
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

const shortTimeFmt = new Intl.DateTimeFormat('en', {
  hour: '2-digit',
  minute: '2-digit',
})

function formatValue(val: unknown): string {
  if (val === null || val === undefined || typeof val !== 'number' || Number.isNaN(val)) {
    return '--'
  }
  if (props.unit === 'percent') {
    return formatPercent(val)
  }
  if (props.unit === 'bytes_rate') {
    return formatRateBps(val)
  }
  return val.toFixed(2)
}

function formatAxisLabel(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) {
    return iso
  }
  return props.timestamps.length > 0 &&
    Date.parse(props.timestamps[props.timestamps.length - 1]) - Date.parse(props.timestamps[0]) > 86400000
    ? timeFmt.format(date)
    : shortTimeFmt.format(date)
}

const hasData = computed(() =>
  props.series.some((s) => s.data.some((v) => v !== null && v !== undefined && !Number.isNaN(v))),
)

const latestSummary = computed(() =>
  props.series.map((s) => {
    let last: number | null = null
    for (let i = s.data.length - 1; i >= 0; i -= 1) {
      if (s.data[i] !== null && s.data[i] !== undefined) {
        last = s.data[i]
        break
      }
    }
    return {
      name: s.name,
      color: s.color,
      formatted: formatValue(last),
    }
  }),
)

const option = computed(() => {
  const dark = theme.isDark
  const axisInk = dark ? '#94a3b8' : '#475569'
  const gridLine = dark ? 'rgba(148, 163, 184, 0.14)' : 'rgba(15, 23, 42, 0.1)'
  const tooltipBg = dark ? '#111827' : '#ffffff'
  const tooltipBorder = dark ? '#374762' : '#cbd5e1'
  const tooltipInk = dark ? '#f1f5f9' : '#0f172a'
  const showSlider = props.timestamps.length > 12

  return {
    animation: false,
    grid: {
      left: 52,
      right: 16,
      top: 18,
      bottom: showSlider ? 52 : 28,
    },
    tooltip: {
      trigger: 'axis',
      confine: true,
      backgroundColor: tooltipBg,
      borderColor: tooltipBorder,
      textStyle: { color: tooltipInk, fontSize: 12 },
      valueFormatter: (val: unknown) => formatValue(val),
    },
    legend: {
      show: props.series.length > 1,
      top: 0,
      right: 8,
      textStyle: { color: axisInk, fontSize: 11 },
      itemWidth: 12,
      itemHeight: 8,
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: props.timestamps.map(formatAxisLabel),
      axisLine: { lineStyle: { color: gridLine } },
      axisTick: { show: false },
      axisLabel: { color: axisInk, fontSize: 11, hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: props.yMax,
      splitLine: { lineStyle: { color: gridLine } },
      axisLabel: {
        color: axisInk,
        fontSize: 11,
        formatter: (value: number) => {
          if (props.unit === 'percent') return `${value}%`
          if (props.unit === 'bytes_rate') return formatRateBps(value)
          return `${value}`
        },
      },
    },
    dataZoom: showSlider
      ? [
          { type: 'inside', throttle: 50 },
          {
            type: 'slider',
            height: 16,
            bottom: 6,
            borderColor: gridLine,
            fillerColor: dark ? 'rgba(16, 185, 129, 0.18)' : 'rgba(5, 150, 105, 0.16)',
            handleStyle: { color: dark ? '#10b981' : '#059669' },
            textStyle: { color: axisInk, fontSize: 10 },
          },
        ]
      : [{ type: 'inside', throttle: 50 }],
    series: props.series.map((s) => ({
      name: s.name,
      type: 'line',
      showSymbol: false,
      connectNulls: true,
      smooth: 0.2,
      lineStyle: {
        color: s.color,
        width: 2,
        type: s.dashed ? 'dashed' : 'solid',
      },
      itemStyle: { color: s.color },
      areaStyle: s.area ? { color: `${s.color}20` } : undefined,
      data: s.data,
    })),
  }
})
</script>

<template>
  <article class="chart-card card">
    <header class="chart-head">
      <div>
        <h3>{{ title }}</h3>
        <p v-if="subtitle" class="chart-sub">{{ subtitle }}</p>
      </div>
      <div class="latest-strip tabular">
        <span v-for="item in latestSummary" :key="item.name" class="latest-item">
          <span class="swatch" :style="{ background: item.color }" aria-hidden="true" />
          <span class="latest-name">{{ item.name }}:</span>
          <strong>{{ item.formatted }}</strong>
        </span>
      </div>
    </header>

    <div v-if="hasData" class="chart-canvas" :style="{ height: height || '230px' }">
      <VChart class="echart" :option="option" autoresize />
    </div>
    <div v-else class="chart-empty" :style="{ height: height || '230px' }">
      No samples in this time window
    </div>
  </article>
</template>

<style scoped>
.chart-card {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.chart-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.chart-head h3 {
  font-size: 0.95rem;
  font-weight: 600;
}

.chart-sub {
  margin: 2px 0 0;
  font-size: 0.78rem;
  color: var(--ink-muted);
}

.latest-strip {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 0.8rem;
}

.latest-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.swatch {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.latest-name {
  color: var(--ink-muted);
}

.chart-canvas {
  width: 100%;
  min-width: 0;
  overflow: hidden;
}

.echart {
  width: 100%;
  height: 100%;
}

.chart-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  border: 1px dashed var(--border);
  color: var(--ink-muted);
  font-size: 0.84rem;
}
</style>
