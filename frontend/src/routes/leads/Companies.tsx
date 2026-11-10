import { useEffect, useMemo, useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { flexRender, getCoreRowModel, useReactTable, type ColumnDef, type SortingState } from '@tanstack/react-table'
import { ArrowDown, ArrowUp, ArrowRight, Star, X } from 'lucide-react'
import { api } from '@/api/client'
import { KINDS, ROLES } from '@/api/types'
import type { CompanyListItem } from '@/api/types'
import { KindBadge, PageHeader, Pagination, StatusBadge } from '@/components/bits'
import { Button } from '@/components/ui/button'
import { Input, Select } from '@/components/ui/input'
import { Empty, ErrorState, InlineError, Loading, Spinner } from '@/components/ui/states'
import { TD, TH, TR } from '@/components/ui/table'
import { useCanEdit, useDebounced, useMe } from '@/lib/hooks'
import { useOpenCompany } from '@/lib/openCompany'
import { cn } from '@/lib/utils'

const PAGE_SIZE = 50
const FILTER_KEYS = ['q', 'role', 'kind', 'country', 'category', 'tag', 'has_lead', 'sap_linked', 'met'] as const

export default function Companies() {
  const [params, setParams] = useSearchParams()
  const show = params.get('show') ?? ''
  const page = Number(params.get('page') ?? 1) || 1
  const sort = params.get('sort') ?? 'name'
  const f = Object.fromEntries(FILTER_KEYS.map((k) => [k, params.get(k) ?? ''])) as Record<(typeof FILTER_KEYS)[number], string>
  const [qText, setQText] = useState(f.q)
  const dq = useDebounced(qText, 300)
  const canEdit = useCanEdit()
  const openCompany = useOpenCompany()

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

  const query = useQuery({
    queryKey: ['companies', { show, page, sort, ...f }],
    queryFn: () => api.companies({ ...f, convention: show, sort, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })
  const facets = useQuery({ queryKey: ['facets', show], queryFn: () => api.facets(show || undefined), staleTime: 60_000 })
  const tags = useQuery({ queryKey: ['tags', show], queryFn: () => api.tags(show), enabled: !!show, staleTime: 60_000 })

  const sorting: SortingState = [{ id: sort.replace(/^-/, ''), desc: sort.startsWith('-') }]
  const columns = useMemo<ColumnDef<CompanyListItem>[]>(
    () => [
      {
        id: 'name',
        header: 'Company',
        enableSorting: true,
        cell: ({ row: { original: c } }) => (
          <div className="min-w-[12rem]">
            <div className="font-medium">{c.name}</div>
            {c.domain ? <div className="text-xs text-muted-foreground">{c.domain}</div> : null}
          </div>
        ),
      },
      { id: 'kind', header: 'Kind', enableSorting: false, cell: ({ row }) => <KindBadge kind={row.original.kind} /> },
      {
        id: 'country',
        header: 'Country',
        enableSorting: true,
        cell: ({ row: { original: c } }) => <span className="whitespace-nowrap">{[c.country, c.city].filter(Boolean).join(' · ')}</span>,
      },
      {
        id: 'booth',
        header: show ? 'Hall / booth' : 'Shows',
        enableSorting: false,
        cell: ({ row: { original: c } }) => {
          if (!show) return <span className="text-muted-foreground">{c.appearances.length || '—'}</span>
          const a = c.appearances.find((x) => x.convention_slug === show)
          return <span className="whitespace-nowrap tabular-nums">{a ? [a.hall, a.booth].filter(Boolean).join(' / ') : '—'}</span>
        },
      },
      {
        id: 'categories',
        header: 'Categories',
        enableSorting: false,
        cell: ({ row: { original: c } }) => (
          <span className="line-clamp-2 max-w-[22rem] text-xs text-muted-foreground" title={c.categories.join('; ')}>
            {c.categories.slice(0, 4).join(' · ')}
            {c.categories.length > 4 ? ` +${c.categories.length - 4}` : ''}
          </span>
        ),
      },
      { id: 'sap', header: 'SAP', enableSorting: false, cell: ({ row }) => (row.original.sap_card_code ? <code className="text-xs">{row.original.sap_card_code}</code> : null) },
      {
        id: 'lead',
        header: '',
        enableSorting: false,
        cell: ({ row: { original: c } }) => <FollowCell c={c} canEdit={canEdit} onView={() => openCompany(c.id, { tab: 'lead' })} />,
      },
    ],
    [show, canEdit, openCompany],
  )

  const data = query.data
  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    state: { sorting },
    manualSorting: true,
    manualPagination: true,
    manualFiltering: true,
    rowCount: data?.total ?? 0,
    getCoreRowModel: getCoreRowModel(),
    onSortingChange: (upd) => {
      const next = typeof upd === 'function' ? upd(sorting) : upd
      const s = next[0]
      setParam('sort', s ? `${s.desc ? '-' : ''}${s.id}` : 'name')
    },
  })

  const active = FILTER_KEYS.filter((k) => k !== 'q' && f[k])
  const tagOptions = tags.data ? [...tags.data.groups.flatMap((g) => g.tags.map((t) => ({ ...t, g: g.name }))), ...tags.data.ungrouped.map((t) => ({ ...t, g: '' }))] : []

  return (
    <>
      <PageHeader title="Companies" sub={data ? `${data.total.toLocaleString()} companies${show ? ` at ${show}` : ''}` : ' '}>
        {query.isFetching && !query.isLoading ? <Spinner className="text-muted-foreground" /> : null}
      </PageHeader>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Input value={qText} onChange={(e) => setQText(e.target.value)} placeholder="Filter by name, domain, contact…" className="w-full sm:w-64" aria-label="Filter companies" />
        <Select aria-label="Role" value={f.role} onChange={(e) => setParam('role', e.target.value)}>
          <option value="">Any role</option>
          {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
        </Select>
        <Select aria-label="Kind" value={f.kind} onChange={(e) => setParam('kind', e.target.value)}>
          <option value="">Any kind</option>
          {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
        </Select>
        <Select aria-label="Country" value={f.country} onChange={(e) => setParam('country', e.target.value)} className="max-w-[10rem]">
          <option value="">Any country</option>
          {facets.data?.countries.map((c) => <option key={c.value} value={c.value}>{c.value} ({c.count})</option>)}
        </Select>
        <Select aria-label="Category" value={f.category} onChange={(e) => setParam('category', e.target.value)} className="max-w-[12rem]">
          <option value="">Any category</option>
          {facets.data?.categories.map((c) => <option key={c.value} value={c.value}>{c.value} ({c.count})</option>)}
        </Select>
        {show ? (
          <Select aria-label="Tag" value={f.tag} onChange={(e) => setParam('tag', e.target.value)} className="max-w-[10rem]">
            <option value="">Any tag</option>
            {tagOptions.map((t) => <option key={t.id} value={t.id}>{t.g ? `${t.g} · ` : ''}{t.name}</option>)}
          </Select>
        ) : null}
        <TriSelect label="Lead" value={f.has_lead} onChange={(v) => setParam('has_lead', v)} yes="Followed" no="Not followed" />
        <TriSelect label="SAP" value={f.sap_linked} onChange={(v) => setParam('sap_linked', v)} yes="SAP-linked" no="Not in SAP" />
        <TriSelect label="Met" value={f.met} onChange={(v) => setParam('met', v)} yes="Met" no="Not met" />
        {active.length ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              const p = new URLSearchParams(params)
              active.forEach((k) => p.delete(k))
              p.delete('page')
              setParams(p)
            }}
          >
            <X /> Clear filters
          </Button>
        ) : null}
      </div>

      {query.isLoading ? <Loading /> : query.isError ? <ErrorState error={query.error} retry={query.refetch} /> : data && data.items.length === 0 ? (
        <Empty title="No companies match">Try fewer filters{show ? ' or switch to All shows' : ''}.</Empty>
      ) : (
        <>
          <div className="relative w-full overflow-x-auto rounded-md border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                {table.getHeaderGroups().map((hg) => (
                  <tr key={hg.id} className="border-b">
                    {hg.headers.map((h) => {
                      const s = h.column.getIsSorted()
                      return (
                        <TH key={h.id} aria-sort={s ? (s === 'desc' ? 'descending' : 'ascending') : undefined}>
                          {h.column.getCanSort() ? (
                            <button type="button" className="inline-flex items-center gap-1 hover:text-foreground" onClick={h.column.getToggleSortingHandler()}>
                              {flexRender(h.column.columnDef.header, h.getContext())}
                              {s === 'asc' ? <ArrowUp className="size-3" /> : s === 'desc' ? <ArrowDown className="size-3" /> : null}
                            </button>
                          ) : (
                            flexRender(h.column.columnDef.header, h.getContext())
                          )}
                        </TH>
                      )
                    })}
                  </tr>
                ))}
              </thead>
              <tbody className={cn(query.isPlaceholderData && 'opacity-60')}>
                {table.getRowModel().rows.map((r) => (
                  <TR
                    key={r.id}
                    tabIndex={0}
                    className="cursor-pointer hover:bg-accent/50 focus-visible:bg-accent/50"
                    onClick={() => openCompany(r.original.id)}
                    onKeyDown={(e) => e.key === 'Enter' && e.currentTarget === e.target && openCompany(r.original.id)}
                  >
                    {r.getVisibleCells().map((c) => (
                      <TD key={c.id}>{flexRender(c.column.columnDef.cell, c.getContext())}</TD>
                    ))}
                  </TR>
                ))}
              </tbody>
            </table>
          </div>
          {data ? <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPage={(p) => setParam('page', String(p), true)} /> : null}
        </>
      )}
    </>
  )
}

