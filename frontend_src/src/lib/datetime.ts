/**
 * Backend timestamps are UTC as "YYYY-MM-DD HH:MM:SS" (no timezone suffix).
 * All UI display helpers treat them as UTC and convert to the browser's local system time.
 */

export function parseUtcTimestamp(utcString: string): Date | null {
  if (!utcString) return null

  // Support DD-MM-YYYY HH:MM:SS format
  if (/^\d{2}-\d{2}-\d{4}/.test(utcString)) {
    const parts = utcString.split(' ')
    const dateParts = parts[0].split('-')
    const day = dateParts[0]
    const month = dateParts[1]
    const year = dateParts[2]
    const timePart = parts[1] || '00:00:00'
    const isoString = `${year}-${month}-${day}T${timePart}`
    const d = new Date(isoString)
    if (!isNaN(d.getTime())) return d
  }

  const formatted = utcString.includes('T') ? utcString : utcString.replace(' ', 'T')
  const date = new Date(formatted)
  if (!isNaN(date.getTime())) return date
  const fallback = new Date(utcString)
  return isNaN(fallback.getTime()) ? null : fallback
}

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

/** Local system date+time: DD-MM-YYYY HH:mm:ss */
export function formatLocalDateTime(utcString: string): string {
  const date = parseUtcTimestamp(utcString)
  if (!date) return utcString || ''
  return (
    `${pad(date.getDate())}-${pad(date.getMonth() + 1)}-${date.getFullYear()} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  )
}

/** Local system date only: DD-MM-YYYY */
export function formatLocalDateOnly(utcString: string): string {
  const date = parseUtcTimestamp(utcString)
  if (!date) return utcString || ''
  return `${pad(date.getDate())}-${pad(date.getMonth() + 1)}-${date.getFullYear()}`
}

/** Local system time only: HH:mm:ss */
export function formatLocalTime(utcString: string): string {
  const date = parseUtcTimestamp(utcString)
  if (!date) return utcString || ''
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

/** Compact relative: "2s ago", "5m ago" (uses local clock via Date). */
export function formatRelativeAgo(utcString: string, nowMs: number = Date.now()): string {
  const date = parseUtcTimestamp(utcString)
  if (!date) return ''
  const diffSec = Math.max(0, Math.floor((nowMs - date.getTime()) / 1000))
  if (diffSec < 60) return `${diffSec}s ago`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  return `${diffDay}d ago`
}
