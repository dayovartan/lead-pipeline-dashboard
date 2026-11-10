import { useEffect, useMemo, useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams, useSearchParams } from 'react-router-dom'
import { flexRender, getCoreRowModel, useReactTable, type ColumnDef, type RowSelectionState } from '@tanstack/react-table'
import { Check, Sparkles, Star, X } from 'lucide-react'
import { api } from '@/api/client'
import { PRIORITIES, ROLES } from '@/api/types'
import type { Appearance, AppearancePatch, BulkInput, Priority, Role } from '@/api/types'
import { PageHeader, Pagination, TagChips } from '@/components/bits'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input, Select } from '@/components/ui/input'
import { Empty, ErrorState, InlineError, Loading, Spinner } from '@/components/ui/states'
import { TD, TH, TR } from '@/components/ui/table'
import { useCanEdit, useDebounced } from '@/lib/hooks'
import { useOpenCompany } from '@/lib/openCompany'
import { cn, label } from '@/lib/utils'

const PAGE_SIZE = 50
const FILTERS = ['q', 'role', 'priority', 'tag', 'group', 'hall', 'mapped'] as const

export function useTagOptions(slug: string, enabled = true) {
  const tags = useQuery({ queryKey: ['tags', slug], queryFn: () => api.tags(slug), enabled, staleTime: 60_000 })
  const options = useMemo(
    () => [
      ...(tags.data?.groups.flatMap((g) => g.tags.map((t) => ({ id: t.id, name: t.name, group: g.name, groupId: g.id, count: t.count }))) ?? []),
      ...(tags.data?.ungrouped.map((t) => ({ id: t.id, name: t.name, group: '', groupId: null as number | null, count: t.count })) ?? []),
    ],
    [tags.data],
  )
  return { tags, options, groups: tags.data?.groups ?? [] }
}

