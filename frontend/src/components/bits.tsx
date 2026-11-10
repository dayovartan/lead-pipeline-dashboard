import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { Kind, LeadStatus, Priority, Role, Tag } from '@/api/types'
import { cn, label } from '@/lib/utils'
import { Badge, type BadgeProps } from './ui/badge'
import { Button } from './ui/button'

const kindVariant: Record<string, BadgeProps['variant']> = {
  lead: 'default',
  supplier: 'success',
  both: 'warning',
  unmapped: 'suggested',
  ignore: 'secondary',
}
export function KindBadge({ kind }: { kind: Kind | Role | null | undefined }) {
  if (!kind) return <Badge variant="suggested">unmapped</Badge>
  return <Badge variant={kindVariant[kind] ?? 'outline'}>{kind}</Badge>
}

/** A role or priority that may only be suggested: dashed until a person confirms. */
export function MaybeSuggested({ value, suggested, kind }: { value: string | null | undefined; suggested?: string | null; kind: 'role' | 'priority' }) {
  if (value) return kind === 'role' ? <KindBadge kind={value as Role} /> : <PriorityBadge priority={value as Priority} />
  if (suggested)
    return (
      <Badge variant="suggested" title="Suggested — not confirmed yet">
        {label(suggested)}?
      </Badge>
    )
  return <span className="text-xs text-muted-foreground">—</span>
}

const prioVariant: Record<Priority, BadgeProps['variant']> = { must_visit: 'danger', nice_to_visit: 'warning', skip: 'secondary' }
export function PriorityBadge({ priority }: { priority: Priority | null | undefined }) {
  if (!priority) return <span className="text-xs text-muted-foreground">—</span>
  return <Badge variant={prioVariant[priority]}>{label(priority)}</Badge>
}

const statusVariant: Record<LeadStatus, BadgeProps['variant']> = {
  new: 'default',
  met: 'success',
  follow_up: 'warning',
  talking: 'success',
  parked: 'secondary',
}
export function StatusBadge({ status }: { status: LeadStatus | null | undefined }) {
  if (!status) return null
  return <Badge variant={statusVariant[status]}>{label(status)}</Badge>
}

export function TagChips({ tags, max = 6, className }: { tags: Tag[]; max?: number; className?: string }) {
  if (!tags?.length) return null
  const shown = tags.slice(0, max)
  return (
    <span className={cn('flex flex-wrap gap-1', className)}>
      {shown.map((t) => (
        <Badge
          key={t.id}
          variant={t.confirmed ? 'secondary' : 'suggested'}
          title={`${t.group ? t.group + ' · ' : ''}${t.name}${t.confirmed ? '' : ' (suggested)'}`}
        >
          {t.name}
        </Badge>
      ))}
      {tags.length > max ? <Badge variant="outline">+{tags.length - max}</Badge> : null}
    </span>
  )
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1
  const to = Math.min(total, page * pageSize)
  return (
    <div className="flex items-center justify-between gap-2 py-2 text-sm text-muted-foreground">
      <span>
        {from.toLocaleString()}–{to.toLocaleString()} of {total.toLocaleString()}
      </span>
      <div className="flex items-center gap-1">
        <Button variant="outline" size="icon" aria-label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <ChevronLeft />
        </Button>
        <span className="px-2 tabular-nums">
          {page} / {pages}
        </span>
        <Button variant="outline" size="icon" aria-label="Next page" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          <ChevronRight />
        </Button>
      </div>
    </div>
  )
}

/** Renders an MCP payload we don't own the shape of: scalars as rows, nested values compact. */
export function KeyValue({ data, omit = [] }: { data: Record<string, unknown> | null | undefined; omit?: string[] }) {
  if (!data) return null
  const entries = Object.entries(data).filter(([k, v]) => !omit.includes(k) && v !== null && v !== undefined && v !== '')
  if (!entries.length) return <p className="text-sm text-muted-foreground">Nothing to show.</p>
  return (
    <dl className="grid grid-cols-[minmax(7rem,auto)_1fr] gap-x-3 gap-y-1 text-sm">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted-foreground">{label(k)}</dt>
          <dd className="min-w-0 break-words">
            {typeof v === 'object' ? (
              <code className="block whitespace-pre-wrap text-xs">{JSON.stringify(v, null, 1)}</code>
            ) : typeof v === 'boolean' ? (
              v ? 'yes' : 'no'
            ) : (
              String(v)
            )}
          </dd>
        </div>
      ))}
    </dl>
  )
}

export function PageHeader({ title, children, sub }: { title: string; sub?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {sub ? <div className="mt-0.5 text-sm text-muted-foreground">{sub}</div> : null}
      </div>
      {children ? <div className="flex flex-wrap items-center gap-2">{children}</div> : null}
    </div>
  )
}
