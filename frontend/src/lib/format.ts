const UNITS = ['B', 'KB', 'MB', 'GB', 'TB']

export function formatBytes(bytes: number): string {
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024
    unit++
  }
  const digits = unit === 0 || value >= 100 ? 0 : 1
  return `${value.toFixed(digits)} ${UNITS[unit]}`
}

export function formatNumber(n: number): string {
  return n.toLocaleString('en-US')
}

const relative = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })
const STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['second', 60],
  ['minute', 60],
  ['hour', 24],
  ['day', 30],
  ['month', 12],
  ['year', Infinity],
]

export function formatRelative(iso: string, now: Date = new Date()): string {
  let delta = (new Date(iso).getTime() - now.getTime()) / 1000
  for (const [unit, size] of STEPS) {
    if (Math.abs(delta) < size) {
      return relative.format(Math.round(delta), unit)
    }
    delta /= size
  }
  return relative.format(Math.round(delta), 'year')
}
