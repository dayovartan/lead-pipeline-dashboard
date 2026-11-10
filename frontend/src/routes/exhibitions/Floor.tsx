import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Check, CloudOff, RefreshCw, Star, UserPlus, Wifi } from 'lucide-react'
import { api } from '@/api/client'
import type { Appearance, FloorList, FloorNoteInput } from '@/api/types'
import { PriorityBadge, TagChips } from '@/components/bits'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Empty, ErrorState, Loading } from '@/components/ui/states'
import { useCanEdit, useOnline } from '@/lib/hooks'
import { clearFailed, enqueue, flush, setOnSent, useQueue } from '@/lib/offlineQueue'
import { load, save } from '@/lib/storage'
import { cn } from '@/lib/utils'

type Local = { visited?: boolean; note?: string; followed?: boolean }
const byBooth = (a: Appearance, b: Appearance) => (a.booth ?? '').localeCompare(b.booth ?? '', undefined, { numeric: true })

/** Phone floor list: one hall at a time, booth order, big checkbox, one-line note, add contact, follow. */
export default function Floor() {
  const { slug = '', person = 'all' } = useParams()
  const qc = useQueryClient()
  const online = useOnline()
  const canEdit = useCanEdit()
  const { queue, failed, flushing } = useQueue()
  const hallKey = `leads.floorHall.${slug}.${person}`
  const [hall, setHall] = useState<string>(() => load(hallKey, ''))
  const [filter, setFilter] = useState('')
  const snapKey = `leads.floorSnap.${slug}.${person}.${hall}`
  const localKey = `leads.floorLocal.${slug}`
  const [local, setLocal] = useState<Record<number, Local>>(() => load(localKey, {}))

  const q = useQuery({
    queryKey: ['floor', slug, person, hall],
    queryFn: async () => {
      const r = await api.floor(slug, person, hall || undefined)
      save(snapKey, r) // offline fallback, in addition to the service worker cache
      return r
    },
    initialData: () => load<FloorList | undefined>(snapKey, undefined),
    initialDataUpdatedAt: 0,
    networkMode: 'always',
    retry: online ? 2 : 0,
  })
  const conv = useQuery({ queryKey: ['convention', slug], queryFn: () => api.convention(slug), retry: 0 })

  useEffect(() => save(hallKey, hall), [hallKey, hall])
  useEffect(() => save(localKey, local), [localKey, local])
  useEffect(() => {
    if (!hall && q.data?.hall) setHall(q.data.hall)
  }, [hall, q.data?.hall])
  // when the queue drains, refresh from the server and drop local overrides it now reflects
  useEffect(() => {
    setOnSent(() => qc.invalidateQueries({ queryKey: ['floor', slug] }))
    return () => setOnSent(null)
  }, [qc, slug])
  useEffect(() => {
    if (online) void flush()
  }, [online])

  const pendingIds = useMemo(() => new Set(queue.map((t) => t.appearanceId)), [queue])
  useEffect(() => {
    // forget local overrides once nothing is queued for that booth and the server agrees with them
    if (!q.data || q.isFetching) return
    const server = new Map(q.data.items.map((a) => [a.id, a]))
    setLocal((cur) => {
      let changed = false
      const next: Record<number, Local> = {}
      for (const [k, v] of Object.entries(cur)) {
        const id = Number(k)
        const a = server.get(id)
        if (pendingIds.has(id) || !a) {
          next[id] = v
          continue
        }
        const keep: Local = {}
        if (v.visited !== undefined && v.visited !== !!a.dispatch?.visited) keep.visited = v.visited
        if (v.followed && !a.lead_id) keep.followed = true
        if (v.note && !a.dispatch?.note) keep.note = v.note
        if (Object.keys(keep).length) next[id] = keep
        if (Object.keys(keep).length !== Object.keys(v).length) changed = true
      }
      return changed ? next : cur
    })
  }, [q.data, q.isFetching, pendingIds])

  const halls = q.data?.halls ?? []
  const items = (q.data?.items ?? [])
    .filter((a) => !hall || (a.hall ?? '') === hall || q.data?.hall === hall)
    .filter((a) => !filter || `${a.booth} ${a.company.name}`.toLowerCase().includes(filter.toLowerCase()))
    .sort(byBooth)
  const visitedCount = items.filter((a) => local[a.id]?.visited ?? a.dispatch?.visited).length

  const tapVisited = (a: Appearance, visited: boolean) => {
    setLocal((c) => ({ ...c, [a.id]: { ...c[a.id], visited } }))
    enqueue({ kind: 'dispatch', slug, appearanceId: a.id, body: { visited } })
  }
  const tapNote = (a: Appearance, body: FloorNoteInput) => {
    setLocal((c) => ({ ...c, [a.id]: { ...c[a.id], visited: true, note: body.text } }))
    enqueue({ kind: 'note', slug, appearanceId: a.id, body })
  }
  const tapFollow = (a: Appearance) => {
    setLocal((c) => ({ ...c, [a.id]: { ...c[a.id], followed: true } }))
    enqueue({ kind: 'follow', slug, appearanceId: a.id })
  }

  return (
    <div className="mx-auto min-h-full max-w-xl pb-16">
      <header className="sticky top-0 z-20 border-b bg-background/95 px-3 pb-2 pt-[max(0.5rem,env(safe-area-inset-top))] backdrop-blur">
        <div className="flex items-center gap-2">
          <Link to={`/exhibitions/${encodeURIComponent(slug)}/dispatch`} className="rounded p-1 text-muted-foreground hover:bg-accent" aria-label="Back to dispatch">
            <ArrowLeft className="size-5" />
          </Link>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-base font-semibold">{conv.data?.name ?? slug}</h1>
            <p className="text-xs text-muted-foreground">
              {person === 'all' ? 'Everyone' : person} · {visitedCount}/{items.length} visited{hall ? ` in hall ${hall}` : ''}
            </p>
          </div>
          <span
            className={cn('flex items-center gap-1 rounded-full px-2 py-0.5 text-xs', online ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300' : 'bg-amber-500/15 text-amber-700 dark:text-amber-300')}
            role="status"
          >
            {online ? <Wifi className="size-3" /> : <CloudOff className="size-3" />}
            {queue.length ? `${queue.length} to send` : online ? 'saved' : 'offline'}
          </span>
          {queue.length && online ? (
            <Button size="icon" variant="ghost" aria-label="Send now" onClick={() => void flush()} disabled={flushing}>
              <RefreshCw className={cn(flushing && 'animate-spin')} />
            </Button>
          ) : null}
        </div>
        {halls.length ? (
          <nav aria-label="Halls" className="-mx-3 mt-2 flex gap-1.5 overflow-x-auto px-3 pb-1">
            {halls.map((h) => (
              <button
                key={h ?? '—'}
                type="button"
                onClick={() => setHall(h ?? '')}
                aria-pressed={(h ?? '') === hall}
                className={cn('shrink-0 rounded-full border px-3 py-1.5 text-sm font-medium', (h ?? '') === hall ? 'border-primary bg-primary text-primary-foreground' : 'bg-card')}
              >
                {h ?? 'no hall'}
              </button>
            ))}
          </nav>
        ) : null}
        <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Find booth or company" className="mt-2 h-10" aria-label="Find booth or company" />
      </header>

      {failed.length ? (
        <div role="alert" className="m-3 rounded-md border border-destructive/50 p-3 text-sm">
          <p className="font-medium text-destructive">{failed.length} tap(s) were rejected by the server</p>
          <ul className="mt-1 text-xs text-muted-foreground">
            {failed.slice(-3).map((f) => <li key={f.tap.id}>{f.tap.kind}: {f.error}</li>)}
          </ul>
          <Button size="sm" variant="outline" className="mt-2" onClick={clearFailed}>Dismiss</Button>
        </div>
      ) : null}

      {q.isLoading && !q.data ? <Loading /> : q.isError && !q.data ? <ErrorState error={q.error} retry={q.refetch} /> : items.length === 0 ? (
        <Empty title="No booths here">{filter ? 'Nothing matches the search.' : 'Pick another hall, or ask for booths to be assigned.'}</Empty>
      ) : (
        <ol className="divide-y">
          {items.map((a) => (
            <FloorRow
              key={a.id}
              a={a}
              local={local[a.id]}
              pending={pendingIds.has(a.id)}
              canEdit={canEdit}
              onVisited={(v) => tapVisited(a, v)}
              onNote={(b) => tapNote(a, b)}
              onFollow={() => tapFollow(a)}
            />
          ))}
        </ol>
      )}
    </div>
  )
}

function FloorRow({ a, local, pending, canEdit, onVisited, onNote, onFollow }: { a: Appearance; local?: Local; pending: boolean; canEdit: boolean; onVisited: (v: boolean) => void; onNote: (b: FloorNoteInput) => void; onFollow: () => void }) {
  const visited = local?.visited ?? !!a.dispatch?.visited
  const savedNote = local?.note ?? a.dispatch?.note ?? ''
  const followed = local?.followed || !!a.lead_id
  const [note, setNote] = useState('')
  const [contactOpen, setContactOpen] = useState(false)
  const [contact, setContact] = useState({ name: '', email: '', title: '', phone: '' })

  const submit = () => {
    const text = note.trim() || (contact.name ? `Met ${contact.name}` : '')
    if (!text) return
    onNote({ text, contact: contactOpen && contact.name.trim() ? { name: contact.name.trim(), email: contact.email.trim() || undefined, title: contact.title.trim() || undefined, phone: contact.phone.trim() || undefined } : undefined })
    setNote('')
    setContact({ name: '', email: '', title: '', phone: '' })
    setContactOpen(false)
  }

  return (
    <li className={cn('px-3 py-3', visited && 'bg-emerald-500/5')}>
      <div className="flex items-start gap-3">
        <button
          type="button"
          role="checkbox"
          aria-checked={visited}
          aria-label={`Visited ${a.company.name}`}
          disabled={!canEdit}
          onClick={() => onVisited(!visited)}
          className={cn('flex size-12 shrink-0 items-center justify-center rounded-lg border-2 transition-colors', visited ? 'border-emerald-600 bg-emerald-600 text-white' : 'border-input bg-card')}
        >
          {visited ? <Check className="size-7" strokeWidth={3} /> : null}
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="shrink-0 text-base font-bold tabular-nums">{a.booth ?? '—'}</span>
            <span className="min-w-0 truncate text-base font-medium">{a.company.name}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1">
            <PriorityBadge priority={a.priority} />
            <TagChips tags={a.tags} max={3} />
            {pending ? <span className="text-xs text-amber-600 dark:text-amber-400">not sent yet</span> : null}
          </div>
          {savedNote ? <p className="mt-1 text-sm text-muted-foreground">“{savedNote}”</p> : null}
        </div>
      </div>
      {canEdit ? (
        <div className="mt-2 space-y-2 pl-[3.75rem]">
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              submit()
            }}
          >
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="One-line note" className="h-10" enterKeyHint="send" aria-label={`Note for ${a.company.name}`} />
            <Button type="submit" className="h-10" disabled={!note.trim() && !(contactOpen && contact.name.trim())}>Save</Button>
          </form>
          {contactOpen ? (
            <div className="grid grid-cols-2 gap-2">
              <Input className="h-10" placeholder="Name" value={contact.name} onChange={(e) => setContact({ ...contact, name: e.target.value })} autoComplete="off" />
              <Input className="h-10" placeholder="Title" value={contact.title} onChange={(e) => setContact({ ...contact, title: e.target.value })} autoComplete="off" />
              <Input className="h-10" type="email" placeholder="Email" value={contact.email} onChange={(e) => setContact({ ...contact, email: e.target.value })} autoComplete="off" />
              <Input className="h-10" type="tel" placeholder="Phone" value={contact.phone} onChange={(e) => setContact({ ...contact, phone: e.target.value })} autoComplete="off" />
            </div>
          ) : null}
          <div className="flex gap-2">
            <Button variant="outline" size="sm" className="h-9" onClick={() => setContactOpen((o) => !o)} aria-expanded={contactOpen}>
              <UserPlus /> {contactOpen ? 'No contact' : 'Add contact'}
            </Button>
            <Button variant={followed ? 'secondary' : 'outline'} size="sm" className="h-9" disabled={followed} onClick={onFollow}>
              <Star className={cn(followed && 'fill-current')} /> {followed ? 'Following' : 'Follow'}
            </Button>
          </div>
        </div>
      ) : null}
    </li>
  )
}
