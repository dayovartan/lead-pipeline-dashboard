import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Check, Download, ExternalLink, Pencil, Plus, X } from 'lucide-react'
import { api, urls } from '@/api/client'
import type { CompanyDetail, CompanyPatch, Contact, ContactInput } from '@/api/types'
import { useCanEdit } from '@/lib/hooks'
import { cn, label } from '@/lib/utils'
import { KindBadge, MaybeSuggested, PriorityBadge, StatusBadge, TagChips } from '../bits'
import { MeetingsTimeline } from '../MeetingsTimeline'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { Field, Input, Textarea } from '../ui/input'
import { ErrorState, InlineError, Loading } from '../ui/states'
import { Table, TBody, TD, TH, THead, TR } from '../ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs'
import { CasesPanel, FollowButton, LeadPanel, pickLead, SapPanel } from './LeadPanels'
import { ExhibitionPanel } from './ExhibitionPanel'

export type WindowMode = 'leads' | 'exhibitions'

export function CompanyWindow({ id, mode, show, tab, onTab }: { id: number; mode: WindowMode; show?: string; tab?: string; onTab?: (t: string) => void }) {
  const q = useQuery({ queryKey: ['company', id], queryFn: () => api.company(id) })
  const [localTab, setLocalTab] = useState<string | undefined>(tab)
  const setTab = (t: string) => (onTab ? onTab(t) : setLocalTab(t))

  if (q.isLoading) return <Loading className="h-64" />
  if (q.isError || !q.data) return <ErrorState error={q.error} retry={q.refetch} className="h-64" />
  const c = q.data
  const lead = pickLead(c, show)
  const appearance = show ? c.appearances.find((a) => a.convention_slug === show) : undefined
  const current = tab ?? localTab ?? (mode === 'exhibitions' ? (show ? 'show' : 'details') : lead ? 'lead' : 'details')

  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b p-4 pr-12">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold leading-tight">{c.name}</h2>
          <KindBadge kind={c.kind} />
          {lead ? <StatusBadge status={lead.status} /> : null}
        </div>
        <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
          {[c.city, c.country].filter(Boolean).join(', ') || null}
          {c.website ? (
            <a href={normUrl(c.website)} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 hover:text-foreground">
              {c.domain || c.website} <ExternalLink className="size-3" />
            </a>
          ) : null}
          {appearance ? (
            <span>
              Hall {appearance.hall ?? '?'} · Booth {appearance.booth ?? '?'}
            </span>
          ) : null}
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <FollowButton company={c} show={show} />
          <Button asChild size="sm" variant="ghost">
            <a href={urls.companyExport(c.id)}>
              <Download /> Markdown
            </a>
          </Button>
        </div>
      </header>
      <Tabs value={current} onValueChange={setTab} className="flex-1">
        <TabsList>
          {mode === 'exhibitions' && show ? <TabsTrigger value="show">This show</TabsTrigger> : null}
          {mode === 'leads' ? <TabsTrigger value="lead">Lead</TabsTrigger> : null}
          <TabsTrigger value="details">Details</TabsTrigger>
          <TabsTrigger value="contacts">Contacts ({c.contacts.length})</TabsTrigger>
          <TabsTrigger value="appearances">Shows ({c.appearances.length})</TabsTrigger>
          <TabsTrigger value="meetings">Meetings</TabsTrigger>
          {mode === 'leads' ? <TabsTrigger value="sap">SAP</TabsTrigger> : null}
        </TabsList>
        {mode === 'exhibitions' && show ? (
          <TabsContent value="show">
            <ExhibitionPanel company={c} show={show} />
          </TabsContent>
        ) : null}
        {mode === 'leads' ? (
          <TabsContent value="lead" className="space-y-6">
            <LeadPanel company={c} lead={lead} show={show} />
            {lead ? <CasesPanel leadId={lead.id} /> : null}
          </TabsContent>
        ) : null}
        <TabsContent value="details">
          <DetailsTab c={c} />
        </TabsContent>
        <TabsContent value="contacts">
          <ContactsTab c={c} />
        </TabsContent>
        <TabsContent value="appearances">
          <AppearancesTab c={c} />
        </TabsContent>
        <TabsContent value="meetings">
          <MeetingsTimeline
            companyId={c.id}
            leadId={lead?.id}
            appearanceId={appearance?.id}
            contacts={c.contacts}
            defaultPlace={appearance ? [appearance.convention_name ?? appearance.convention_slug, appearance.hall && `Hall ${appearance.hall}`, appearance.booth && `Booth ${appearance.booth}`].filter(Boolean).join(', ') : undefined}
          />
        </TabsContent>
        {mode === 'leads' ? (
          <TabsContent value="sap">
            <SapPanel company={c} />
          </TabsContent>
        ) : null}
      </Tabs>
    </div>
  )
}

export function normUrl(u: string) {
  return /^https?:\/\//i.test(u) ? u : `https://${u}`
}

