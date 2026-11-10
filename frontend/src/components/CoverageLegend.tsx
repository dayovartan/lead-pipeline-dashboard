// Coverage legend that doubles as the filter.
// Hierarchy: who (clients / suppliers) → tag groups (hardware, servers, AI infra, …) → tags inside each group.
// Everything comes from the show's own tag groups and tags and the per-show role; nothing is hard-coded.
import { createContext, useContext, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ChevronRight, Filter, X } from 'lucide-react'
import type { CoverageBooth, Role, TagList, TagWithCount, VenueNode } from '@/api/types'
import { Checkbox } from './ui/checkbox'
import { Button } from './ui/button'
import { cn } from '@/lib/utils'

export type Who = 'lead' | 'supplier' | 'unmapped'
export const WHO: { id: Who; label: string; hint: string }[] = [
  { id: 'lead', label: 'Clients', hint: 'role lead or both: companies we could sell to' },
  { id: 'supplier', label: 'Suppliers', hint: 'role supplier or both: companies we could buy from' },
  { id: 'unmapped', label: 'Not mapped yet', hint: 'no role confirmed or suggested' },
]

export interface LegendFilter {
  who: Set<Who>
  tags: Set<number>
  suggested: boolean // also count suggested (unconfirmed) roles and tags
}

function roleOf(b: CoverageBooth, suggested: boolean): Role | null {
  return b.role ?? (suggested ? b.suggested_role ?? null : null)
}
export function boothWho(b: CoverageBooth, suggested: boolean): Who[] {
  const r = roleOf(b, suggested)
  if (r === 'both') return ['lead', 'supplier']
  if (r === 'lead' || r === 'supplier') return [r]
  if (r === 'ignore') return []
  return ['unmapped']
}
export function boothTagIds(b: CoverageBooth, suggested: boolean): number[] {
  return (b.tags ?? []).filter((t) => t.confirmed || suggested).map((t) => t.tag_id)
}
export function isActive(f: LegendFilter) {
  return f.who.size > 0 || f.tags.size > 0
}
/** OR inside a section, AND between sections. */
export function matches(b: CoverageBooth, f: LegendFilter) {
  if (f.who.size && !boothWho(b, f.suggested).some((w) => f.who.has(w))) return false
  if (f.tags.size && !boothTagIds(b, f.suggested).some((t) => f.tags.has(t))) return false
  return true
}

/** Filter state kept in the URL (?who=lead,supplier&tags=3,7&sugg=0) so a view can be shared. */
export function useLegendFilter(): [LegendFilter, (f: LegendFilter) => void] {
  const [sp, setSp] = useSearchParams()
  const f = useMemo<LegendFilter>(
    () => ({
      who: new Set((sp.get('who') ?? '').split(',').filter(Boolean) as Who[]),
      tags: new Set((sp.get('tags') ?? '').split(',').filter(Boolean).map(Number)),
      suggested: sp.get('sugg') !== '0',
    }),
    [sp],
  )
  const set = (n: LegendFilter) =>
    setSp(
      (prev) => {
        const p = new URLSearchParams(prev)
        n.who.size ? p.set('who', [...n.who].join(',')) : p.delete('who')
        n.tags.size ? p.set('tags', [...n.tags].join(',')) : p.delete('tags')
        n.suggested ? p.delete('sugg') : p.set('sugg', '0')
        return p
      },
      { replace: true },
    )
  return [f, set]
}

/** What the coverage nodes read to highlight: matching appearances and per-node match counts. */
export interface Highlight {
  active: boolean
  match: Set<number> // appearance ids
  nodeCount: Map<number, number> // venue node id → matching companies at or under it
}
export const HighlightContext = createContext<Highlight>({ active: false, match: new Set(), nodeCount: new Map() })
export const useHighlight = () => useContext(HighlightContext)

export function computeHighlight(nodes: VenueNode[], booths: CoverageBooth[], f: LegendFilter): Highlight {
  const active = isActive(f)
  const match = new Set<number>()
  const nodeCount = new Map<number, number>()
  if (!active) return { active, match, nodeCount }
  const parent = new Map(nodes.map((n) => [n.id, n.parent_id]))
  for (const b of booths) {
    if (!matches(b, f)) continue
    match.add(b.appearance_id)
    let id: number | null | undefined = b.node_id
    while (id != null) {
      nodeCount.set(id, (nodeCount.get(id) ?? 0) + 1)
      id = parent.get(id)
    }
  }
  return { active, match, nodeCount }
}

type Group = { id: number | 'none'; name: string; tags: TagWithCount[] }