export default function MapPage() {
  const { slug = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const page = Number(params.get('page') ?? 1) || 1
  const f = Object.fromEntries(FILTERS.map((k) => [k, params.get(k) ?? ''])) as Record<(typeof FILTERS)[number], string>
  const [qText, setQText] = useState(f.q)
  const dq = useDebounced(qText, 300)
  const canEdit = useCanEdit()
  const qc = useQueryClient()
  const openCompany = useOpenCompany()
  const [selection, setSelection] = useState<RowSelectionState>({})
  const { options: tagOptions, groups } = useTagOptions(slug)

  const setParam = (k: string, v: string, keepPage = false) => {
    const p = new URLSearchParams(params)
    if (v) p.set(k, v)
    else p.delete(k)
    if (!keepPage) p.delete('page')
    setParams(p, { replace: k === 'q' })
  }
  useEffect(() => {
    if (dq !== f.q) setParam('q', dq)
  }, [dq])

  const key = ['appearances', slug, { page, ...f }]
  const q = useQuery({ queryKey: key, queryFn: () => api.appearances(slug, { ...f, sort: 'booth', page, page_size: PAGE_SIZE }), placeholderData: keepPreviousData })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['appearances', slug] })
    qc.invalidateQueries({ queryKey: ['convention', slug] })
    qc.invalidateQueries({ queryKey: ['conventions'] })
    qc.invalidateQueries({ queryKey: ['tags', slug] })
  }
  const patch = useMutation({ mutationFn: ({ id, b }: { id: number; b: AppearancePatch }) => api.patchAppearance(slug, id, b), onSuccess: refresh })
  const bulk = useMutation({ mutationFn: (b: BulkInput) => api.bulk(slug, b), onSuccess: () => (refresh(), setSelection({})) })
  const suggest = useMutation({ mutationFn: () => api.suggest(slug), onSuccess: refresh })
  const follow = useMutation({
    mutationFn: (a: Appearance) => api.follow(a.company.id, { appearance_id: a.id }),
    onSuccess: () => (refresh(), qc.invalidateQueries({ queryKey: ['leads'] })),
  })

  const columns = useMemo<ColumnDef<Appearance>[]>(
    () => [
      {
        id: 'select',
        header: ({ table }) => (
          <Checkbox
            aria-label="Select page"
            checked={table.getIsAllRowsSelected() ? true : table.getIsSomeRowsSelected() ? 'indeterminate' : false}
            onCheckedChange={(v) => table.toggleAllRowsSelected(v === true)}
          />
        ),
        cell: ({ row }) => <Checkbox aria-label={`Select ${row.original.company.name}`} checked={row.getIsSelected()} onCheckedChange={(v) => row.toggleSelected(v === true)} onClick={(e) => e.stopPropagation()} />,
      },
      {
        id: 'company',
        header: 'Company',
        cell: ({ row: { original: a } }) => (
          <button type="button" className="min-w-[11rem] text-left" onClick={() => openCompany(a.company.id)}>
            <span className="block font-medium hover:underline">{a.company.name}</span>
            <span className="block max-w-[18rem] truncate text-xs text-muted-foreground" title={a.company.categories.join('; ')}>
              {[a.company.country, a.company.categories.slice(0, 2).join(' · ')].filter(Boolean).join(' — ')}
            </span>
          </button>
        ),
      },
      { id: 'booth', header: 'Hall / booth', cell: ({ row: { original: a } }) => <span className="whitespace-nowrap tabular-nums">{[a.hall, a.booth].filter(Boolean).join(' / ') || a.hall_booth_raw || '—'}</span> },
      {
        id: 'role',
        header: 'Role',
        cell: ({ row: { original: a } }) => (
          <SuggestedSelect
            value={a.role}
            suggested={a.mapping?.suggested_role ?? null}
            options={ROLES}
            disabled={!canEdit}
            onChange={(v) => patch.mutate({ id: a.id, b: { role: v as Role | null } })}
            label={`Role of ${a.company.name}`}
          />
        ),
      },
      {
        id: 'priority',
        header: 'Priority',
        cell: ({ row: { original: a } }) => (
          <SuggestedSelect
            value={a.priority}
            suggested={a.mapping?.suggested_priority ?? null}
            options={PRIORITIES}
            disabled={!canEdit}
            onChange={(v) => patch.mutate({ id: a.id, b: { priority: v as Priority | null } })}
            label={`Priority of ${a.company.name}`}
          />
        ),
      },
      {
        id: 'confirm',
        header: '',
        cell: ({ row: { original: a } }) => {
          const pending = (!a.role && a.mapping?.suggested_role) || (!a.priority && a.mapping?.suggested_priority) || a.tags.some((t) => !t.confirmed)
          if (!pending || !canEdit) return null
          return (
            <Button size="icon" variant="ghost" title="Confirm suggestions" aria-label={`Confirm suggestions for ${a.company.name}`} onClick={() => bulk.mutate({ ids: [a.id], confirm: true })}>
              <Check />
            </Button>
          )
        },
      },
      { id: 'tags', header: 'Tags', cell: ({ row: { original: a } }) => <TagChips tags={a.tags} max={4} className="max-w-[20rem]" /> },
      {
        id: 'lead',
        header: '',
        cell: ({ row: { original: a } }) =>
          a.lead_id ? (
            <Badge variant="default">lead</Badge>
          ) : canEdit ? (
            <Button size="sm" variant="ghost" onClick={() => follow.mutate(a)} disabled={follow.isPending} aria-label={`Follow ${a.company.name}`}>
              <Star /> Follow
            </Button>
          ) : null,
      },
    ],
    [canEdit, openCompany, patch, bulk, follow],
  )

  const table = useReactTable({
    data: q.data?.items ?? [],
    columns,
    state: { rowSelection: selection },
    enableRowSelection: canEdit,
    onRowSelectionChange: setSelection,
    getRowId: (a) => String(a.id),
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    manualFiltering: true,
  })
  const selectedIds = Object.keys(selection).filter((k) => selection[k]).map(Number)
  const hidden = canEdit ? [] : ['select', 'confirm']

  return (
    <>
      <PageHeader title="Map" sub="Role, tags and priority per exhibitor. Dashed values are suggestions until someone confirms them.">
        {q.isFetching && !q.isLoading ? <Spinner className="text-muted-foreground" /> : null}
        {canEdit ? (
          <Button variant="outline" onClick={() => suggest.mutate()} disabled={suggest.isPending}>
            <Sparkles /> {suggest.isPending ? 'Running…' : 'Run suggestions'}
          </Button>
        ) : null}
      </PageHeader>
      {suggest.data ? (
        <p className="mb-3 text-sm text-muted-foreground">
          Suggestions: {Object.entries(suggest.data).map(([k, v]) => `${label(k)} ${v}`).join(' · ')}
        </p>
      ) : null}
      <InlineError error={suggest.error ?? patch.error ?? bulk.error ?? follow.error} />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Input value={qText} onChange={(e) => setQText(e.target.value)} placeholder="Company, category, description…" className="w-full sm:w-64" aria-label="Filter exhibitors" />
        <Select aria-label="Mapped" value={f.mapped} onChange={(e) => setParam('mapped', e.target.value)}>
          <option value="">Mapped: any</option>
          <option value="false">Needs mapping</option>
          <option value="true">Confirmed</option>
        </Select>
        <Select aria-label="Role" value={f.role} onChange={(e) => setParam('role', e.target.value)}>
          <option value="">Any role</option>
          <option value="none">No role yet</option>
          {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
        </Select>
        <Select aria-label="Priority" value={f.priority} onChange={(e) => setParam('priority', e.target.value)}>
          <option value="">Any priority</option>
          <option value="none">No priority yet</option>
          {PRIORITIES.map((p) => <option key={p} value={p}>{label(p)}</option>)}
        </Select>
        <Select aria-label="Tag group" value={f.group} onChange={(e) => setParam('group', e.target.value)} className="max-w-[10rem]">
          <option value="">Any group</option>
          {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
        </Select>
        <Select aria-label="Tag" value={f.tag} onChange={(e) => setParam('tag', e.target.value)} className="max-w-[10rem]">
          <option value="">Any tag</option>
          {tagOptions.map((t) => <option key={t.id} value={t.id}>{t.group ? `${t.group} · ` : ''}{t.name}</option>)}
        </Select>
        <Input value={f.hall} onChange={(e) => setParam('hall', e.target.value)} placeholder="Hall" className="w-20" aria-label="Hall" />
      </div>

      {selectedIds.length ? <BulkBar count={selectedIds.length} tagOptions={tagOptions} busy={bulk.isPending} onApply={(b) => bulk.mutate({ ids: selectedIds, ...b })} onClear={() => setSelection({})} /> : null}

      {q.isLoading ? <Loading /> : q.isError ? <ErrorState error={q.error} retry={q.refetch} /> : q.data && q.data.items.length === 0 ? (
        <Empty title="No exhibitors match">{Object.values(f).some(Boolean) ? 'Try fewer filters.' : 'Load the Excel on the intake page first.'}</Empty>
      ) : (
        <>
          <div className="relative w-full overflow-x-auto rounded-md border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                {table.getHeaderGroups().map((hg) => (
                  <tr key={hg.id} className="border-b">
                    {hg.headers.filter((h) => !hidden.includes(h.id)).map((h) => <TH key={h.id}>{flexRender(h.column.columnDef.header, h.getContext())}</TH>)}
                  </tr>
                ))}
              </thead>
              <tbody className={cn(q.isPlaceholderData && 'opacity-60')}>
                {table.getRowModel().rows.map((r) => (
                  <TR key={r.id} data-state={r.getIsSelected() ? 'selected' : undefined}>
                    {r.getVisibleCells().filter((c) => !hidden.includes(c.column.id)).map((c) => <TD key={c.id} className="py-1.5">{flexRender(c.column.columnDef.cell, c.getContext())}</TD>)}
                  </TR>
                ))}
              </tbody>
            </table>
          </div>
          {q.data ? <Pagination page={page} pageSize={PAGE_SIZE} total={q.data.total} onPage={(p) => (setSelection({}), setParam('page', String(p), true))} /> : null}
        </>
      )}
    </>
  )
}

