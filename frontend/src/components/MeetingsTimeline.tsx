import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarDays, Download, MapPin, Plus, Trash2, Users } from 'lucide-react'
import { api, urls } from '@/api/client'
import type { Contact, Meeting, MeetingCreate } from '@/api/types'
import { useCanEdit, useMe } from '@/lib/hooks'
import { cn, fmtDate, fmtDateTime, isOverdue, todayIso } from '@/lib/utils'
import { MdEditor, MdView } from './Markdown'
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { Checkbox } from './ui/checkbox'
import { Field, Input } from './ui/input'
import { Empty, ErrorState, InlineError, Loading } from './ui/states'

type Props = {
  companyId?: number
  contactId?: number
  leadId?: number
  appearanceId?: number
  contacts?: Contact[]
  defaultPlace?: string
}

export function MeetingsTimeline({ companyId, contactId, leadId, appearanceId, contacts = [], defaultPlace }: Props) {
  const canEdit = useCanEdit()
  const [adding, setAdding] = useState(false)
  const key = ['meetings', { companyId, contactId }]
  const q = useQuery({
    queryKey: key,
    queryFn: () => api.meetings({ company_id: companyId, contact_id: contactId }),
    enabled: !!(companyId || contactId),
  })

  return (
    <div className="space-y-4">
      {canEdit && companyId ? (
        adding ? (
          <MeetingEditor
            companyId={companyId}
            leadId={leadId}
            appearanceId={appearanceId}
            contacts={contacts}
            defaultPlace={defaultPlace}
            onDone={() => setAdding(false)}
          />
        ) : (
          <Button size="sm" onClick={() => setAdding(true)}>
            <Plus /> Add meeting
          </Button>
        )
      ) : null}
      {q.isLoading ? <Loading /> : q.isError ? <ErrorState error={q.error} retry={q.refetch} /> : null}
      {q.data && q.data.length === 0 && !adding ? <Empty title="No meetings yet">Notes from the floor and meetings show up here, newest first.</Empty> : null}
      <ol className="relative space-y-4 border-l pl-4">
        {q.data?.map((m) => <MeetingItem key={m.id} m={m} canEdit={canEdit} />)}
      </ol>
    </div>
  )
}

function MeetingItem({ m, canEdit }: { m: Meeting; canEdit: boolean }) {
  const qc = useQueryClient()
  const [newAction, setNewAction] = useState('')
  const toggle = useMutation({
    mutationFn: ({ aid, done }: { aid: number; done: boolean }) => api.patchAction(m.id, aid, { done }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['meetings'] })
      qc.invalidateQueries({ queryKey: ['leads'] })
    },
  })
  const add = useMutation({
    mutationFn: (text: string) => api.addAction(m.id, { text }),
    onSuccess: () => {
      setNewAction('')
      qc.invalidateQueries({ queryKey: ['meetings'] })
      qc.invalidateQueries({ queryKey: ['leads'] })
    },
  })
  return (
    <li className="relative">
      <span className={cn('absolute -left-[1.4rem] top-1.5 size-2.5 rounded-full border-2 border-background', m.source === 'floor' ? 'bg-amber-500' : 'bg-primary')} />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span className="flex items-center gap-1 font-medium">
          <CalendarDays className="size-3.5 text-muted-foreground" />
          {m.starts_at ? fmtDateTime(m.starts_at) : fmtDate(m.met_on)}
        </span>
        {m.place ? (
          <span className="flex items-center gap-1 text-muted-foreground">
            <MapPin className="size-3.5" /> {m.place}
          </span>
        ) : null}
        {m.met_by?.length ? (
          <span className="flex items-center gap-1 text-muted-foreground">
            <Users className="size-3.5" /> {m.met_by.join(', ')}
          </span>
        ) : null}
        {m.source && m.source !== 'app' ? <Badge variant="outline">{m.source}</Badge> : null}
        <a href={urls.meetingExport(m.id)} className="ml-auto text-muted-foreground hover:text-foreground" title="Export to Obsidian markdown" aria-label="Export markdown">
          <Download className="size-3.5" />
        </a>
      </div>
      {m.contacts?.length ? <p className="mt-0.5 text-xs text-muted-foreground">With {m.contacts.map((c) => c.name).join(', ')}</p> : null}
      {m.summary_md ? (
        <div className="mt-2 rounded-md border bg-card p-3">
          <MdView source={m.summary_md} />
        </div>
      ) : null}
      {m.actions?.length || canEdit ? (
        <ul className="mt-2 space-y-1">
          {m.actions?.map((a) => (
            <li key={a.id} className="flex items-start gap-2 text-sm">
              <Checkbox
                className="mt-0.5"
                checked={!!a.done_at}
                disabled={!canEdit || toggle.isPending}
                onCheckedChange={(v) => toggle.mutate({ aid: a.id, done: v === true })}
                aria-label={`Done: ${a.text}`}
              />
              <span className={cn(a.done_at && 'text-muted-foreground line-through')}>{a.text}</span>
              {a.owner ? <span className="text-xs text-muted-foreground">· {a.owner}</span> : null}
              {a.due_on ? (
                <span className={cn('text-xs', !a.done_at && isOverdue(a.due_on) ? 'font-medium text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
                  · due {fmtDate(a.due_on)}
                </span>
              ) : null}
            </li>
          ))}
          {canEdit ? (
            <li>
              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault()
                  if (newAction.trim()) add.mutate(newAction.trim())
                }}
              >
                <Input value={newAction} onChange={(e) => setNewAction(e.target.value)} placeholder="Add follow-up action…" className="h-8 text-sm" />
                <Button type="submit" size="sm" variant="outline" disabled={!newAction.trim() || add.isPending}>
                  Add
                </Button>
              </form>
              <InlineError error={add.error ?? toggle.error} />
            </li>
          ) : null}
        </ul>
      ) : null}
    </li>
  )
}

