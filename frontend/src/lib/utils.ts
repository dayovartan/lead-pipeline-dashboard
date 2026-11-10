import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function fmtDate(d?: string | null): string {
  if (!d) return ''
  const date = new Date(d.length === 10 ? d + 'T00:00:00' : d)
  if (isNaN(date.getTime())) return d
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

export function fmtDateTime(d?: string | null): string {
  if (!d) return ''
  const date = new Date(d)
  if (isNaN(date.getTime())) return d
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export function todayIso(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function isOverdue(d?: string | null): boolean {
  return !!d && d < todayIso()
}

export const label = (s?: string | null) => (s ? s.replace(/_/g, ' ') : '')

/** Build a query string, dropping empty values. */
export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    p.set(k, String(v))
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}