const DETAIL_FIELDS: { key: keyof CompanyPatch; label: string; multiline?: boolean }[] = [
  { key: 'name', label: 'Name' },
  { key: 'website', label: 'Website' },
  { key: 'domain', label: 'Domain' },
  { key: 'primary_email', label: 'Email' },
  { key: 'phone', label: 'Phone' },
  { key: 'address', label: 'Address' },
  { key: 'city', label: 'City' },
  { key: 'country', label: 'Country' },
  { key: 'profile_url', label: 'Profile URL' },
  { key: 'description', label: 'Description', multiline: true },
]

function DetailsTab({ c }: { c: CompanyDetail }) {
  const canEdit = useCanEdit()
  const qc = useQueryClient()
  const m = useMutation({
    mutationFn: (b: CompanyPatch) => api.patchCompany(c.id, b),
    onSuccess: (data) => {
      if (data && typeof data === 'object' && 'id' in data) qc.setQueryData(['company', c.id], { ...c, ...data })
      qc.invalidateQueries({ queryKey: ['company', c.id] })
      qc.invalidateQueries({ queryKey: ['companies'] })
    },
  })
  return (
    <div className="space-y-4">
      <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-[9rem_1fr]">
        {DETAIL_FIELDS.map((f) => (
          <InlineField
            key={f.key}
            label={f.label}
            value={(c[f.key] as string | null) ?? ''}
            multiline={f.multiline}
            edited={c.edited_fields?.includes(f.key)}
            canEdit={canEdit}
            onSave={(v) => m.mutateAsync({ [f.key]: v || null } as CompanyPatch)}
          />
        ))}
        <InlineField
          label="Categories"
          value={(c.categories ?? []).join('; ')}
          edited={c.edited_fields?.includes('categories')}
          canEdit={canEdit}
          hint="separate with ;"
          onSave={(v) => m.mutateAsync({ categories: v.split(/[;\n]/).map((s) => s.trim()).filter(Boolean) })}
        />
        <dt className="text-sm text-muted-foreground">SAP card</dt>
        <dd className="text-sm">{c.sap_card_code ?? <span className="text-muted-foreground">not linked</span>}</dd>
      </dl>
      <InlineError error={m.error} />
      {c.edited_fields?.length ? (
        <p className="text-xs text-muted-foreground">
          <span className="mr-1 inline-block size-1.5 rounded-full bg-amber-500 align-middle" /> edited in the app — a re-import won't overwrite these.
        </p>
      ) : null}
    </div>
  )
}

function InlineField({
  label: lbl,
  value,
  multiline,
  edited,
  canEdit,
  hint,
  onSave,
}: {
  label: string
  value: string
  multiline?: boolean
  edited?: boolean
  canEdit: boolean
  hint?: string
  onSave: (v: string) => Promise<unknown>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const [busy, setBusy] = useState(false)
  const start = () => {
    setDraft(value)
    setEditing(true)
  }
  const commit = async () => {
    if (draft === value) return setEditing(false)
    setBusy(true)
    try {
      await onSave(draft.trim())
      setEditing(false)
    } catch {
      /* error shown by the parent */
    } finally {
      setBusy(false)
    }
  }
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') setEditing(false)
    if (e.key === 'Enter' && (!multiline || e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      void commit()
    }
  }
  return (
    <>
      <dt className="flex items-center gap-1 pt-1.5 text-sm text-muted-foreground">
        {lbl}
        {edited ? <span className="size-1.5 rounded-full bg-amber-500" title="Edited in the app" /> : null}
      </dt>
      <dd className="min-w-0">
        {editing ? (
          <div className="flex items-start gap-1">
            {multiline ? (
              <Textarea autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} rows={4} />
            ) : (
              <Input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} placeholder={hint} />
            )}
            <Button size="icon" variant="ghost" aria-label="Save" onClick={commit} disabled={busy}>
              <Check />
            </Button>
            <Button size="icon" variant="ghost" aria-label="Cancel" onClick={() => setEditing(false)}>
              <X />
            </Button>
          </div>
        ) : (
          <div className="group flex min-h-9 items-start gap-1 py-1.5 text-sm">
            <span className={cn('min-w-0 whitespace-pre-wrap break-words', !value && 'text-muted-foreground')}>{value || '—'}</span>
            {canEdit ? (
              <button type="button" onClick={start} aria-label={`Edit ${lbl}`} className="ml-1 rounded p-0.5 text-muted-foreground opacity-60 hover:bg-accent hover:opacity-100 focus:opacity-100 sm:opacity-0 sm:group-hover:opacity-100">
                <Pencil className="size-3.5" />
              </button>
            ) : null}
          </div>
        )}
      </dd>
    </>
  )
}

