import { memo, useCallback, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { useTheme } from '@/lib/theme'
import { Background, Controls, MiniMap, ReactFlow, type Node, type NodeProps, type NodeTypes } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Hammer, Image as ImageIcon, Network } from 'lucide-react'
import { api } from '@/api/client'
import type { CoverageBooth, CoverageStats, VenueNode } from '@/api/types'
import { PageHeader } from '@/components/bits'
import { Button } from '@/components/ui/button'
import { Empty, ErrorState, InlineError, Loading } from '@/components/ui/states'
import { useCanEdit } from '@/lib/hooks'
import { useOpenCompany } from '@/lib/openCompany'
import { cn } from '@/lib/utils'
import { layoutVenue } from '@/lib/venueLayout'
import { CoverageLegend, HighlightContext, computeHighlight, useHighlight, useLegendFilter } from '@/components/CoverageLegend'

type AreaData = { node: VenueNode; width: number; height: number }
type BoothData = { node: VenueNode; booths: CoverageBooth[]; onOpen: (b: CoverageBooth) => void }

type BoothState = 'visited' | 'must' | 'skipped' | 'open'
function boothState(booths: CoverageBooth[], s?: CoverageStats): BoothState {
  if (booths.length) {
    if (booths.every((b) => b.visited)) return 'visited'
    if (booths.some((b) => !b.visited && b.priority === 'must_visit')) return 'must'
    if (booths.every((b) => b.priority === 'skip' || b.role === 'ignore')) return 'skipped'
    return 'open'
  }
  if (s) {
    if (s.total && s.visited >= s.total) return 'visited'
    if (s.must_visit_uncovered) return 'must'
    if (s.total && s.skipped >= s.total) return 'skipped'
  }
  return 'open'
}
const stateCls: Record<BoothState, string> = {
  visited: 'border-emerald-500 bg-emerald-500/15',
  must: 'border-red-500 bg-red-500/15',
  skipped: 'border-dashed border-muted-foreground/40 bg-muted/60 text-muted-foreground',
  open: 'border-border bg-card',
}

