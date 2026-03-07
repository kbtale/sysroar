<script setup lang="ts">
import { computed } from 'vue'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Filler,
  Legend
} from 'chart.js'
import { Line } from 'vue-chartjs'

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Filler,
  Legend
)

const props = defineProps<{
  label: string
  data: number[]
  color: string
}>()

const chartData = computed(() => ({
  labels: props.data.map((_, i) => i),
  datasets: [
    {
      label: props.label,
      backgroundColor: props.color + '33', // 20% opacity
      borderColor: props.color,
      borderWidth: 2,
      pointRadius: 0,
      data: props.data,
      fill: true,
      tension: 0.4,
    }
  ]
}))

const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { display: false },
    tooltip: { enabled: true }
  },
  scales: {
    x: { display: false },
    y: {
      beginAtZero: true,
      max: 100,
      grid: { color: 'rgba(255, 255, 255, 0.05)' },
      ticks: { color: '#94a3b8', font: { size: 10 } }
    }
  },
  animation: {
    duration: 500,
  }
}
</script>

<template>
  <div class="chart-wrapper">
    <div class="chart-header">
      <span class="label">{{ label }}</span>
      <span class="value" :style="{ color: color }">
        {{ data.length > 0 ? Math.round(data[data.length - 1]) : 0 }}%
      </span>
    </div>
    <div class="chart-container">
      <Line :data="chartData" :options="chartOptions" />
    </div>
  </div>
</template>

<style scoped>
.chart-wrapper {
  background: rgba(15, 23, 42, 0.5);
  border-radius: 1rem;
  padding: 1.25rem;
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.label {
  color: #94a3b8;
  font-size: 0.875rem;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.value {
  font-size: 1.25rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.chart-container {
  height: 120px;
  position: relative;
}
</style>
