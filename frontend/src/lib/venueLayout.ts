// ELK layout for the coverage hierarchy: floor → hall/room → booth, as nested boxes.
// Runs ELK in a web worker so a 3,000+ booth show doesn't freeze the page.
import ELK from 'elkjs/lib/elk-api'
import type { ElkNode } from 'elkjs/lib/elk-api'
import type { CoverageBooth, VenueNode } from '@/api/types'

let elk: InstanceType<typeof ELK> | null = null
function getElk() {
  if (!elk) {
    elk = new ELK({
      workerFactory: () => new Worker(new URL('elkjs/lib/elk-worker.min.js', import.meta.url)),
    } as ConstructorParameters<typeof ELK>[0])
  }
  return elk
}

export const BOOTH_W = 156
export const boothHeight = (companies: number) => 30 + 16 * Math.min(Math.max(companies, 1), 3) + (companies > 3 ? 14 : 0)

export interface LaidOut {
  id: string
  node: VenueNode
  parent?: string
  x: number
  y: number
  width: number
  height: number
  booths: CoverageBooth[]
}

const containerOpts = {
  'elk.algorithm': 'rectpacking',
  'elk.padding': '[top=44,left=12,bottom=12,right=12]',
  'elk.spacing.nodeNode': '10',
  'elk.aspectRatio': '1.6',
  'elk.nodeSize.constraints': 'MINIMUM_SIZE',
  'elk.nodeSize.minimum': '(300, 90)',
}

export async function layoutVenue(nodes: VenueNode[], booths: CoverageBooth[]): Promise<LaidOut[]> {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const kids = new Map<number | null, VenueNode[]>()
  for (const n of nodes) {
    const p = n.parent_id !== null && byId.has(n.parent_id) ? n.parent_id : null
    if (!kids.has(p)) kids.set(p, [])
    kids.get(p)!.push(n)
  }
  const boothsByNode = new Map<number, CoverageBooth[]>()
  for (const b of booths) {
    if (!boothsByNode.has(b.node_id)) boothsByNode.set(b.node_id, [])
    boothsByNode.get(b.node_id)!.push(b)
  }
  const natural = (a: VenueNode, b: VenueNode) => a.label.localeCompare(b.label, undefined, { numeric: true })

  const build = (n: VenueNode): ElkNode => {
    const children = (kids.get(n.id) ?? []).sort(natural)
    if (n.kind === 'booth' || children.length === 0) {
      const c = boothsByNode.get(n.id)?.length ?? 0
      const isContainer = n.kind !== 'booth'
      return { id: String(n.id), width: isContainer ? 180 : BOOTH_W, height: isContainer ? 70 : boothHeight(c) }
    }
    return { id: String(n.id), layoutOptions: containerOpts, children: children.map(build) }
  }

  const graph: ElkNode = {
    id: 'root',
    layoutOptions: { ...containerOpts, 'elk.padding': '[top=0,left=0,bottom=0,right=0]', 'elk.spacing.nodeNode': '40', 'elk.aspectRatio': '1.8' },
    children: (kids.get(null) ?? []).sort(natural).map(build),
  }
  const res = await getElk().layout(graph)

  const out: LaidOut[] = []
  const walk = (e: ElkNode, parent?: string) => {
    const n = byId.get(Number(e.id))!
    out.push({
      id: e.id,
      node: n,
      parent,
      // a position someone saved by dragging wins over the automatic layout
      x: n.x ?? e.x ?? 0,
      y: n.y ?? e.y ?? 0,
      width: e.width ?? BOOTH_W,
      height: e.height ?? 40,
      booths: boothsByNode.get(n.id) ?? [],
    })
    for (const c of e.children ?? []) walk(c, e.id)
  }
  for (const c of res.children ?? []) walk(c)
  return out
}