const AreaNode = memo(function AreaNode({ data }: NodeProps<Node<AreaData>>) {
  const { node, width, height } = data
  const s = node.stats ?? { total: 0, visited: 0, must_visit_uncovered: 0, skipped: 0 }
  const pct = s.total ? Math.round((100 * s.visited) / s.total) : 0
  const hl = useHighlight()
  const hits = hl.nodeCount.get(node.id) ?? 0
  return (
    <div
      style={{ width, height }}
      className={cn(
        'rounded-xl border-2 border-dotted transition-opacity',
        hl.active && !hits && 'opacity-40',
        node.kind === 'floor' ? 'border-muted-foreground/40 bg-muted/20' : 'border-muted-foreground/50 bg-background/60',
        s.must_visit_uncovered > 0 && 'border-red-500/60',
      )}
    >
      <div className="flex items-center gap-2 overflow-hidden whitespace-nowrap px-3 pt-2 text-xs">
        <span className="text-sm font-semibold capitalize">{node.kind === 'booth' ? '' : `${node.kind} `}{node.label}</span>
        <span className="tabular-nums text-muted-foreground">{s.visited}/{s.total} visited</span>
        {s.must_visit_uncovered ? <span className="font-medium text-red-600 dark:text-red-400">{s.must_visit_uncovered} must-visit left</span> : null}
        {hl.active && hits ? <span className="rounded bg-primary px-1.5 font-medium text-primary-foreground">{hits} match</span> : null}
      </div>
      <div className="mx-3 mt-1 h-1 overflow-hidden rounded-full bg-muted">
        <div className="h-full bg-emerald-500" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
})

const BoothNode = memo(function BoothNode({ data }: NodeProps<Node<BoothData>>) {
  const { node, booths, onOpen } = data
  const st = boothState(booths, node.stats)
  const hl = useHighlight()
  const hit = hl.active && booths.some((b) => hl.match.has(b.appearance_id))
  return (
    <div
      className={cn(
        'h-full w-[156px] rounded-md border-2 px-2 py-1 text-[11px] leading-4 shadow-sm transition-opacity',
        stateCls[st],
        hl.active && (hit ? 'ring-[3px] ring-primary ring-offset-1 ring-offset-background' : 'opacity-25'),
      )}
    >
      <div className="font-semibold tabular-nums">{node.label}</div>
      {booths.slice(0, 3).map((b) => (
        <button
          key={b.appearance_id}
          type="button"
          className={cn('nodrag block w-full truncate text-left hover:underline', hl.active && hl.match.has(b.appearance_id) && 'font-semibold text-primary')}
          title={b.company_name}
          onClick={(e) => {
            e.stopPropagation()
            onOpen(b)
          }}
        >
          {b.visited ? '✓ ' : b.priority === 'must_visit' ? '! ' : ''}
          {b.company_name}
        </button>
      ))}
      {booths.length > 3 ? <div className="text-muted-foreground">+{booths.length - 3} more</div> : null}
    </div>
  )
})

const nodeTypes: NodeTypes = { area: AreaNode, booth: BoothNode }

export default function Coverage() {
  const { slug = '' } = useParams()
  const canEdit = useCanEdit()
  const qc = useQueryClient()
  const openCompany = useOpenCompany()
  const conv = useQuery({ queryKey: ['convention', slug], queryFn: () => api.convention(slug) })
  const cov = useQuery({ queryKey: ['coverage', slug], queryFn: () => api.coverage(slug) })
  const tags = useQuery({ queryKey: ['tags', slug], queryFn: () => api.tags(slug) })
  const [filter, setFilter] = useLegendFilter()
  const highlight = useMemo(() => computeHighlight(cov.data?.nodes ?? [], cov.data?.booths ?? [], filter), [cov.data, filter])
  const [view, setView] = useState<'map' | 'tree' | null>(null)
  const hasMap = !!conv.data?.venue_map_url
  const mode = view ?? (hasMap ? 'map' : 'tree')

  const rebuild = useMutation({ mutationFn: () => api.rebuildVenue(slug), onSuccess: () => qc.invalidateQueries({ queryKey: ['coverage', slug] }) })
  const move = useMutation({ mutationFn: ({ id, x, y }: { id: number; x: number; y: number }) => api.moveNode(slug, id, x, y) })

  const openBooth = useCallback(
    async (b: CoverageBooth) => {
      if (b.company_id) return openCompany(b.company_id)
      // coverage booths may not carry company_id: resolve through search
      const r = await api.search(b.company_name)
      const hit = r.companies.find((c) => c.name === b.company_name) ?? r.companies[0]
      if (hit) openCompany(hit.id)
    },
    [openCompany],
  )

  const totals = useMemo(() => {
    const roots = (cov.data?.nodes ?? []).filter((n) => n.parent_id === null)
    return roots.reduce(
      (a, n) => ({
        total: a.total + (n.stats?.total ?? 0),
        visited: a.visited + (n.stats?.visited ?? 0),
        must: a.must + (n.stats?.must_visit_uncovered ?? 0),
      }),
      { total: 0, visited: 0, must: 0 },
    )
  }, [cov.data])

  return (
    <>
      <PageHeader
        title="Coverage"
        sub={cov.data ? `${totals.visited.toLocaleString()} of ${totals.total.toLocaleString()} booths visited · ${totals.must.toLocaleString()} must-visit left` : 'Which halls, rooms and booths have been visited.'}
      >
        {hasMap ? (
          <div className="flex rounded-md border p-0.5">
            <Button size="sm" variant={mode === 'map' ? 'secondary' : 'ghost'} onClick={() => setView('map')}><ImageIcon /> Venue map</Button>
            <Button size="sm" variant={mode === 'tree' ? 'secondary' : 'ghost'} onClick={() => setView('tree')}><Network /> Hierarchy</Button>
          </div>
        ) : null}
        {canEdit ? (
          <Button variant="outline" onClick={() => rebuild.mutate()} disabled={rebuild.isPending}>
            <Hammer /> {rebuild.isPending ? 'Rebuilding…' : 'Rebuild from hall/booth'}
          </Button>
        ) : null}
      </PageHeader>
      <Legend />
      <InlineError error={rebuild.error ?? move.error} />
      <HighlightContext.Provider value={highlight}>
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_17rem]">
      <div className="order-2 min-w-0 lg:order-1">
      {cov.isLoading ? <Loading /> : cov.isError ? <ErrorState error={cov.error} retry={cov.refetch} /> : !cov.data?.nodes.length ? (
        <Empty title="No venue layout yet">{canEdit ? 'Load the Excel on the intake page, then press "Rebuild from hall/booth".' : 'An editor needs to load the exhibitor list first.'}</Empty>
      ) : mode === 'map' && hasMap ? (
        <MapView url={conv.data!.venue_map_url!} nodes={cov.data.nodes} />
      ) : (
        <Hierarchy nodes={cov.data.nodes} booths={cov.data.booths} canEdit={canEdit} onOpen={openBooth} onMove={(id, x, y) => move.mutate({ id, x, y })} />
      )}
      </div>
      <CoverageLegend
        className="order-1 self-start lg:order-2 lg:sticky lg:top-28"
        booths={cov.data?.booths ?? []}
        tagList={tags.data}
        filter={filter}
        onChange={setFilter}
        matchCount={highlight.match.size}
      />
      </div>
      </HighlightContext.Provider>
    </>
  )
}