function ContactsTab({ c }: { c: CompanyDetail }) {
  const canEdit = useCanEdit()
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<number | null>(null)
  return (
    <div className="space-y-3">
      {canEdit && !adding ? (
        <Button size="sm" onClick={() => setAdding(true)}>
          <Plus /> Add contact
        </Button>
      ) : null}
      {adding ? <ContactForm companyId={c.id} onDone={() => setAdding(false)} /> : null}
      {c.contacts.length === 0 && !adding ? <p className="text-sm text-muted-foreground">No contacts yet.</p> : null}
      <ul className="divide-y rounded-md border">
        {c.contacts.map((p) =>
          editing === p.id ? (
            <li key={p.id} className="p-2">
              <ContactForm companyId={c.id} contact={p} onDone={() => setEditing(null)} />
            </li>
          ) : (
            <li key={p.id} className="flex items-start justify-between gap-2 p-3 text-sm">
              <div className="min-w-0">
                <Link to={`/leads/contacts/${p.id}`} className="font-medium hover:underline">
                  {p.name || p.email || 'Unnamed'}
                </Link>
                {p.title ? <span className="text-muted-foreground"> · {p.title}</span> : null}
                <div className="flex flex-wrap gap-x-3 text-muted-foreground">
                  {p.email ? <a href={`mailto:${p.email}`} className="hover:text-foreground">{p.email}</a> : null}
                  {p.phone ? <a href={`tel:${p.phone}`} className="hover:text-foreground">{p.phone}</a> : null}
                </div>
              </div>
              {canEdit ? (
                <Button size="icon" variant="ghost" aria-label={`Edit ${p.name}`} onClick={() => setEditing(p.id)}>
                  <Pencil />
                </Button>
              ) : null}
            </li>
          ),
        )}
      </ul>
    </div>
  )
}

export function ContactForm({ companyId, contact, onDone }: { companyId: number; contact?: Contact; onDone: () => void }) {
  const qc = useQueryClient()
  const [v, setV] = useState<ContactInput>({ name: contact?.name ?? '', title: contact?.title ?? '', email: contact?.email ?? '', phone: contact?.phone ?? '' })
  const m = useMutation({
    mutationFn: () => {
      const body = Object.fromEntries(Object.entries(v).map(([k, x]) => [k, (x ?? '').trim() || null])) as ContactInput
      return contact ? api.patchContact(contact.id, body) : api.addContact(companyId, body)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['company', companyId] })
      onDone()
    },
  })
  const set = (k: keyof ContactInput) => (e: React.ChangeEvent<HTMLInputElement>) => setV({ ...v, [k]: e.target.value })
  return (
    <form
      className="grid gap-2 rounded-md border bg-card p-3 sm:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault()
        m.mutate()
      }}
    >
      <Field label="Name"><Input autoFocus value={v.name ?? ''} onChange={set('name')} /></Field>
      <Field label="Title"><Input value={v.title ?? ''} onChange={set('title')} /></Field>
      <Field label="Email"><Input type="email" value={v.email ?? ''} onChange={set('email')} /></Field>
      <Field label="Phone"><Input type="tel" value={v.phone ?? ''} onChange={set('phone')} /></Field>
      <div className="flex items-center justify-end gap-2 sm:col-span-2">
        <InlineError error={m.error} />
        <Button variant="ghost" onClick={onDone}>Cancel</Button>
        <Button type="submit" disabled={m.isPending || !(v.name || v.email)}>{contact ? 'Save' : 'Add contact'}</Button>
      </div>
    </form>
  )
}

function AppearancesTab({ c }: { c: CompanyDetail }) {
  if (!c.appearances.length) return <p className="text-sm text-muted-foreground">Not at any show yet.</p>
  return (
    <Table>
      <THead>
        <TR>
          <TH>Show</TH>
          <TH>Hall / booth</TH>
          <TH>Role</TH>
          <TH>Priority</TH>
          <TH>Tags</TH>
          <TH>Visit</TH>
        </TR>
      </THead>
      <TBody>
        {c.appearances.map((a) => (
          <TR key={a.id ?? a.convention_slug}>
            <TD>
              <Link className="hover:underline" to={`/exhibitions/${encodeURIComponent(a.convention_slug)}/map`}>
                {a.convention_name ?? a.convention_slug}
              </Link>
            </TD>
            <TD className="whitespace-nowrap">{[a.hall, a.booth].filter(Boolean).join(' / ') || a.hall_booth_raw || '—'}</TD>
            <TD><MaybeSuggested kind="role" value={a.role} suggested={a.mapping?.suggested_role} /></TD>
            <TD>{a.priority ? <PriorityBadge priority={a.priority} /> : <MaybeSuggested kind="priority" value={null} suggested={a.mapping?.suggested_priority} />}</TD>
            <TD><TagChips tags={a.tags ?? []} max={3} /></TD>
            <TD>
              {a.dispatch?.visited ? <Badge variant="success">visited</Badge> : a.met_at_booth ? <Badge variant="success">met</Badge> : <span className="text-xs text-muted-foreground">{a.dispatch?.assignee ? label(a.dispatch.assignee) : '—'}</span>}
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  )
}
