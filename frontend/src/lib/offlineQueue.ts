// Floor-list taps (visited / note / follow) are queued in localStorage and sent in order.
// A tap is removed once the server accepts it, or dropped (and reported) if the server rejects it.
// Network failures leave it queued until the browser is back online.
import { useSyncExternalStore } from 'react'
import { api, ApiError } from '@/api/client'
import type { DispatchPut, FloorNoteInput } from '@/api/types'
import { load, save } from './storage'

export type QueuedTap =
  | { id: string; at: string; kind: 'dispatch'; slug: string; appearanceId: number; body: DispatchPut }
  | { id: string; at: string; kind: 'note'; slug: string; appearanceId: number; body: FloorNoteInput }
  | { id: string; at: string; kind: 'follow'; slug: string; appearanceId: number }

type NewTap = QueuedTap extends infer T ? (T extends QueuedTap ? Omit<T, 'id' | 'at'> : never) : never

const KEY = 'leads.floorQueue'
const FAIL_KEY = 'leads.floorQueueFailed'
let queue: QueuedTap[] = load<QueuedTap[]>(KEY, [])
let failed: { tap: QueuedTap; error: string }[] = load(FAIL_KEY, [])
let flushing = false
const listeners = new Set<() => void>()
let snapshot = { queue, failed, flushing }

function emit() {
  save(KEY, queue)
  save(FAIL_KEY, failed)
  snapshot = { queue, failed, flushing }
  listeners.forEach((l) => l())
}

export function enqueue(tap: NewTap) {
  const full = { ...tap, id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, at: new Date().toISOString() } as QueuedTap
  queue = [...queue, full]
  emit()
  void flush()
}

function send(t: QueuedTap): Promise<unknown> {
  switch (t.kind) {
    case 'dispatch':
      return api.putDispatch(t.slug, t.appearanceId, t.body)
    case 'note':
      return api.floorNote(t.slug, t.appearanceId, t.body)
    case 'follow':
      return api.floorFollow(t.slug, t.appearanceId)
  }
}

let onSent: ((t: QueuedTap) => void) | null = null
export function setOnSent(fn: ((t: QueuedTap) => void) | null) {
  onSent = fn
}

export async function flush() {
  if (flushing || queue.length === 0) return
  if (!navigator.onLine) return
  flushing = true
  emit()
  try {
    while (queue.length) {
      const t = queue[0]
      try {
        await send(t)
        queue = queue.slice(1)
        onSent?.(t)
        emit()
      } catch (e) {
        if (e instanceof ApiError && e.status >= 400 && e.status < 500 && e.status !== 401 && e.status !== 408 && e.status !== 429) {
          // the server said no: don't retry forever
          queue = queue.slice(1)
          failed = [...failed, { tap: t, error: typeof e.detail === 'string' ? e.detail : e.message }]
          emit()
          continue
        }
        break // offline, 5xx or auth expired: keep it for later
      }
    }
  } finally {
    flushing = false
    emit()
  }
}

export function clearFailed() {
  failed = []
  emit()
}

export function useQueue() {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    () => snapshot,
  )
}

if (typeof window !== 'undefined') {
  window.addEventListener('online', () => void flush())
  setInterval(() => void flush(), 30_000)
  window.addEventListener('storage', (e) => {
    if (e.key === KEY) {
      queue = load<QueuedTap[]>(KEY, [])
      snapshot = { queue, failed, flushing }
      listeners.forEach((l) => l())
    }
  })
}
