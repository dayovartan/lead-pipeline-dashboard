import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import { ArrowRight, Link2, Search, Star, Unlink } from 'lucide-react'
import { api } from '@/api/client'
import { isUnavailable, LEAD_STATUSES } from '@/api/types'
import type { CaseSuggestion, CompanyDetail, CompanyLeadBrief, LeadCase, LeadPatch, LeadStatus } from '@/api/types'
import { useCanEdit, useMe } from '@/lib/hooks'
import { useOpenCompany } from '@/lib/openCompany'
import { fmtDate, fmtDateTime, isOverdue, label } from '@/lib/utils'
import { KeyValue } from '../bits'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { Field, Input, Select, Textarea } from '../ui/input'
import { Empty, InlineError, Loading, Spinner, Unavailable } from '../ui/states'

/** The lead for the current show if there is one, else the most recently updated. */
export function pickLead(c: CompanyDetail, show?: string): CompanyLeadBrief | undefined {
  if (!c.leads?.length) return undefined
  if (show) {
    const app = c.appearances.find((a) => a.convention_slug === show)
    const m = c.leads.find((l) => l.convention_slug === show || (app && l.appearance_id === app.id))
    if (m) return m
  }
  return [...c.leads].sort((a, b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? ''))[0]
}

function invalidateLead(qc: ReturnType<typeof useQueryClient>, companyId: number) {
  qc.invalidateQueries({ queryKey: ['company', companyId] })
  qc.invalidateQueries({ queryKey: ['companies'] })
  qc.invalidateQueries({ queryKey: ['leads'] })
  qc.invalidateQueries({ queryKey: ['appearances'] })
}

export function FollowButton({ company, show, size = 'sm' }: { company: CompanyDetail; show?: string; size?: 'sm' | 'default' }) {
  const canEdit = useCanEdit()
  const qc = useQueryClient()
  const { data: me } = useMe()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const openCompany = useOpenCompany()
  const lead = pickLead(company, show)
  const appearance = show ? company.appearances.find((a) => a.convention_slug === show) : undefined
  const follow = useMutation({
    mutationFn: () => api.follow(company.id, { owner: me?.name || me?.email, appearance_id: appearance?.id }),
    onSuccess: () => invalidateLead(qc, company.id),
  })
  if (lead) {
    const view = () =>
      pathname.startsWith('/leads')
        ? openCompany(company.id, { tab: 'lead' })
        : navigate(`/leads/companies?${new URLSearchParams({ ...(show ? { show } : {}), company: String(company.id), tab: 'lead' })}`)
    return (
      <Button size={size} variant="outline" onClick={view}>
        View lead <ArrowRight />
      </Button>
    )
  }
  if (!canEdit) return null
  return (
    <>
      <Button size={size} onClick={() => follow.mutate()} disabled={follow.isPending}>
        <Star /> {follow.isPending ? 'Following…' : 'Follow'}
      </Button>
      <InlineError error={follow.error} />
    </>
  )
}

