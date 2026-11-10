import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { Copy, Download, Printer, Smartphone } from 'lucide-react'
import { api, urls } from '@/api/client'
import { PRIORITIES, ROLES } from '@/api/types'
import type { Appearance, DispatchPut } from '@/api/types'
import { PageHeader, PriorityBadge, TagChips } from '@/components/bits'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input, Select } from '@/components/ui/input'
import { Empty, ErrorState, InlineError, Loading } from '@/components/ui/states'
import { useCanEdit } from '@/lib/hooks'
import { useOpenCompany } from '@/lib/openCompany'
import { cn, label } from '@/lib/utils'
import { useTagOptions } from './MapPage'

const byBooth = (a: Appearance, b: Appearance) => (a.booth ?? '').localeCompare(b.booth ?? '', undefined, { numeric: true })

export default function Dispatch() {
  const { slug = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const f = { tag: params.get('tag') ?? '', role: params.get('role') ?? '', priority: params.get('priority') ?? '', assignee: params.get('assignee') ?? '' }
  const canEdit = useCanEdit()
  const qc = useQueryClient()
  const openCompany = useOpenCompany()
  const { options: tagOptions } = useTagOptions(slug)
  const [copied, setCopied] = useState(false)
  const key = ['dispatch', slug, f]
  const q = useQuery({ queryKey: key, queryFn: () => api.dispatch(slug, f) })
  const setParam = (k: string, v: string) => {
    const p = new URLSearchParams(params)
    if (v) p.set(k, v)
    else p.delete(k)
    setParams(p)
  }
  const put = useMutation({
    mutationFn: ({ id, b }: { id: number; b: DispatchPut }) => api.putDispatch(slug, id, b),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['dispatch', slug] })
      qc.invalidateQueries({ queryKey: ['coverage', slug] })
    },
  })

  const assignees = useMemo(
    () => Array.from(new Set((q.data?.halls ?? []).flatMap((h) => h.appearances.map((a) => a.dispatch?.assignee).filter(Boolean) as string[]))).sort(),
    [q.data],
  )
  const person = f.assignee || 'all'
  const phonePath = `/exhibitions/${encodeURIComponent(slug)}/floor/${encodeURIComponent(person)}`
  const total = (q.data?.halls ?? []).reduce((n, h) => n + h.appearances.length, 0)

  return (
    <>
      <PageHeader title="Dispatch" sub={q.data ? `${total.toLocaleString()} booths in ${q.data.halls.length} halls` : 'Category and location view: who visits which booths.'}>
        <Button asChild variant="outline">
          <a href={urls.dispatchExport(slug, f)}><Download /> Export floor list</a>
        </Button>
        <Button variant="outline" onClick={() => window.print()}><Printer /> Print</Button>
        <Button asChild>
          <Link to={phonePath}><Smartphone /> Phone list{f.assignee ? ` · ${f.assignee}` : ''}</Link>
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Copy phone link"
          title="Copy phone link"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(location.origin + phonePath)
              setCopied(true)
              setTimeout(() => setCopied(false), 1500)
            } catch {
              /* clipboard blocked */
            }
          }}
        >
          <Copy />
        </Button>
        {copied ? <span className="text-xs text-muted-foreground">copied</span> : null}
      </PageHeader>

      <div className="no-print mb-3 flex flex-wrap items-center gap-2">
        <Select aria-label="Tag" value={f.tag} onChange={(e) => setParam('tag', e.target.value)} className="max-w-[12rem]">
          <option value="">Any tag</option>
          {tagOptions.map((t) => <option key={t.id} value={t.id}>{t.group ? `${t.group} · ` : ''}{t.name}</option>)}
        </Select>
        <Select aria-label="Role" value={f.role} onChange={(e) => setParam('role', e.target.value)}>
          <option value="">Any role</option>
          {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
        </Select>
        <Select aria-label="Priority" value={f.priority} onChange={(e) => setParam('priority', e.target.value)}>
          <option value="">Any priority</option>
          {PRIORITIES.map((p) => <option key={p} value={p}>{label(p)}</option>)}
        </Select>
        <Select aria-label="Assignee" value={f.assignee} onChange={(e) => setParam('assignee', e.target.value)}>
          <option value="">Anyone</option>
          <option value="none">Unassigned</option>
          {f.assignee && f.assignee !== 'none' && !assignees.includes(f.assignee) ? <option value={f.assignee}>{f.assignee}</option> : null}
          {assignees.map((a) => <option key={a} value={a}>{a}</option>)}
        </Select>
      </div>
      <InlineError error={put.error} />

      {q.isLoading ? <Loading /> : q.isError ? <ErrorState error={q.error} retry={q.refetch} /> : !total ? (
        <Empty title="Nothing to dispatch">Map roles and priorities first, or loosen the filters.</Empty>
      ) : (
        <div className="-mx-4 flex gap-3 overflow-x-auto px-4 pb-4 print:mx-0 print:block print:overflow-visible print:px-0">
          {q.data!.halls.map((h) => (
            <section key={h.hall ?? '—'} className="print-break flex w-72 shrink-0 flex-col rounded-lg border bg-muted/30 print:mb-4 print:w-full print:border-0">
              <header className="sticky top-0 flex items-baseline justify-between rounded-t-lg border-b bg-muted/80 px-3 py-2 backdrop-blur">
                <h2 className="text-sm font-semibold">{h.hall ? `Hall ${h.hall}` : 'No hall'}</h2>
                <span className="text-xs text-muted-foreground">
                  {h.appearances.filter((a) => a.dispatch?.visited).length}/{h.appearances.length} visited
                </span>
              </header>
              <ol className="max-h-[70vh] space-y-1.5 overflow-y-auto p-2 print:max-h-none">
                {[...h.appearances].sort(byBooth).map((a) => (
                  <li key={a.id} className={cn('rounded-md border bg-card p-2 text-sm', a.dispatch?.visited && 'opacity-60')}>
                    <div className="flex items-start gap-2">
                      <Checkbox
                        className="no-print mt-0.5"
                        aria-label={`Visited ${a.company.name}`}
                        checked={!!a.dispatch?.visited}
                        disabled={!canEdit}
                        onCheckedChange={(v) => put.mutate({ id: a.id, b: { visited: v === true } })}
                      />
                      <span className="w-12 shrink-0 font-semibold tabular-nums">{a.booth ?? '—'}</span>
                      <button type="button" className="min-w-0 flex-1 text-left font-medium hover:underline" onClick={() => openCompany(a.company.id)}>
                        {a.company.name}
                      </button>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-1 pl-6">
                      <PriorityBadge priority={a.priority} />
                      <TagChips tags={a.tags} max={3} />
                    </div>
                    {a.dispatch?.note ? <p className="mt-1 pl-6 text-xs text-muted-foreground">{a.dispatch.note}</p> : null}
                    <div className="mt-1 pl-6">
                      {canEdit ? (
                        <AssigneeInput value={a.dispatch?.assignee ?? ''} options={assignees} onSave={(v) => put.mutate({ id: a.id, b: { assignee: v || null } })} />
                      ) : a.dispatch?.assignee ? (
                        <span className="text-xs text-muted-foreground">→ {a.dispatch.assignee}</span>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ol>
            </section>
          ))}
        </div>
      )}
    </>
  )
}

function AssigneeInput({ value, options, onSave }: { value: string; options: string[]; onSave: (v: string) => void }) {
  const [v, setV] = useState(value)
  const id = useMemo(() => `assignees-${Math.random().toString(36).slice(2)}`, [])
  return (
    <>
      <Input
        list={id}
        value={v}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => v !== value && onSave(v.trim())}
        onKeyDown={(e) => e.key === 'Enter' && (e.currentTarget as HTMLInputElement).blur()}
        placeholder="assign…"
        aria-label="Assignee"
        className="no-print h-7 text-xs"
      />
      <datalist id={id}>{options.map((o) => <option key={o} value={o} />)}</datalist>
    </>
  )
}
