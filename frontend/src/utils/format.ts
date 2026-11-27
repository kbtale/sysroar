export interface SparklinePoint {
  t: string
  cpu: number
  ram: number
}

const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto', style: 'short' })
const dateTimeFmt = new Intl.DateTimeFormat('en', {
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})
const numFmt1 = new Intl.NumberFormat('en', { maximumFractionDigits: 1, minimumFractionDigits: 1 })
const intFmt = new Intl.NumberFormat('en', { maximumFractionDigits: 0 })

export function formatRelativeTime(iso: string | null | undefined, nowMs = Date.now()): string {
  if (!iso) {
    return 'Never'
  }
  const ts = Date.parse(iso)
  if (Number.isNaN(ts)) {
    return 'Unknown'
  }
  const diffSec = Math.round((ts - nowMs) / 1000)
  const absSec = Math.abs(diffSec)
  if (absSec < 15) {
    return 'Just now'
  }
  if (absSec < 60) {
    return rtf.format(diffSec, 'second')
  }
  const diffMin = Math.round(diffSec / 60)
  if (Math.abs(diffMin) < 60) {
    return rtf.format(diffMin, 'minute')
  }
  const diffHr = Math.round(diffMin / 60)
  if (Math.abs(diffHr) < 24) {
    return rtf.format(diffHr, 'hour')
  }
  const diffDay = Math.round(diffHr / 24)
  return rtf.format(diffDay, 'day')
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) {
    return '--'
  }
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) {
    return '--'
  }
  return dateTimeFmt.format(date)
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '--'
  }
  return `${numFmt1.format(value)}%`
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes) || bytes < 0) {
    return '--'
  }
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let val = bytes
  let idx = 0
  while (val >= 1024 && idx < units.length - 1) {
    val /= 1024
    idx += 1
  }
  return idx === 0 ? `${intFmt.format(val)} ${units[idx]}` : `${numFmt1.format(val)} ${units[idx]}`
}

export function formatRateBps(bps: number | null | undefined): string {
  if (bps === null || bps === undefined || Number.isNaN(bps) || bps < 0) {
    return '--'
  }
  const units = ['B/s', 'KB/s', 'MB/s', 'GB/s']
  let val = bps
  let idx = 0
  while (val >= 1000 && idx < units.length - 1) {
    val /= 1000
    idx += 1
  }
  return idx === 0 ? `${intFmt.format(val)} ${units[idx]}` : `${numFmt1.format(val)} ${units[idx]}`
}

export function formatUptime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds) || seconds < 0) {
    return '--'
  }
  const total = Math.floor(seconds)
  const days = Math.floor(total / 86400)
  const hours = Math.floor((total % 86400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  if (days > 0) {
    return `${days}d ${hours}h ${minutes}m`
  }
  if (hours > 0) {
    return `${hours}h ${minutes}m`
  }
  return `${minutes}m`
}

export function parseSparkline(raw: unknown): SparklinePoint[] {
  if (!Array.isArray(raw)) {
    return []
  }
  const points: SparklinePoint[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') {
      continue
    }
    const rec = item as Record<string, unknown>
    const cpu = typeof rec.cpu === 'number' ? rec.cpu : Number(rec.cpu)
    const ram = typeof rec.ram === 'number' ? rec.ram : Number(rec.ram)
    const t = typeof rec.t === 'string' ? rec.t : ''
    if (!Number.isNaN(cpu) && !Number.isNaN(ram)) {
      points.push({ t, cpu, ram })
    }
  }
  return points
}