export function LeadPanel({ company, lead, show }: { company: CompanyDetail; lead?: CompanyLeadBrief; show?: string }) {
  const canEdit = useCanEdit()
  const qc = useQueryClient()
  const [notes, setNotes] = useState(lead?.notes ?? '')
  const [owner, setOwner] = useState(lead?.owner ?? '')
  useEffect(() => {
    setNotes(lead?.notes ?? '')
    setOwner(lead?.owner ?? '')
  }, [lead?.id, lead?.notes, lead?.owner])
  const m = useMutation({
    mutationFn: (b: LeadPatch) => api.patchLead(lead!.id, b),
    onSuccess: () => invalidateLead(qc, company.id),
  })
  const activity = useQuery({ queryKey: ['leads', 'activity', lead?.id], queryFn: () => api.leadActivity(lead!.id), enabled: !!lead })

  if (!lead)
    return (
      <Empty title="Not followed yet">
        <p className="mb-3">Following creates a lead on the board{show ? ` for ${show}` : ''}.</p>
        <FollowButton company={company} show={show} size="default" />
      </Empty>
    )

  return (
    <section className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Status">
          <Select value={lead.status} disabled={!canEdit || m.isPending} onChange={(e) => m.mutate({ status: e.target.value as LeadStatus })}>
            {LEAD_STATUSES.map((s) => (
              <option key={s} value={s}>
                {label(s)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Owner">
          <Input value={owner} disabled={!canEdit} onChange={(e) => setOwner(e.target.value)} onBlur={() => owner !== (lead.owner ?? '') && m.mutate({ owner: owner || null })} />
        </Field>
        <Field label="Follow-up">
          <Input
            type="date"
            value={lead.follow_up_on ?? ''}
            disabled={!canEdit}
            onChange={(e) => m.mutate({ follow_up_on: e.target.value || null })}
            className={isOverdue(lead.follow_up_on) ? 'border-red-500 text-red-600 dark:text-red-400' : undefined}
          />
        </Field>
      </div>
      <Field label="Notes">
        <Textarea value={notes} disabled={!canEdit} rows={3} onChange={(e) => setNotes(e.target.value)} onBlur={() => notes !== (lead.notes ?? '') && m.mutate({ notes: notes || null })} />
      </Field>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        {m.isPending ? <Spinner /> : null}
        <InlineError error={m.error} />
      </div>
      {activity.data?.length ? (
        <details className="text-sm">
          <summary className="cursor-pointer text-muted-foreground">Activity ({activity.data.length})</summary>
          <ul className="mt-2 space-y-1">
            {activity.data.map((a, i) => (
              <li key={i} className="text-xs text-muted-foreground">
                <span className="tabular-nums">{fmtDateTime(a.at)}</span> · {a.actor ?? 'system'} · {label(a.kind)}
                {a.data && Object.keys(a.data).length ? <code className="ml-1">{JSON.stringify(a.data)}</code> : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  )
}

function asList<T>(r: unknown): T[] | null {
  if (Array.isArray(r)) return r as T[]
  if (r && typeof r === 'object' && Array.isArray((r as { items?: unknown }).items)) return (r as { items: T[] }).items
  return null
}

export function CasesPanel({ leadId }: { leadId: number }) {
  const canEdit = useCanEdit()
  const qc = useQueryClient()
  const [caseId, setCaseId] = useState('')
  const cases = useQuery({ queryKey: ['leads', 'cases', leadId], queryFn: () => api.leadCases(leadId), retry: false })
  const sugg = useQuery({ queryKey: ['leads', 'suggestions', leadId], queryFn: () => api.suggestions(leadId), retry: false, staleTime: 5 * 60_000 })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['leads', 'cases', leadId] })
    qc.invalidateQueries({ queryKey: ['leads', 'suggestions', leadId] })
    qc.invalidateQueries({ queryKey: ['leads'] })
  }
  const link = useMutation({ mutationFn: (id: string) => api.linkCase(leadId, id), onSuccess: () => (setCaseId(''), refresh()) })
  const unlink = useMutation({ mutationFn: (id: string) => api.unlinkCase(leadId, id), onSuccess: refresh })
  const accept = useMutation({ mutationFn: (sid: number) => api.acceptSuggestion(leadId, sid), onSuccess: refresh })
  const dismiss = useMutation({ mutationFn: (sid: number) => api.dismissSuggestion(leadId, sid), onSuccess: refresh })

  const caseList = isUnavailable(cases.data) ? null : asList<LeadCase>(cases.data)
  const suggList = isUnavailable(sugg.data) ? null : asList<CaseSuggestion>(sugg.data)?.filter((s) => s.status === 'pending' || !s.status)

  return (
    <section className="space-y-4">
      <div>
        <h3 className="mb-2 text-sm font-semibold">Linked cases</h3>
        {cases.isLoading ? <Loading /> : null}
        {cases.isError ? <Unavailable what="Cases" reason="The cases lookup failed." /> : null}
        {isUnavailable(cases.data) ? <Unavailable what="Cases" reason={cases.data.reason} /> : null}
        {caseList && caseList.length === 0 ? <p className="text-sm text-muted-foreground">No cases linked.</p> : null}
        <ul className="space-y-2">
          {caseList?.map((c) => (
            <li key={c.loop_case_id} className="rounded-md border p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <code className="font-medium">{c.loop_case_id}</code>
                <Badge variant={c.how === 'suggested' ? 'suggested' : 'outline'}>{c.how}</Badge>
                <span className="text-xs text-muted-foreground">
                  {fmtDate(c.linked_at)}
                  {c.linked_by ? ` · ${c.linked_by}` : ''}
                </span>
                {canEdit ? (
                  <Button size="sm" variant="ghost" className="ml-auto" onClick={() => unlink.mutate(c.loop_case_id)} disabled={unlink.isPending}>
                    <Unlink /> Unlink
                  </Button>
                ) : null}
              </div>
              {c.available === false ? (
                <div className="mt-2">
                  <Unavailable what="Live case state" />
                </div>
              ) : (
                <div className="mt-2 grid gap-3 sm:grid-cols-3">
                  {(['story', 'quotation', 'order'] as const).map((k) =>
                    c[k] ? (
                      <div key={k}>
                        <p className="mb-1 text-xs font-medium uppercase text-muted-foreground">{k}</p>
                        <KeyValue data={c[k]} />
                      </div>
                    ) : null,
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
        {canEdit && !isUnavailable(cases.data) ? (
          <form
            className="mt-3 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              if (caseId.trim()) link.mutate(caseId.trim())
            }}
          >
            <Input value={caseId} onChange={(e) => setCaseId(e.target.value)} placeholder="intake-… case id" className="max-w-xs" />
            <Button type="submit" variant="outline" disabled={!caseId.trim() || link.isPending}>
              <Link2 /> Link case
            </Button>
          </form>
        ) : null}
        <InlineError error={link.error ?? unlink.error} />
      </div>
      <div>
        <h3 className="mb-2 text-sm font-semibold">Suggested cases</h3>
        {sugg.isLoading ? <Loading label="Looking for matching cases…" /> : null}
        {sugg.isError ? <Unavailable what="Case suggestions" reason="The lookup failed." /> : null}
        {isUnavailable(sugg.data) ? <Unavailable what="Case suggestions" reason={sugg.data.reason} /> : null}
        {suggList && suggList.length === 0 ? <p className="text-sm text-muted-foreground">No suggestions.</p> : null}
        <ul className="space-y-2">
          {suggList?.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-2 rounded-md border border-dashed p-2 text-sm">
              <code>{s.loop_case_id}</code>
              <Badge variant="secondary">matched on {label(s.reason)}</Badge>
              {canEdit ? (
                <span className="ml-auto flex gap-1">
                  <Button size="sm" onClick={() => accept.mutate(s.id)} disabled={accept.isPending}>
                    Accept
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => dismiss.mutate(s.id)} disabled={dismiss.isPending}>
                    Dismiss
                  </Button>
                </span>
              ) : null}
            </li>
          ))}
        </ul>
        <InlineError error={accept.error ?? dismiss.error} />
      </div>
    </section>
  )
}

export function SapPanel({ company }: { company: CompanyDetail }) {
  const canEdit = useCanEdit()
  const qc = useQueryClient()
  const linked = !!company.sap_card_code
  const isSupplier = company.kind === 'supplier' || company.kind === 'both'
  const card = useQuery({ queryKey: ['sap-card', company.id, company.sap_card_code], queryFn: () => api.sapCard(company.id), enabled: linked, retry: false })
  const prices = useQuery({ queryKey: ['supplier-prices', company.id], queryFn: () => api.supplierPrices(company.id), enabled: isSupplier, retry: false })
  const [q, setQ] = useState(company.name)
  const [searchQ, setSearchQ] = useState<string | null>(null)
  const search = useQuery({ queryKey: ['sap-search', company.id, searchQ], queryFn: () => api.sapSearch(company.id, searchQ!), enabled: !!searchQ, retry: false })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['company', company.id] })
    qc.invalidateQueries({ queryKey: ['companies'] })
  }
  const link = useMutation({ mutationFn: (code: string) => api.sapLink(company.id, code), onSuccess: refresh })
  const unlink = useMutation({ mutationFn: () => api.sapUnlink(company.id), onSuccess: refresh })

  const results: Record<string, unknown>[] = search.data && !isUnavailable(search.data) ? (search.data.matches ?? asList<Record<string, unknown>>(search.data) ?? []) : []

  return (
    <div className="space-y-6">
      <section>
        <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
          SAP card {linked ? <code className="font-normal">{company.sap_card_code}</code> : null}
          {linked && canEdit ? (
            <Button size="sm" variant="ghost" className="ml-auto" onClick={() => unlink.mutate()} disabled={unlink.isPending}>
              <Unlink /> Unlink
            </Button>
          ) : null}
        </h3>
        {linked ? (
          card.isLoading ? (
            <Loading />
          ) : card.isError ? (
            <Unavailable what="SAP card" reason="The SAP lookup failed." />
          ) : isUnavailable(card.data) ? (
            <Unavailable what="SAP card" reason={card.data.reason} />
          ) : (
            <div className="space-y-2">
              {card.data?.card ? <KeyValue data={card.data.card} /> : null}
              {card.data?.text ? <pre className="whitespace-pre-wrap rounded-md bg-muted/50 p-2 text-xs">{card.data.text}</pre> : null}
              {!card.data?.card && !card.data?.text ? <p className="text-sm text-muted-foreground">SAP returned nothing for this card.</p> : null}
            </div>
          )
        ) : (
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">Not linked to a SAP business partner.</p>
            {canEdit ? (
              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault()
                  setSearchQ(q.trim() || null)
                }}
              >
                <Input value={q} onChange={(e) => setQ(e.target.value)} className="max-w-xs" aria-label="SAP search" />
                <Button type="submit" variant="outline">
                  <Search /> Find in SAP
                </Button>
              </form>
            ) : null}
            {search.isFetching ? <Loading label="Searching SAP…" /> : null}
            {search.isError ? <Unavailable what="SAP search" reason="The SAP lookup failed." /> : null}
            {isUnavailable(search.data) ? <Unavailable what="SAP search" reason={search.data.reason} /> : null}
            {searchQ && !search.isFetching && search.data && !isUnavailable(search.data) && results.length === 0 ? (
              <p className="text-sm text-muted-foreground">No SAP matches.</p>
            ) : null}
            {search.data && !isUnavailable(search.data) && search.data.more ? <p className="text-xs text-muted-foreground">More matches exist; refine the search.</p> : null}
            <ul className="divide-y rounded-md border empty:hidden">
              {results.map((r, i) => {
                const code = String(r.card_code ?? r.CardCode ?? r.code ?? '')
                return (
                  <li key={code || i} className="flex items-center gap-2 p-2 text-sm">
                    <code>{code}</code>
                    <span className="min-w-0 flex-1 truncate">{String(r.name ?? r.card_name ?? r.CardName ?? '')}</span>
                    {canEdit && code ? (
                      <Button size="sm" variant="outline" onClick={() => link.mutate(code)} disabled={link.isPending}>
                        Link
                      </Button>
                    ) : null}
                  </li>
                )
              })}
            </ul>
          </div>
        )}
        <InlineError error={link.error ?? unlink.error} />
      </section>
      {isSupplier ? (
        <section>
          <h3 className="mb-2 text-sm font-semibold">Latest supplier prices</h3>
          {prices.isLoading ? (
            <Loading />
          ) : prices.isError ? (
            <Unavailable what="Supplier prices" reason="The SAP lookup failed." />
          ) : isUnavailable(prices.data) ? (
            <Unavailable what="Supplier prices" reason={prices.data.reason} />
          ) : (
            <PriceTable data={prices.data} />
          )}
        </section>
      ) : null}
    </div>
  )
}

function PriceTable({ data }: { data: unknown }) {
  const rows =
    asList<Record<string, unknown>>((data as { prices?: unknown })?.prices) ??
    asList<Record<string, unknown>>(data) ??
    null
  if (!rows) return <KeyValue data={data as Record<string, unknown>} omit={['available', 'query', 'item_code']} />
  if (!rows.length) return <p className="text-sm text-muted-foreground">No recent prices.</p>
  const cols = Array.from(new Set(rows.flatMap((r) => Object.keys(r)))).slice(0, 8)
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-sm">
        <thead className="bg-muted/50">
          <tr>{cols.map((c) => <th key={c} className="px-2 py-1.5 text-left text-xs font-medium text-muted-foreground">{label(c)}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t">
              {cols.map((c) => <td key={c} className="px-2 py-1.5">{r[c] === null || r[c] === undefined ? '' : String(r[c])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
