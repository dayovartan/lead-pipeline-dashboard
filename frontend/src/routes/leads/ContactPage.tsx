import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Mail, Phone } from 'lucide-react'
import { api } from '@/api/client'
import { MeetingsTimeline } from '@/components/MeetingsTimeline'
import { Button } from '@/components/ui/button'
import { StatusBadge } from '@/components/bits'
import { useOpenCompany } from '@/lib/openCompany'

/** Contact window: details (GET /api/contacts/{id}) plus their meetings. */
export default function ContactPage() {
  const { id } = useParams()
  const cid = Number(id)
  const openCompany = useOpenCompany()
  const contact = useQuery({ queryKey: ['contact', cid], queryFn: () => api.contact(cid), retry: false })
  const c = contact.data
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <Button asChild variant="ghost" size="sm">
        <Link to="/leads/companies">
          <ArrowLeft /> Companies
        </Link>
      </Button>
      <header className="rounded-lg border p-4">
        <h1 className="text-lg font-semibold">{c?.name || c?.email || `Contact ${cid}`}</h1>
        {c?.title ? <p className="text-sm text-muted-foreground">{c.title}</p> : null}
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {c?.email ? <a className="inline-flex items-center gap-1 hover:underline" href={`mailto:${c.email}`}><Mail className="size-3.5" />{c.email}</a> : null}
          {c?.phone ? <a className="inline-flex items-center gap-1 hover:underline" href={`tel:${c.phone}`}><Phone className="size-3.5" />{c.phone}</a> : null}
          {c?.company ? (
            <button type="button" className="text-primary hover:underline" onClick={() => openCompany(c.company!.id)}>
              {c.company.name}
            </button>
          ) : null}
        </div>
        {c?.leads?.length ? (
          <p className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            Leads: {c.leads.map((l) => <StatusBadge key={l.id} status={l.status} />)}
          </p>
        ) : null}
        {contact.isError ? <p className="mt-2 text-xs text-muted-foreground">Contact details aren't available; meetings are shown below.</p> : null}
      </header>
      <section>
        <h2 className="mb-3 text-sm font-semibold">Meetings</h2>
        <MeetingsTimeline contactId={cid} />
      </section>
    </div>
  )
}
