import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { CalendarClock, FolderKanban, MoreHorizontal, User } from 'lucide-react'
import { api, itemsOf } from '@/api/client'
import { BOARD_STATUSES, LEAD_STATUSES } from '@/api/types'
import type { LeadListItem, LeadStatus } from '@/api/types'
import { PageHeader } from '@/components/bits'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Select } from '@/components/ui/input'
import { Empty, ErrorState, InlineError, Loading } from '@/components/ui/states'
import { useCanEdit } from '@/lib/hooks'
import { useOpenCompany } from '@/lib/openCompany'
import { cn, fmtDate, isOverdue, label } from '@/lib/utils'

const COLUMN_HINT: Record<LeadStatus, string> = {
  new: 'Just opened',
  met: 'Met at the booth',
  follow_up: 'Follow-up owed',
  talking: 'In conversation',
  parked: 'Not now',
}

export default function Board() {
  const [params, setParams] = useSearchParams()
  const show = params.get('show') ?? ''
  const owner = params.get('owner') ?? ''
  const parked = params.get('parked') === '1'
  const canEdit = useCanEdit()
  const qc = useQueryClient()
  const openCompany = useOpenCompany()
  const [dragOver, setDragOver] = useState<LeadStatus | null>(null)
  const key = ['leads', 'board', { show, owner, parked }]

  const q = useQuery({
    queryKey: key,
    queryFn: () => api.leads({ convention: show, owner, include_parked: parked, page_size: 500 }),
  })
  // owners for the filter come from an unfiltered (by owner) list
  const all = useQuery({
    queryKey: ['leads', 'board', { show, owner: '', parked: true }],
    queryFn: () => api.leads({ convention: show, include_parked: true, page_size: 500 }),
    staleTime: 60_000,
  })
  const owners = useMemo(() => Array.from(new Set(itemsOf(all.data).map((l) => l.owner).filter(Boolean) as string[])).sort(), [all.data])

  const move = useMutation({
    mutationFn: ({ id, status }: { id: number; status: LeadStatus }) => api.patchLead(id, { status }),
    onMutate: async ({ id, status }) => {
      await qc.cancelQueries({ queryKey: key })
      const prev = qc.getQueryData(key)
      qc.setQueryData(key, (old: unknown) => {
        const patchOne = (l: LeadListItem) => (l.id === id ? { ...l, status } : l)
        if (Array.isArray(old)) return old.map(patchOne)
        if (old && typeof old === 'object' && 'items' in old) return { ...(old as object), items: (old as { items: LeadListItem[] }).items.map(patchOne) }
        return old
      })
      return { prev }
    },
    onError: (_e, _v, ctx) => ctx?.prev !== undefined && qc.setQueryData(key, ctx.prev),
    onSettled: () => qc.invalidateQueries({ queryKey: ['leads'] }),
  })

  const setParam = (k: string, v: string) => {
    const p = new URLSearchParams(params)
    if (v) p.set(k, v)
    else p.delete(k)
    setParams(p)
  }

  const statuses = parked ? [...BOARD_STATUSES, 'parked' as const] : BOARD_STATUSES
  const leads = itemsOf(q.data)
  const byStatus = (s: LeadStatus) =>
    leads
      .filter((l) => l.status === s)
      .sort((a, b) => (a.follow_up_on ?? '9999').localeCompare(b.follow_up_on ?? '9999'))

  return (
    <>
      <PageHeader title="Leads board" sub={q.data ? `${leads.length} followed${show ? ` · ${show}` : ''} · sorted by follow-up` : ' '}>
        <Select aria-label="Owner" value={owner} onChange={(e) => setParam('owner', e.target.value)}>
          <option value="">Any owner</option>
          {owner && !owners.includes(owner) ? <option value={owner}>{owner}</option> : null}
          {owners.map((o) => <option key={o} value={o}>{o}</option>)}
        </Select>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={parked} onCheckedChange={(v) => setParam('parked', v === true ? '1' : '')} /> Show parked
        </label>
      </PageHeader>
      <InlineError error={move.error} />
      {q.isLoading ? <Loading /> : q.isError ? <ErrorState error={q.error} retry={q.refetch} /> : leads.length === 0 ? (
        <Empty title="No followed leads yet" icon={<FolderKanban className="size-6" />}>
          Press <b>Follow</b> on a company in the <Link className="text-primary hover:underline" to={`/leads/companies${show ? `?show=${encodeURIComponent(show)}` : ''}`}>directory</Link> or on the floor list.
        </Empty>
      ) : (
        <div className="-mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-4 md:mx-0 md:grid md:snap-none md:overflow-visible md:px-0" style={{ gridTemplateColumns: `repeat(${statuses.length}, minmax(0, 1fr))` }}>
          {statuses.map((s) => {
            const items = byStatus(s)
            return (
              <section
                key={s}
                aria-label={label(s)}
                className={cn('flex w-[85vw] max-w-sm shrink-0 snap-start flex-col rounded-lg border bg-muted/40 md:w-auto md:max-w-none', dragOver === s && 'ring-2 ring-primary')}
                onDragOver={(e) => {
                  if (!canEdit) return
                  e.preventDefault()
                  setDragOver(s)
                }}
                onDragLeave={() => setDragOver((d) => (d === s ? null : d))}
                onDrop={(e) => {
                  e.preventDefault()
                  setDragOver(null)
                  const id = Number(e.dataTransfer.getData('text/lead-id'))
                  const l = leads.find((x) => x.id === id)
                  if (l && l.status !== s) move.mutate({ id, status: s })
                }}
              >
                <header className="flex items-baseline justify-between px-3 py-2">
                  <h2 className="text-sm font-semibold capitalize">{label(s)}</h2>
                  <span className="text-xs text-muted-foreground">{items.length} · {COLUMN_HINT[s]}</span>
                </header>
                <ol className="flex flex-1 flex-col gap-2 px-2 pb-2">
                  {items.map((l) => (
                    <LeadCard key={l.id} l={l} canEdit={canEdit} onOpen={() => openCompany(l.company.id, { tab: 'meetings' })} onMove={(st) => move.mutate({ id: l.id, status: st })} />
                  ))}
                  {items.length === 0 ? <li className="rounded-md border border-dashed p-3 text-center text-xs text-muted-foreground">Nothing here</li> : null}
                </ol>
              </section>
            )
          })}
        </div>
      )}
    </>
  )
}

