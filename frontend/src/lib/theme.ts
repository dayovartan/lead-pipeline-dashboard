import { useEffect, useSyncExternalStore } from 'react'

export type Mode = 'system' | 'light' | 'dark'
export type Accent = 'blue' | 'teal' | 'violet' | 'amber' | 'rose' | 'slate'
export interface Theme { mode: Mode; accent: Accent }

export const ACCENTS: { id: Accent; label: string; swatch: string }[] = [
  { id: 'blue', label: 'Blue', swatch: 'hsl(221 83% 45%)' },
  { id: 'teal', label: 'Teal', swatch: 'hsl(173 80% 30%)' },
  { id: 'violet', label: 'Violet', swatch: 'hsl(262 70% 50%)' },
  { id: 'amber', label: 'Amber', swatch: 'hsl(32 95% 44%)' },
  { id: 'rose', label: 'Rose', swatch: 'hsl(346 77% 46%)' },
  { id: 'slate', label: 'Slate', swatch: 'hsl(222 47% 20%)' },
]

// Remembered per user in this browser: "leads-theme:<email>". "leads-theme:last" lets index.html
// apply the theme before the first paint, before /api/me has answered.
const LAST = 'leads-theme:last'
const DEFAULT: Theme = { mode: 'system', accent: 'blue' }
const mq = () => window.matchMedia('(prefers-color-scheme: dark)')

function read(key: string): Theme | null {
  try {
    const v = JSON.parse(localStorage.getItem(key) || 'null')
    return v && v.mode && v.accent ? v : null
  } catch {
    return null
  }
}
function write(key: string, t: Theme) {
  try { localStorage.setItem(key, JSON.stringify(t)) } catch { /* private mode */ }
}

let user: string | null = null
let current: Theme = read(LAST) ?? DEFAULT
const listeners = new Set<() => void>()

export function isDark(t: Theme = current) {
  return t.mode === 'dark' || (t.mode === 'system' && mq().matches)
}

function apply() {
  const el = document.documentElement
  el.classList.toggle('dark', isDark())
  if (current.accent === 'blue') el.removeAttribute('data-accent')
  else el.setAttribute('data-accent', current.accent)
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', isDark() ? '#0b1120' : '#ffffff')
  listeners.forEach((l) => l())
}

export function setTheme(patch: Partial<Theme>) {
  current = { ...current, ...patch }
  write(LAST, current)
  if (user) write(`leads-theme:${user}`, current)
  apply()
}

/** Called once the signed-in user is known: switch to that user's saved theme. */
export function useThemeForUser(email: string | undefined) {
  useEffect(() => {
    if (!email || email === user) return
    user = email
    const saved = read(`leads-theme:${email}`)
    if (saved) { current = saved; write(LAST, saved) } else write(`leads-theme:${email}`, current)
    apply()
  }, [email])
}

if (typeof window !== 'undefined') {
  apply()
  mq().addEventListener('change', () => current.mode === 'system' && apply())
}

function subscribe(l: () => void) {
  listeners.add(l)
  return () => listeners.delete(l)
}
let snap = { ...current, dark: isDark() }
function getSnapshot() {
  const d = isDark()
  if (snap.mode !== current.mode || snap.accent !== current.accent || snap.dark !== d) snap = { ...current, dark: d }
  return snap
}

/** { mode, accent, dark } — dark is the resolved value (system mode follows the OS). */
export function useTheme() {
  return useSyncExternalStore(subscribe, getSnapshot)
}