type DraftAction = { text: string; owner: string; due_on: string }

export function MeetingEditor({
  companyId,
  leadId,
  appearanceId,
  contacts,
  defaultPlace,
  onDone,
}: {
  companyId: number
  leadId?: number
  appearanceId?: number
  contacts: Contact[]
  defaultPlace?: string
  onDone: () => void
}) {
  const qc = useQueryClient()
  const { data: me } = useMe()
  const [metOn, setMetOn] = useState(todayIso())
  const [time, setTime] = useState('')
  const [place, setPlace] = useState(defaultPlace ?? '')
  const [metBy, setMetBy] = useState(me?.name ?? '')
  const [summary, setSummary] = useState('')
  const [contactIds, setContactIds] = useState<number[]>([])
  const [actions, setActions] = useState<DraftAction[]>([])

  const save = useMutation({
    mutationFn: () => {
      const body: MeetingCreate = {
        company_id: companyId,
        met_on: metOn,
        lead_id: leadId,
        appearance_id: appearanceId,
        starts_at: time ? new Date(`${metOn}T${time}`).toISOString() : undefined,
        place: place || undefined,
        met_by: metBy.split(',').map((s) => s.trim()).filter(Boolean),
        summary_md: summary || undefined,
        contact_ids: contactIds,
        actions: actions.filter((a) => a.text.trim()).map((a) => ({ text: a.text.trim(), owner: a.owner || undefined, due_on: a.due_on || undefined })),
        source: 'app',
      }
      return api.createMeeting(body)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['meetings'] })
      qc.invalidateQueries({ queryKey: ['leads'] })
      onDone()
    },
  })

  return (
    <form
      className="space-y-3 rounded-lg border bg-card p-3"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Field label="Date">
          <Input type="date" required value={metOn} onChange={(e) => setMetOn(e.target.value)} />
        </Field>
        <Field label="Time (optional)">
          <Input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
        </Field>
        <Field label="Place or show" className="col-span-2">
          <Input value={place} onChange={(e) => setPlace(e.target.value)} placeholder="electronica 2026, Hall B4" />
        </Field>
        <Field label="Who met (comma separated)" className="col-span-2">
          <Input value={metBy} onChange={(e) => setMetBy(e.target.value)} />
        </Field>
        {contacts.length ? (
          <fieldset className="col-span-2 flex flex-col gap-1">
            <legend className="mb-1 text-xs font-medium text-muted-foreground">Contacts</legend>
            <div className="flex flex-wrap gap-2">
              {contacts.map((c) => {
                const on = contactIds.includes(c.id)
                return (
                  <button
                    key={c.id}
                    type="button"
                    aria-pressed={on}
                    onClick={() => setContactIds(on ? contactIds.filter((x) => x !== c.id) : [...contactIds, c.id])}
                    className={cn('rounded-full border px-2 py-0.5 text-xs', on ? 'border-primary bg-primary/10 text-primary' : 'text-muted-foreground')}
                  >
                    {c.name || c.email}
                  </button>
                )
              })}
            </div>
          </fieldset>
        ) : null}
      </div>
      <MdEditor value={summary} onChange={setSummary} />
      <div className="space-y-2">
        <p className="text-xs font-medium text-muted-foreground">Follow-up actions</p>
        {actions.map((a, i) => (
          <div key={i} className="grid grid-cols-[1fr_1fr_auto] gap-2 sm:grid-cols-[1fr_8rem_9rem_auto]">
            <Input className="col-span-3 sm:col-span-1" value={a.text} placeholder="Send quote for…" onChange={(e) => setActions(actions.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} />
            <Input value={a.owner} placeholder="Owner" onChange={(e) => setActions(actions.map((x, j) => (j === i ? { ...x, owner: e.target.value } : x)))} />
            <Input type="date" value={a.due_on} onChange={(e) => setActions(actions.map((x, j) => (j === i ? { ...x, due_on: e.target.value } : x)))} />
            <Button variant="ghost" size="icon" aria-label="Remove action" onClick={() => setActions(actions.filter((_, j) => j !== i))}>
              <Trash2 />
            </Button>
          </div>
        ))}
        <Button size="sm" variant="outline" onClick={() => setActions([...actions, { text: '', owner: me?.name ?? '', due_on: '' }])}>
          <Plus /> Action
        </Button>
      </div>
      <InlineError error={save.error} />
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? 'Saving…' : 'Save meeting'}
        </Button>
      </div>
    </form>
  )
}