function LeadCard({ l, canEdit, onOpen, onMove }: { l: LeadListItem; canEdit: boolean; onOpen: () => void; onMove: (s: LeadStatus) => void }) {
  const overdue = l.overdue ?? isOverdue(l.follow_up_on)
  return (
    <li
      draggable={canEdit}
      onDragStart={(e) => {
        e.dataTransfer.setData('text/lead-id', String(l.id))
        e.dataTransfer.effectAllowed = 'move'
      }}
      className="group relative rounded-md border bg-card p-3 text-sm shadow-sm transition-shadow hover:shadow-md"
    >
      <button type="button" onClick={onOpen} className="block w-full text-left after:absolute after:inset-0 after:content-['']" aria-label={`Open ${l.company.name}`}>
        <span className="block pr-7 font-medium leading-tight">{l.company.name}</span>
      </button>
      {l.contact ? <p className="mt-0.5 truncate text-xs text-muted-foreground">{l.contact.name}{l.contact.email ? ` · ${l.contact.email}` : ''}</p> : null}
      {l.last_note ? <p className="mt-1.5 line-clamp-2 text-xs">{l.last_note}</p> : null}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {l.owner ? <span className="flex items-center gap-1"><User className="size-3" />{l.owner}</span> : null}
        {l.follow_up_on ? (
          <span className={cn('flex items-center gap-1', overdue && 'font-semibold text-red-600 dark:text-red-400')}>
            <CalendarClock className="size-3" />
            {overdue ? 'overdue · ' : ''}
            {fmtDate(l.follow_up_on)}
          </span>
        ) : null}
        {l.linked_case_count ? <span>{l.linked_case_count} case{l.linked_case_count === 1 ? '' : 's'}</span> : null}
        {l.convention_slug ? <span>{l.convention_slug}</span> : null}
      </div>
      {canEdit ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="absolute right-1 top-1 z-10 size-7" aria-label={`Change status of ${l.company.name}`}>
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>Move to</DropdownMenuLabel>
            {LEAD_STATUSES.filter((s) => s !== l.status).map((s) => (
              <DropdownMenuItem key={s} onSelect={() => onMove(s)} className="capitalize">
                {label(s)}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </li>
  )
}
