import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { CalendarDays, MapPin, Plus } from 'lucide-react'
import { api } from '@/api/client'
import type { ConventionCreate } from '@/api/types'
import { PageHeader } from '@/components/bits'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog, DialogContent, DialogTrigger } from '@/components/ui/dialog'
import { Field, Input } from '@/components/ui/input'
import { Empty, ErrorState, InlineError, Loading } from '@/components/ui/states'
import { useCanEdit, useConventions } from '@/lib/hooks'
import { fmtDate } from '@/lib/utils'

export default function ShowList() {
  const q = useConventions()
  const canEdit = useCanEdit()
  return (
    <>
      <PageHeader title="Shows" sub="Get list → sort → map → dispatch, once per exhibition.">
        {canEdit ? <NewShowDialog /> : null}
      </PageHeader>
      {q.isLoading ? <Loading /> : q.isError ? <ErrorState error={q.error} retry={q.refetch} /> : null}
      {q.data && q.data.length === 0 ? (
        <Empty title="No shows yet">{canEdit ? 'Create one with "New show", then load its Excel on the intake page.' : 'An editor needs to create the first show.'}</Empty>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {q.data?.map((c) => {
          const n = c.counts ?? { appearances: 0, mapped: 0, visited: 0, leads: 0 }
          const pct = (x: number) => (n.appearances ? Math.round((100 * x) / n.appearances) : 0)
          return (
            <Card key={c.slug} className="flex flex-col p-4 transition-colors hover:border-primary/50">
              <Link to={`/exhibitions/${encodeURIComponent(c.slug)}/map`} className="text-base font-semibold hover:underline">
                {c.name}
              </Link>
              <p className="mt-1 flex flex-wrap gap-x-3 text-sm text-muted-foreground">
                {c.city || c.country ? (
                  <span className="flex items-center gap-1"><MapPin className="size-3.5" />{[c.city, c.country].filter(Boolean).join(', ')}</span>
                ) : null}
                {c.starts_on ? (
                  <span className="flex items-center gap-1"><CalendarDays className="size-3.5" />{fmtDate(c.starts_on)}{c.ends_on && c.ends_on !== c.starts_on ? ` – ${fmtDate(c.ends_on)}` : ''}</span>
                ) : null}
              </p>
              <dl className="mt-3 grid grid-cols-4 gap-2 text-center">
                {([['exhibitors', n.appearances], ['mapped', n.mapped], ['visited', n.visited], ['leads', n.leads]] as const).map(([k, v]) => (
                  <div key={k} className="rounded-md bg-muted/60 px-1 py-1.5">
                    <dd className="text-base font-semibold tabular-nums">{v.toLocaleString()}</dd>
                    <dt className="text-[11px] text-muted-foreground">{k}</dt>
                  </div>
                ))}
              </dl>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted" title={`${pct(n.mapped)}% mapped`}>
                <div className="h-full bg-primary" style={{ width: `${pct(n.mapped)}%` }} />
              </div>
              <div className="mt-3 flex flex-wrap gap-1 text-sm">
                {(['intake', 'map', 'coverage', 'dispatch'] as const).map((s) => (
                  <Button key={s} asChild size="sm" variant="ghost" className="capitalize">
                    <Link to={`/exhibitions/${encodeURIComponent(c.slug)}/${s}`}>{s}</Link>
                  </Button>
                ))}
              </div>
            </Card>
          )
        })}
      </div>
    </>
  )
}

const slugify = (s: string) =>
  s
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')

function NewShowDialog() {
  const [open, setOpen] = useState(false)
  const [v, setV] = useState<ConventionCreate>({ name: '', slug: '' })
  const [slugTouched, setSlugTouched] = useState(false)
  const qc = useQueryClient()
  const navigate = useNavigate()
  const m = useMutation({
    mutationFn: () => {
      const body = Object.fromEntries(Object.entries(v).filter(([, x]) => x)) as unknown as ConventionCreate
      return api.createConvention(body)
    },
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ['conventions'] })
      setOpen(false)
      navigate(`/exhibitions/${encodeURIComponent(c?.slug ?? v.slug)}/intake`)
    },
  })
  const set = (k: keyof ConventionCreate) => (e: React.ChangeEvent<HTMLInputElement>) => setV({ ...v, [k]: e.target.value })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus /> New show
        </Button>
      </DialogTrigger>
      <DialogContent title="New show" description="You load the exhibitor Excel on the next page.">
        <form
          className="grid gap-3 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault()
            m.mutate()
          }}
        >
          <Field label="Name" className="sm:col-span-2">
            <Input required autoFocus value={v.name} placeholder="electronica 2026" onChange={(e) => setV({ ...v, name: e.target.value, slug: slugTouched ? v.slug : slugify(e.target.value) })} />
          </Field>
          <Field label="Slug (in the URL)" className="sm:col-span-2">
            <Input required pattern="[a-z0-9][a-z0-9\-]*" value={v.slug} onChange={(e) => (setSlugTouched(true), setV({ ...v, slug: e.target.value }))} />
          </Field>
          <Field label="City"><Input value={v.city ?? ''} onChange={set('city')} /></Field>
          <Field label="Country"><Input value={v.country ?? ''} onChange={set('country')} /></Field>
          <Field label="Starts"><Input type="date" value={v.starts_on ?? ''} onChange={set('starts_on')} /></Field>
          <Field label="Ends"><Input type="date" value={v.ends_on ?? ''} onChange={set('ends_on')} /></Field>
          <div className="flex items-center justify-end gap-2 sm:col-span-2">
            <InlineError error={m.error} />
            <Button type="submit" disabled={m.isPending}>{m.isPending ? 'Creating…' : 'Create show'}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
