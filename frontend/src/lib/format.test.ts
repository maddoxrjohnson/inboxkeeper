import { describe, expect, it } from 'vitest'
import { formatBytes, formatNumber, formatRelative } from './format'

describe('formatBytes', () => {
  it.each([
    [0, '0 B'],
    [512, '512 B'],
    [1536, '1.5 KB'],
    [5 * 1024 ** 2, '5.0 MB'],
    [250 * 1024 ** 3, '250 GB'],
  ])('%d -> %s', (input, expected) => {
    expect(formatBytes(input)).toBe(expected)
  })
})

describe('formatNumber', () => {
  it('adds thousands separators', () => {
    expect(formatNumber(1234567)).toBe('1,234,567')
  })
})

describe('formatRelative', () => {
  const now = new Date('2026-06-01T12:00:00Z')

  it.each([
    ['2026-06-01T11:59:30Z', '30 seconds ago'],
    ['2026-06-01T11:55:00Z', '5 minutes ago'],
    ['2026-06-01T09:00:00Z', '3 hours ago'],
    ['2026-05-31T12:00:00Z', 'yesterday'],
  ])('%s -> %s', (iso, expected) => {
    expect(formatRelative(iso, now)).toBe(expected)
  })
})
