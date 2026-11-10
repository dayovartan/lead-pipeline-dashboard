import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { CheckCircle2, Download, FileSpreadsheet, Image as ImageIcon, Play, Upload } from 'lucide-react'
import { api, urls } from '@/api/client'
import type { ImportBatch } from '@/api/types'
import { PageHeader } from '@/components/bits'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Empty, ErrorState, InlineError, Loading } from '@/components/ui/states'
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/table'
import { useCanEdit } from '@/lib/hooks'
import { cn, fmtDateTime, label } from '@/lib/utils'

export default function Intake() {
  const { slug = '' } = useParams()
  const canEdit = useCanEdit()
  const qc = useQueryClient()
  const conv = useQuery({ queryKey: ['convention', slug], queryFn: () => api.convention(slug) })
  const history = useQuery({ queryKey: ['imports', slug], queryFn: () => api.imports(slug) })
  const [file, setFile] = useState<File | null>(null)
  const [picked, setPicked] = useState<ImportBatch | null>(null)
  // the history list omits conflicts/errors; the single-batch read has them
  const full = useQuery({ queryKey: ['imports', 'one', picked?.id], queryFn: () => api.importBatch(picked!.id), enabled: !!picked })
  const selected = full.data && full.data.id === picked?.id ? full.data : picked
  const setSelected = (b: ImportBatch | null) => setPicked(b)
  const fileRef = useRef<HTMLInputElement>(null)

  const done = (b: ImportBatch) => {
    qc.setQueryData(['imports', 'one', b.id], b)
    setSelected(b)
    qc.invalidateQueries({ queryKey: ['imports', slug] })
  }
  const dry = useMutation({ mutationFn: () => api.uploadImport(slug, file!, true), onSuccess: done })
  const apply = useMutation({
    mutationFn: (id: number) => api.applyImport(id),
    onSuccess: (b) => {
      done(b)
      setFile(null)
      if (fileRef.current) fileRef.current.value = ''
      for (const k of ['convention', 'conventions', 'appearances', 'companies', 'coverage', 'dispatch', 'categories', 'tags', 'leads'])
        qc.invalidateQueries({ queryKey: [k] })
    },
  })

  return (
    <>
      <PageHeader title={`Intake${conv.data ? ` · ${conv.data.name}` : ''}`} sub="Upload the exhibitor Excel, check the dry run, then load it. Reloading is safe: tags, assignments and notes made in the app are kept.">
        <Button asChild variant="outline">
          <a href={urls.template}>
            <Download /> Template
          </a>
        </Button>
      </PageHeader>
      {conv.isError ? <ErrorState error={conv.error} retry={conv.refetch} /> : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-4">
          {canEdit ? (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2"><FileSpreadsheet className="size-4" /> Excel file</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <label
                  className={cn(
                    'flex cursor-pointer flex-col items-center justify-center gap-1 rounded-md border-2 border-dashed p-6 text-center text-sm text-muted-foreground hover:border-primary/60',
                    file && 'border-primary/60 text-foreground',
                  )}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault()
                    const f = e.dataTransfer.files?.[0]
                    if (f) setFile(f)
                  }}
                >
                  <Upload className="size-5" />
                  {file ? <span className="font-medium">{file.name} · {(file.size / 1024).toFixed(0)} KB</span> : <span>Drop the .xlsx here or click to choose</span>}
                  <span className="text-xs">Sheets: Exhibitors, Contacts</span>
                  <input
                    ref={fileRef}
                    type="file"
                    accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    className="sr-only"
                    onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  />
                </label>
                <div className="flex flex-wrap items-center gap-2">
                  <Button onClick={() => dry.mutate()} disabled={!file || dry.isPending}>
                    <Play /> {dry.isPending ? 'Checking…' : 'Dry run'}
                  </Button>
                  <span className="text-xs text-muted-foreground">A dry run writes nothing except the batch record.</span>
                </div>
                <InlineError error={dry.error} />
              </CardContent>
            </Card>
          ) : null}

          {selected ? (
            <BatchReport
              batch={selected}
              canEdit={canEdit}
              onApply={() => apply.mutate(selected.id)}
              applying={apply.isPending}
              applyError={apply.error}
            />
          ) : (
            !canEdit && <Empty title="Pick a batch from the history to see its report" />
          )}
        </div>

        <div className="space-y-4">
          {canEdit ? <VenueMapCard slug={slug} url={conv.data?.venue_map_url ?? null} /> : null}
          <Card>
            <CardHeader><CardTitle>History</CardTitle></CardHeader>
            <CardContent className="p-0">
              {history.isLoading ? <Loading /> : history.isError ? <ErrorState error={history.error} retry={history.refetch} /> : null}
              {history.data?.length === 0 ? <p className="p-4 text-sm text-muted-foreground">No imports yet.</p> : null}
              <ul className="divide-y">
                {history.data?.map((b) => (
                  <li key={b.id}>
                    <button
                      type="button"
                      onClick={() => setSelected(b)}
                      className={cn('w-full px-4 py-2 text-left text-sm hover:bg-accent', selected?.id === b.id && 'bg-accent')}
                    >
                      <div className="flex items-center gap-2">
                        <span className="truncate font-medium">{b.file ?? `batch ${b.id}`}</span>
                        <Badge variant={b.dry_run ? 'suggested' : 'success'} className="ml-auto">{b.dry_run ? 'dry run' : 'loaded'}</Badge>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {fmtDateTime(b.at)}{b.actor ? ` · ${b.actor}` : ''} · {b.rows} rows · +{b.created} ~{b.updated} ={b.skipped}
                        {b.conflicts ? <span className="text-amber-600 dark:text-amber-400"> · {b.conflicts} conflicts</span> : null}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  )
}

function BatchReport({ batch, canEdit, onApply, applying, applyError }: { batch: ImportBatch; canEdit: boolean; onApply: () => void; applying: boolean; applyError: unknown }) {
  const r = batch.report ?? {}
  const sheets = Object.entries(r.sheets ?? {})
  const cols = Array.from(new Set(sheets.flatMap(([, c]) => Object.keys(c ?? {}))))
  const order = ['rows', 'created', 'updated', 'unchanged', 'skipped', 'conflicts', 'errors']
  cols.sort((a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99))
  const conflicts = r.conflicts ?? []
  const errors = r.errors ?? []
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
        <div>
          <CardTitle className="flex items-center gap-2">
            {batch.dry_run ? 'Dry run' : <><CheckCircle2 className="size-4 text-emerald-600" /> Loaded</>} · {batch.file ?? `batch ${batch.id}`}
          </CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">{fmtDateTime(batch.at)}</p>
        </div>
        {batch.dry_run && canEdit && !r.applied_batch_id ? (
          <Button onClick={onApply} disabled={applying}>
            {applying ? 'Loading…' : 'Load into the database'}
          </Button>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-4">
        <InlineError error={applyError} />
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          {([['rows', batch.rows], ['created', batch.created], ['updated', batch.updated], ['skipped', batch.skipped], ['conflicts', batch.conflicts]] as const).map(([k, v]) => (
            <div key={k} className={cn('rounded-md border p-2 text-center', k === 'conflicts' && v > 0 && 'border-amber-500/60')}>
              <div className="text-lg font-semibold tabular-nums">{(v ?? 0).toLocaleString()}</div>
              <div className="text-xs text-muted-foreground">{k}</div>
            </div>
          ))}
        </div>
        {r.failed ? <p className="text-sm text-destructive">This import failed{typeof r.failed === 'string' ? `: ${r.failed}` : '.'}</p> : null}
        {batch.dry_run && r.applied_batch_id ? <p className="text-sm text-muted-foreground">Already loaded as batch {r.applied_batch_id}.</p> : null}
        {r.leads_created ? <p className="text-sm">{r.leads_created} lead(s) {batch.dry_run ? 'would be' : 'were'} created from rows with lead activity.</p> : null}
        {sheets.length ? (
          <Table>
            <THead>
              <TR>
                <TH>Sheet</TH>
                {cols.map((c) => <TH key={c} className="text-right">{label(c)}</TH>)}
              </TR>
            </THead>
            <TBody>
              {sheets.map(([name, counts]) => (
                <TR key={name}>
                  <TD className="font-medium capitalize">{name}</TD>
                  {cols.map((c) => <TD key={c} className="text-right tabular-nums">{typeof counts?.[c] === 'number' ? counts[c].toLocaleString() : String(counts?.[c] ?? '—')}</TD>)}
                </TR>
              ))}
            </TBody>
          </Table>
        ) : null}
        {conflicts.length ? (
          <div>
            <h3 className="mb-2 text-sm font-semibold">Conflicts ({conflicts.length}) <span className="font-normal text-muted-foreground">— edited in the app; the app value is kept</span></h3>
            <Table>
              <THead>
                <TR><TH>Company</TH><TH>Field</TH><TH>In the app</TH><TH>In the file</TH></TR>
              </THead>
              <TBody>
                {conflicts.map((c, i) => (
                  <TR key={`${c.company_id}-${c.field}-${i}`}>
                    <TD className="font-medium">{c.company}</TD>
                    <TD>{label(c.field.replace(/^contact\./, 'contact: '))}</TD>
                    <TD className="max-w-[16rem] truncate" title={fmt(c.app_value)}>{fmt(c.app_value)}</TD>
                    <TD className="max-w-[16rem] truncate" title={fmt(c.file_value)}>{fmt(c.file_value)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </div>
        ) : null}
        {errors.length ? (
          <div>
            <h3 className="mb-2 text-sm font-semibold text-destructive">Errors ({errors.length})</h3>
            <ul className="max-h-64 space-y-1 overflow-y-auto rounded-md border p-2 text-sm">
              {errors.map((e, i) => (
                <li key={i}>
                  <span className="tabular-nums text-muted-foreground">{e.sheet ? `${e.sheet} ` : ''}row {e.row}:</span> {e.message}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

const fmt = (v: unknown) => (v === null || v === undefined || v === '' ? '—' : Array.isArray(v) ? v.join('; ') : typeof v === 'object' ? JSON.stringify(v) : String(v))

function VenueMapCard({ slug, url }: { slug: string; url: string | null }) {
  const qc = useQueryClient()
  const m = useMutation({
    mutationFn: (f: File) => api.uploadVenueMap(slug, f),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['convention', slug] }),
  })
  return (
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2"><ImageIcon className="size-4" /> Venue map</CardTitle></CardHeader>
      <CardContent className="space-y-2 text-sm">
        {url ? <img src={url} alt="Venue map" className="max-h-40 w-full rounded border object-contain" /> : <p className="text-muted-foreground">None. Coverage uses the hall/booth hierarchy instead.</p>}
        <label className="inline-flex cursor-pointer items-center gap-2 text-primary hover:underline">
          <Upload className="size-4" /> {url ? 'Replace image' : 'Upload image'}
          <input type="file" accept="image/*,application/pdf" className="sr-only" onChange={(e) => e.target.files?.[0] && m.mutate(e.target.files[0])} />
        </label>
        {m.isPending ? <p className="text-muted-foreground">Uploading…</p> : null}
        <InlineError error={m.error} />
      </CardContent>
    </Card>
  )
}