function Legend() {
  const item = (cls: string, text: string) => (
    <span className="flex items-center gap-1.5">
      <span className={cn('inline-block size-3 rounded-sm border-2', cls)} /> {text}
    </span>
  )
  return (
    <div className="mb-3 flex flex-wrap gap-4 text-xs text-muted-foreground">
      {item(stateCls.visited, 'visited')}
      {item(stateCls.must, 'must-visit, not covered')}
      {item(stateCls.open, 'not visited')}
      {item(stateCls.skipped, 'skipped / ignore')}
    </div>
  )
}

function MapView({ url, nodes }: { url: string; nodes: VenueNode[] }) {
  const hl = useHighlight()
  const halls = nodes.filter((n) => n.kind === 'hall' || n.kind === 'room').sort((a, b) => a.label.localeCompare(b.label, undefined, { numeric: true }))
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="overflow-auto rounded-lg border bg-muted/30">
        <img src={url} alt="Venue map" className="mx-auto max-h-[75vh] w-auto" />
      </div>
      <ul className="grid content-start gap-2 sm:grid-cols-2 lg:grid-cols-1">
        {halls.map((h) => {
          const s = h.stats
          const pct = s.total ? Math.round((100 * s.visited) / s.total) : 0
          return (
            <li key={h.id} className={cn('rounded-md border p-2 text-sm', s.must_visit_uncovered && 'border-red-500/60', hl.active && (hl.nodeCount.get(h.id) ? 'ring-2 ring-primary' : 'opacity-40'))}>
              <div className="flex items-baseline justify-between">
                <span className="font-medium capitalize">{h.kind} {h.label}</span>
                <span className="tabular-nums text-xs text-muted-foreground">
                  {hl.active ? <span className="mr-2 font-medium text-primary">{hl.nodeCount.get(h.id) ?? 0} match</span> : null}
                  {s.visited}/{s.total}
                </span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full bg-emerald-500" style={{ width: `${pct}%` }} /></div>
              {s.must_visit_uncovered ? <p className="mt-1 text-xs text-red-600 dark:text-red-400">{s.must_visit_uncovered} must-visit left</p> : null}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function Hierarchy({ nodes, booths, canEdit, onOpen, onMove }: { nodes: VenueNode[]; booths: CoverageBooth[]; canEdit: boolean; onOpen: (b: CoverageBooth) => void; onMove: (id: number, x: number, y: number) => void }) {
  const [rfNodes, setRfNodes] = useState<Node[] | null>(null)
  const [err, setErr] = useState<unknown>(null)

  useEffect(() => {
    let alive = true
    setErr(null)
    layoutVenue(nodes, booths)
      .then((laid) => {
        if (!alive) return
        setRfNodes(
          laid.map((l) => {
            const isBooth = l.node.kind === 'booth'
            return {
              id: l.id,
              type: isBooth ? 'booth' : 'area',
              position: { x: l.x, y: l.y },
              parentId: l.parent,
              extent: l.parent ? ('parent' as const) : undefined,
              draggable: canEdit,
              selectable: false,
              style: { width: l.width, height: l.height },
              data: isBooth ? { node: l.node, booths: l.booths, onOpen } : { node: l.node, width: l.width, height: l.height },
              zIndex: isBooth ? 1 : 0,
            } as Node
          }),
        )
      })
      .catch((e) => alive && setErr(e))
    return () => {
      alive = false
    }
  }, [nodes, booths, canEdit, onOpen])
  const { dark } = useTheme()

  if (err) return <ErrorState error={err} />
  if (!rfNodes) return <Loading label="Laying out the venue…" />
  return (
    <div className="h-[calc(100vh-15rem)] min-h-[420px] overflow-hidden rounded-lg border bg-muted/10">
      <ReactFlow
        colorMode={dark ? 'dark' : 'light'}
        nodes={rfNodes}
        edges={[]}
        nodeTypes={nodeTypes}
        onNodesChange={(changes) =>
          setRfNodes((cur) =>
            cur
              ? cur.map((n) => {
                  const c = changes.find((x) => x.type === 'position' && x.id === n.id)
                  return c && c.type === 'position' && c.position ? { ...n, position: c.position } : n
                })
              : cur,
          )
        }
        onNodeDragStop={(_e, n) => onMove(Number(n.id), Math.round(n.position.x), Math.round(n.position.y))}
        nodesConnectable={false}
        onlyRenderVisibleElements
        fitView
        minZoom={0.05}
        maxZoom={2}
      >
        <Background gap={24} />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable bgColor="hsl(var(--card))" maskColor="hsl(var(--muted) / 0.6)" className="hidden md:block" nodeColor={(n) => (n.type === 'booth' ? '#94a3b8' : 'transparent')} />
      </ReactFlow>
    </div>
  )
}
