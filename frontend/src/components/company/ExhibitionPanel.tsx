import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, X } from 'lucide-react'
import { api } from '@/api/client'
import { PRIORITIES, ROLES } from '@/api/types'
import type { AppearancePatch, CompanyDetail, DispatchPut, Priority, Role } from '@/api/types'
import { useCanEdit } from '@/lib/hooks'
import { fmtDateTime, label } from '@/lib/utils'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { Checkbox } from '../ui/checkbox'
import { Field, Input, Select } from '../ui/input'
import { Empty, InlineError } from '../ui/states'

/** Exhibitions route: role, tags, priority and visit status for one show. No MCP calls here. */
export function ExhibitionPanel({ company, show }: { company: CompanyDetail; show: string }) {
  const canEdit = useCanEdit()
  const qc = useQueryClient()
  const a = company.appearances.find((x) => x.convention_slug === show)
  const tags = useQuery({ queryKey: ['tags', show], queryFn: () => api.tags(show), enabled: !!a && canEdit, staleTime: 60_000 })
  const [assignee, setAssignee] = useState(a?.dispatch?.assignee ?? '')
  const [note, setNote] = useState(a?.dispatch?.note ?? '')
  useEffect(() => {
    setAssignee(a?.dispatch?.assignee ?? '')
    setNote(a?.dispatch?.note ?? '')
  }, [a?.id, a?.dispatch?.assignee, a?.dispatch?.note])

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['company', company.id] })
    qc.invalidateQueries({ queryKey: ['appearances', show] })
    qc.invalidateQueries({ queryKey: ['coverage', show] })
    qc.invalidateQueries({ queryKey: ['dispatch', show] })
  }
  const patch = useMutation({ mutationFn: (b: AppearancePatch) => api.patchAppearance(show, a!.id, b), onSuccess: refresh })
  const disp = useMutation({ mutationFn: (b: DispatchPut) => api.putDispatch(show, a!.id, b), onSuccess: refresh })
  const tagOp = useMutation({
    mutationFn: ({ op, tagId }: { op: 'add' | 'remove' | 'confirm'; tagId: number }) =>
      op === 'add' ? api.addTag(show, a!.id, tagId) : op === 'remove' ? api.removeTag(show, a!.id, tagId) : api.confirmTag(show, a!.id, tagId),
    onSuccess: () => {
      refresh()
      qc.invalidateQueries({ queryKey: ['tags', show] })
    },
  })

  if (!a) return <Empty title="Not at this show">This company has no appearance at {show}.</Empty>

  const allTags = [...(tags.data?.groups.flatMap((g) => g.tags.map((t) => ({ ...t, group: g.name }))) ?? []), ...(tags.data?.ungrouped.map((t) => ({ ...t, group: '' })) ?? [])]
  const have = new Set((a.tags ?? []).map((t) => t.id))

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        Hall <b className="text-foreground">{a.hall ?? '?'}</b> · Booth <b className="text-foreground">{a.booth ?? '?'}</b>
        {a.hall_booth_raw && a.hall_booth_raw !== `${a.hall}/${a.booth}` ? <span> ({a.hall_booth_raw})</span> : null}
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label={`Role${!a.role && a.mapping?.suggested_role ? ` (suggested: ${a.mapping.suggested_role})` : ''}`}>
          <Select
            value={a.role ?? ''}
            disabled={!canEdit || patch.isPending}
            onChange={(e) => patch.mutate({ role: (e.target.value || null) as Role | null })}
            className={!a.role && a.mapping?.suggested_role ? 'border-dashed' : undefined}
          >
            <option value="">{a.mapping?.suggested_role ? `${a.mapping.suggested_role}? (unconfirmed)` : '—'}</option>
            {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </Select>
        </Field>
        <Field label="Priority">
          <Select
            value={a.priority ?? ''}
            disabled={!canEdit || patch.isPending}
            onChange={(e) => patch.mutate({ priority: (e.target.value || null) as Priority | null })}
            className={!a.priority && a.mapping?.suggested_priority ? 'border-dashed' : undefined}
          >
            <option value="">{a.mapping?.suggested_priority ? `${label(a.mapping.suggested_priority)}? (unconfirmed)` : '—'}</option>
            {PRIORITIES.map((p) => <option key={p} value={p}>{label(p)}</option>)}
          </Select>
        </Field>
        <label className="flex items-center gap-2 pt-5 text-sm">
          <Checkbox checked={!!a.met_at_booth} disabled={!canEdit} onCheckedChange={(v) => patch.mutate({ met_at_booth: v === true })} />
          Met at booth
        </label>
      </div>
      {!a.role && a.mapping?.suggested_role && canEdit ? (
        <Button size="sm" variant="outline" onClick={() => patch.mutate({ role: a.mapping!.suggested_role!, priority: a.priority ?? a.mapping!.suggested_priority ?? undefined })}>
          <Check /> Confirm suggestion
        </Button>
      ) : null}
      {a.mapping?.confirmed_by ? (
        <p className="text-xs text-muted-foreground">Confirmed by {a.mapping.confirmed_by} {fmtDateTime(a.mapping.confirmed_at)}</p>
      ) : null}
      <InlineError error={patch.error} />

      <section>
        <h3 className="mb-2 text-sm font-semibold">Tags</h3>
        <div className="flex flex-wrap gap-1.5">
          {(a.tags ?? []).length === 0 ? <span className="text-sm text-muted-foreground">No tags.</span> : null}
          {(a.tags ?? []).map((t) => (
            <Badge key={t.id} variant={t.confirmed ? 'secondary' : 'suggested'} className="gap-1 py-1">
              {t.group ? <span className="text-muted-foreground">{t.group} ·</span> : null}
              {t.name}
              {canEdit && !t.confirmed ? (
                <button type="button" aria-label={`Confirm ${t.name}`} title="Confirm" onClick={() => tagOp.mutate({ op: 'confirm', tagId: t.id })} className="rounded hover:text-foreground">
                  <Check className="size-3" />
                </button>
              ) : null}
              {canEdit ? (
                <button type="button" aria-label={`Remove ${t.name}`} title="Remove" onClick={() => tagOp.mutate({ op: 'remove', tagId: t.id })} className="rounded hover:text-foreground">
                  <X className="size-3" />
                </button>
              ) : null}
            </Badge>
          ))}
        </div>
        {canEdit ? (
          <Select
            className="mt-2"
            value=""
            aria-label="Add tag"
            onChange={(e) => e.target.value && tagOp.mutate({ op: 'add', tagId: Number(e.target.value) })}
          >
            <option value="">+ Add tag…</option>
            {allTags.filter((t) => !have.has(t.id)).map((t) => (
              <option key={t.id} value={t.id}>
                {t.group ? `${t.group} · ` : ''}
                {t.name}
              </option>
            ))}
          </Select>
        ) : null}
        <InlineError error={tagOp.error} />
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold">Visit</h3>
        <div className="grid gap-3 sm:grid-cols-[auto_1fr]">
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={!!a.dispatch?.visited} disabled={!canEdit} onCheckedChange={(v) => disp.mutate({ visited: v === true })} />
            Visited {a.dispatch?.visited_at ? <span className="text-xs text-muted-foreground">{fmtDateTime(a.dispatch.visited_at)}</span> : null}
          </label>
          <Field label="Assignee">
            <Input value={assignee} disabled={!canEdit} onChange={(e) => setAssignee(e.target.value)} onBlur={() => assignee !== (a.dispatch?.assignee ?? '') && disp.mutate({ assignee: assignee || null })} />
          </Field>
          <Field label="Visit note" className="sm:col-span-2">
            <Input value={note} disabled={!canEdit} onChange={(e) => setNote(e.target.value)} onBlur={() => note !== (a.dispatch?.note ?? '') && disp.mutate({ note: note || null })} />
          </Field>
        </div>
        <InlineError error={disp.error} />
      </section>
    </div>
  )
}