function SuggestedSelect({ value, suggested, options, onChange, disabled, label: aria }: { value: string | null; suggested: string | null; options: readonly string[]; onChange: (v: string | null) => void; disabled?: boolean; label: string }) {
  const isSuggested = !value && !!suggested
  return (
    <Select
      aria-label={aria}
      value={value ?? ''}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value || null)}
      className={cn('h-8 w-[8.5rem] text-xs', isSuggested && 'border-dashed border-muted-foreground/70 italic text-muted-foreground', !value && !suggested && 'text-muted-foreground')}
      title={isSuggested ? `Suggested: ${label(suggested)} — pick it to confirm` : undefined}
    >
      <option value="">{isSuggested ? `${label(suggested)}?` : '—'}</option>
      {options.map((o) => <option key={o} value={o}>{label(o)}</option>)}
    </Select>
  )
}

function BulkBar({ count, tagOptions, busy, onApply, onClear }: { count: number; tagOptions: { id: number; name: string; group: string }[]; busy: boolean; onApply: (b: Omit<BulkInput, 'ids'>) => void; onClear: () => void }) {
  const [role, setRole] = useState('')
  const [priority, setPriority] = useState('')
  const [addTag, setAddTag] = useState('')
  const [removeTag, setRemoveTag] = useState('')
  const [assignee, setAssignee] = useState('')
  const any = role || priority || addTag || removeTag || assignee
  return (
    <div className="sticky top-[6.5rem] z-20 mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-primary/40 bg-background p-2 shadow-sm">
      <span className="px-1 text-sm font-medium">{count} selected</span>
      <Select aria-label="Set role" value={role} onChange={(e) => setRole(e.target.value)} className="h-8 text-xs">
        <option value="">Role…</option>
        {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
      </Select>
      <Select aria-label="Set priority" value={priority} onChange={(e) => setPriority(e.target.value)} className="h-8 text-xs">
        <option value="">Priority…</option>
        {PRIORITIES.map((p) => <option key={p} value={p}>{label(p)}</option>)}
      </Select>
      <Select aria-label="Add tag" value={addTag} onChange={(e) => setAddTag(e.target.value)} className="h-8 max-w-[10rem] text-xs">
        <option value="">+ tag…</option>
        {tagOptions.map((t) => <option key={t.id} value={t.id}>{t.group ? `${t.group} · ` : ''}{t.name}</option>)}
      </Select>
      <Select aria-label="Remove tag" value={removeTag} onChange={(e) => setRemoveTag(e.target.value)} className="h-8 max-w-[10rem] text-xs">
        <option value="">− tag…</option>
        {tagOptions.map((t) => <option key={t.id} value={t.id}>{t.group ? `${t.group} · ` : ''}{t.name}</option>)}
      </Select>
      <Input aria-label="Assignee" value={assignee} onChange={(e) => setAssignee(e.target.value)} placeholder="Assignee" className="h-8 w-28 text-xs" />
      <Button
        size="sm"
        disabled={!any || busy}
        onClick={() =>
          onApply({
            role: (role || undefined) as Role | undefined,
            priority: (priority || undefined) as Priority | undefined,
            add_tag_ids: addTag ? [Number(addTag)] : undefined,
            remove_tag_ids: removeTag ? [Number(removeTag)] : undefined,
            assignee: assignee || undefined,
            confirm: true,
          })
        }
      >
        Set
      </Button>
      <Button size="sm" variant="outline" disabled={busy} onClick={() => onApply({ confirm: true })}>
        <Check /> Confirm suggestions
      </Button>
      <Button size="sm" variant="ghost" onClick={onClear} className="ml-auto">
        <X /> Clear
      </Button>
    </div>
  )
}