function TriSelect({ label, value, onChange, yes, no }: { label: string; value: string; onChange: (v: string) => void; yes: string; no: string }) {
  return (
    <Select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{label}: any</option>
      <option value="true">{yes}</option>
      <option value="false">{no}</option>
    </Select>
  )
}

function FollowCell({ c, canEdit, onView }: { c: CompanyListItem; canEdit: boolean; onView: () => void }) {
  const qc = useQueryClient()
  const { data: me } = useMe()
  const m = useMutation({
    mutationFn: () => api.follow(c.id, { owner: me?.name || me?.email }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['companies'] })
      qc.invalidateQueries({ queryKey: ['leads'] })
      qc.invalidateQueries({ queryKey: ['company', c.id] })
    },
  })
  const stop = (e: React.SyntheticEvent) => e.stopPropagation()
  if (c.lead_id)
    return (
      <div className="flex items-center justify-end gap-2" onClick={stop}>
        <StatusBadge status={c.lead_status} />
        <Button size="sm" variant="outline" onClick={onView}>
          View lead <ArrowRight />
        </Button>
      </div>
    )
  if (!canEdit) return null
  return (
    <div className="flex items-center justify-end gap-2" onClick={stop}>
      <InlineError error={m.error} />
      <Button size="sm" onClick={() => m.mutate()} disabled={m.isPending}>
        <Star /> Follow
      </Button>
    </div>
  )
}