export function CoverageLegend({ booths, tagList, filter, onChange, matchCount, className }: {
  booths: CoverageBooth[]
  tagList: TagList | undefined
  filter: LegendFilter
  onChange: (f: LegendFilter) => void
  matchCount: number
  className?: string
}) {
  const [open, setOpen] = useState<Set<string>>(new Set())
  const [collapsed, setCollapsed] = useState(false)

  // counts in this show, honouring the "include suggested" switch
  const { whoCount, tagCount } = useMemo(() => {
    const whoCount = new Map<Who, number>()
    const tagCount = new Map<number, number>()
    for (const b of booths) {
      for (const w of boothWho(b, filter.suggested)) whoCount.set(w, (whoCount.get(w) ?? 0) + 1)
      for (const t of new Set(boothTagIds(b, filter.suggested))) tagCount.set(t, (tagCount.get(t) ?? 0) + 1)
    }
    return { whoCount, tagCount }
  }, [booths, filter.suggested])

  const groups: Group[] = useMemo(() => {
    const g: Group[] = (tagList?.groups ?? []).map((x) => ({ id: x.id, name: x.name, tags: x.tags }))
    if (tagList?.ungrouped?.length) g.push({ id: 'none', name: 'Other tags', tags: tagList.ungrouped })
    return g
  }, [tagList])

  const groupCount = (g: Group) => booths.filter((b) => boothTagIds(b, filter.suggested).some((t) => g.tags.some((x) => x.id === t))).length

  const toggleWho = (w: Who) => {
    const who = new Set(filter.who)
    who.has(w) ? who.delete(w) : who.add(w)
    onChange({ ...filter, who })
  }
  const toggleTag = (id: number) => {
    const tags = new Set(filter.tags)
    tags.has(id) ? tags.delete(id) : tags.add(id)
    onChange({ ...filter, tags })
  }
  const toggleGroup = (g: Group) => {
    const tags = new Set(filter.tags)
    const all = g.tags.length > 0 && g.tags.every((t) => tags.has(t.id))
    g.tags.forEach((t) => (all ? tags.delete(t.id) : tags.add(t.id)))
    onChange({ ...filter, tags })
  }
  const groupState = (g: Group): boolean | 'indeterminate' => {
    const n = g.tags.filter((t) => filter.tags.has(t.id)).length
    return n === 0 ? false : n === g.tags.length ? true : 'indeterminate'
  }
  const flip = (k: string) => setOpen((s) => {
    const n = new Set(s)
    n.has(k) ? n.delete(k) : n.add(k)
    return n
  })
  const active = isActive(filter)

  return (
    <aside className={cn('rounded-lg border bg-card text-sm', className)} aria-label="Legend and filter">
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <Filter className="size-4 text-muted-foreground" />
        <span className="font-semibold">Legend</span>
        {active ? <span className="text-xs tabular-nums text-muted-foreground">{matchCount} match</span> : null}
        <div className="ml-auto flex items-center gap-1">
          {active ? (
            <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => onChange({ ...filter, who: new Set(), tags: new Set() })}>
              <X /> Clear
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" className="h-7 px-2 lg:hidden" onClick={() => setCollapsed((c) => !c)} aria-expanded={!collapsed}>
            {collapsed ? 'Show' : 'Hide'}
          </Button>
        </div>
      </div>

      <div className={cn('max-h-[calc(100vh-17rem)] overflow-y-auto p-2', collapsed && 'hidden lg:block')}>
        <Section title="Who">
          {WHO.map((w) => (
            <Row key={w.id} title={w.hint} checked={filter.who.has(w.id)} onToggle={() => toggleWho(w.id)} label={w.label} count={whoCount.get(w.id) ?? 0} />
          ))}
        </Section>

        <Section title="Groups">
          {groups.length === 0 ? (
            <p className="px-2 py-1 text-xs text-muted-foreground">No tag groups for this show yet. Create them on the Tags page.</p>
          ) : (
            groups.map((g) => {
              const k = String(g.id)
              const isOpen = open.has(k)
              return (
                <div key={k}>
                  <div className="flex items-center gap-1">
                    <button type="button" className="grid size-6 place-items-center rounded hover:bg-accent" onClick={() => flip(k)} aria-label={isOpen ? `Collapse ${g.name}` : `Expand ${g.name}`} aria-expanded={isOpen}>
                      <ChevronRight className={cn('size-4 transition-transform', isOpen && 'rotate-90')} />
                    </button>
                    <Row className="flex-1 pl-0" checked={groupState(g)} onToggle={() => toggleGroup(g)} label={g.name} count={groupCount(g)} strong disabled={!g.tags.length} />
                  </div>
                  {isOpen ? (
                    <div className="ml-6 border-l pl-1">
                      {g.tags.length === 0 ? <p className="px-2 py-1 text-xs text-muted-foreground">No tags in this group.</p> : null}
                      {[...g.tags].sort((a, b) => a.name.localeCompare(b.name)).map((t) => (
                        <Row key={t.id} checked={filter.tags.has(t.id)} onToggle={() => toggleTag(t.id)} label={t.name} count={tagCount.get(t.id) ?? 0} />
                      ))}
                    </div>
                  ) : null}
                </div>
              )
            })
          )}
        </Section>

        <label className="mt-2 flex cursor-pointer items-center gap-2 border-t px-2 pt-2 text-xs text-muted-foreground">
          <Checkbox checked={filter.suggested} onCheckedChange={(v) => onChange({ ...filter, suggested: v === true })} />
          Include suggested roles and tags (not yet confirmed)
        </label>
      </div>
    </aside>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-2">
      <div className="px-2 pb-1 pt-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</div>
      {children}
    </div>
  )
}

function Row({ checked, onToggle, label, count, title, strong, disabled, className }: {
  checked: boolean | 'indeterminate'
  onToggle: () => void
  label: string
  count: number
  title?: string
  strong?: boolean
  disabled?: boolean
  className?: string
}) {
  return (
    <label title={title} className={cn('flex cursor-pointer items-center gap-2 rounded px-2 py-1 hover:bg-accent', disabled && 'cursor-default opacity-50', className)}>
      <Checkbox checked={checked} onCheckedChange={onToggle} disabled={disabled} />
      <span className={cn('flex-1 truncate', strong && 'font-medium')}>{label}</span>
      <span className="tabular-nums text-xs text-muted-foreground">{count}</span>
    </label>
  )
}
