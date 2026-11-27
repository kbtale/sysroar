<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent])

const props = defineProps<{
  label: string
  data: number[]
  color: string
  height?: string
}>()

const option = computed(() => ({
  animation: false,
  grid: { left: 2, right: 2, top: 4, bottom: 2 },
  tooltip: {
    trigger: 'axis',
    confine: true,
    valueFormatter: (value: unknown) => (typeof value === 'number' ? `${value.toFixed(1)}%` : ''),
  },
  xAxis: {
    type: 'category',
    show: false,
    boundaryGap: false,
    data: props.data.map((_, idx) => idx),
  },
  yAxis: {
    type: 'value',
    show: false,
    min: 0,
    max: 100,
  },
  series: [
    {
      name: props.label,
      type: 'line',
      showSymbol: false,
      smooth: 0.25,
      lineStyle: { color: props.color, width: 1.75 },
      areaStyle: { color: `${props.color}22` },
      data: props.data,
    },
  ],
}))
</script>

<template>
  <div class="spark-wrap" :style="{ height: height || '52px' }">
    <VChart class="spark-chart" :option="option" autoresize />
  </div>
</template>

<style scoped>
.spark-wrap {
  width: 100%;
  min-width: 0;
}

.spark-chart {
  width: 100%;
  height: 100%;
}
</style>
