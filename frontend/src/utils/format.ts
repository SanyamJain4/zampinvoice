import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Money arrives as an exact decimal string; format without going through float rounding surprises. */
export function money(value: string | number | null | undefined, currency?: string | null): string {
  if (value === null || value === undefined || value === '') return '—'
  const n = typeof value === 'number' ? value : Number(value)
  if (Number.isNaN(n)) return String(value)
  const s = n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  const sym: Record<string, string> = { INR: '₹', USD: '$', EUR: '€', GBP: '£' }
  if (!currency) return s
  return sym[currency] ? `${sym[currency]}${s}` : `${currency} ${s}`
}

export function compactMoney(value: number, currency = 'INR'): string {
  const sym = currency === 'INR' ? '₹' : currency === 'USD' ? '$' : ''
  if (currency === 'INR') {
    if (value >= 1e7) return `${sym}${(value / 1e7).toFixed(2)} Cr`
    if (value >= 1e5) return `${sym}${(value / 1e5).toFixed(2)} L`
  }
  return `${sym}${value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
}

export function fullDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

export function dateOnly(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso.length === 10 ? iso + 'T00:00:00' : iso)
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
}

export function duration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`
}

export function seconds(s: number | null | undefined): string {
  if (s === null || s === undefined) return '—'
  return s < 1 ? `${Math.round(s * 1000)} ms` : `${s.toFixed(s < 10 ? 2 : 1)} s`
}

export function humanize(s: string): string {
  return s.replace(/_/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase())
}

export function decisionLabel(d: string | null | undefined): string {
  switch (d) {
    case 'APPROVED': return 'Approved'
    case 'NEEDS_REVIEW': return 'Needs review'
    case 'REJECTED': return 'Rejected'
    case 'PROCESSING_ERROR': return 'Processing error'
    default: return d ? humanize(d) : 'Not processed'
  }
}
