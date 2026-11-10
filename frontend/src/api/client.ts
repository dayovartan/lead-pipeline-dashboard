// Small fetch client for /api. Every endpoint the UI calls is listed here, mirroring docs/API.md.
import { qs } from '@/lib/utils'
import type {
  Appearance,
  AppearancePatch,
  BulkInput,
  CaseSuggestion,
  CategoryRow,
  CompanyDetail,
  CompanyListItem,
  CompanyPatch,
  Contact,
  ContactDetail,
  ContactInput,
  Convention,
  ConventionCreate,
  Coverage,
  DispatchBoard,
  DispatchPut,
  Facets,
  FloorList,
  FloorNoteInput,
  FloorNoteResult,
  FollowInput,
  ImportBatch,
  Lead,
  LeadActivity,
  LeadCase,
  LeadListItem,
  LeadPatch,
  Me,
  McpResult,
  Meeting,
  MeetingAction,
  MeetingCreate,
  Page,
  SapCard,
  SapSearch,
  SearchResult,
  SupplierPrices,
  TagList,
} from './types'

export const API_BASE = '/api'

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `HTTP ${status}`)
    this.status = status
    this.detail = detail
  }
}

type Params = Record<string, string | number | boolean | null | undefined>

async function request<T>(method: string, path: string, body?: unknown, params?: Params): Promise<T> {
  const init: RequestInit = { method, credentials: 'same-origin', headers: { Accept: 'application/json' } }
  if (body instanceof FormData) {
    init.body = body
  } else if (body !== undefined) {
    init.body = JSON.stringify(body)
    ;(init.headers as Record<string, string>)['Content-Type'] = 'application/json'
  }
  const res = await fetch(API_BASE + path + (params ? qs(params) : ''), init)
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      const j = await res.json()
      detail = j?.detail ?? j
    } catch {
      /* not json */
    }
    if (Array.isArray(detail)) detail = detail.map((d) => d?.msg ?? JSON.stringify(d)).join('; ')
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  const ct = res.headers.get('content-type') ?? ''
  return (ct.includes('application/json') ? res.json() : res.text()) as Promise<T>
}

const get = <T>(p: string, params?: Params) => request<T>('GET', p, undefined, params)
const post = <T>(p: string, body?: unknown) => request<T>('POST', p, body ?? {})
const patch = <T>(p: string, body: unknown) => request<T>('PATCH', p, body)
const put = <T>(p: string, body: unknown) => request<T>('PUT', p, body)
const del = <T>(p: string) => request<T>('DELETE', p)
const enc = encodeURIComponent

/** Plain URLs for downloads (template, exports) — opened with <a href>. */
export const urls = {
  template: `${API_BASE}/imports/template.xlsx`,
  companyExport: (id: number) => `${API_BASE}/companies/${id}/export.md`,
  meetingExport: (id: number) => `${API_BASE}/meetings/${id}/export.md`,
  dispatchExport: (slug: string, p: { assignee?: string; tag?: string; role?: string; priority?: string } = {}) =>
    `${API_BASE}/conventions/${enc(slug)}/dispatch/export.xlsx${qs(p)}`,
}

export const api = {
  me: () => get<Me>('/me'),
  search: (q: string) => get<SearchResult>('/search', { q, limit: 10 }),

  // conventions
  conventions: () => get<Convention[]>('/conventions'),
  convention: (slug: string) => get<Convention>(`/conventions/${enc(slug)}`),
  createConvention: (b: ConventionCreate) => post<Convention>('/conventions', b),
  uploadVenueMap: (slug: string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return post<Convention>(`/conventions/${enc(slug)}/venue-map`, fd)
  },

  // imports
  uploadImport: (slug: string, file: File, dryRun = true) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('convention_slug', slug)
    fd.append('dry_run', String(dryRun))
    return post<ImportBatch>('/imports', fd)
  },
  applyImport: (id: number) => post<ImportBatch>(`/imports/${id}/apply`),
  imports: (slug: string) => get<ImportBatch[]>('/imports', { convention_slug: slug }),
  importBatch: (id: number) => get<ImportBatch>(`/imports/${id}`),

  // companies
  companies: (p: Params) => get<Page<CompanyListItem>>('/companies', p),
  facets: (convention?: string) => get<Facets>('/companies/facets', { convention }),
  company: (id: number) => get<CompanyDetail>(`/companies/${id}`),
  patchCompany: (id: number, b: CompanyPatch) => patch<CompanyDetail>(`/companies/${id}`, b),
  mergeCompany: (id: number, into_id: number) => post<CompanyDetail>(`/companies/${id}/merge`, { into_id }),
  addContact: (companyId: number, b: ContactInput) => post<Contact>(`/companies/${companyId}/contacts`, b),
  patchContact: (id: number, b: ContactInput) => patch<Contact>(`/contacts/${id}`, b),
  /** Beyond API.md v0.1 (added by the backend): contact + company + leads. */
  contact: (id: number) => get<ContactDetail>(`/contacts/${id}`),
  meeting: (id: number) => get<Meeting>(`/meetings/${id}`),
  sapLink: (id: number, card_code: string) => post<unknown>(`/companies/${id}/sap-link`, { card_code }),
  sapUnlink: (id: number) => del<unknown>(`/companies/${id}/sap-link`),
  sapCard: (id: number) => get<McpResult<SapCard>>(`/companies/${id}/sap-card`),
  sapSearch: (id: number, q: string) => get<McpResult<SapSearch>>(`/companies/${id}/sap-search`, { q }),
  supplierPrices: (id: number, p?: { q?: string; item_code?: string }) =>
    get<McpResult<SupplierPrices>>(`/companies/${id}/supplier-prices`, p),

  // leads
  follow: (companyId: number, b: FollowInput = {}) => post<Lead>(`/companies/${companyId}/leads`, b),
  leads: (p: Params) => get<Page<LeadListItem> | LeadListItem[]>('/leads', p),
  lead: (id: number) => get<Lead>(`/leads/${id}`),
  patchLead: (id: number, b: LeadPatch) => patch<Lead>(`/leads/${id}`, b),
  leadActivity: (id: number) => get<LeadActivity[]>(`/leads/${id}/activity`),
  leadCases: (id: number) => get<LeadCase[] | McpResult<{ items: LeadCase[] }>>(`/leads/${id}/cases`),
  linkCase: (id: number, loop_case_id: string) => post<unknown>(`/leads/${id}/cases`, { loop_case_id }),
  unlinkCase: (id: number, caseId: string) => del<unknown>(`/leads/${id}/cases/${enc(caseId)}`),
  suggestions: (id: number) => get<CaseSuggestion[] | McpResult<{ items: CaseSuggestion[] }>>(`/leads/${id}/suggestions`),
  acceptSuggestion: (id: number, sid: number) => post<unknown>(`/leads/${id}/suggestions/${sid}/accept`),
  dismissSuggestion: (id: number, sid: number) => post<unknown>(`/leads/${id}/suggestions/${sid}/dismiss`),

  // meetings
  meetings: (p: { company_id?: number; contact_id?: number; lead_id?: number }) => get<Meeting[]>('/meetings', p),
  createMeeting: (b: MeetingCreate) => post<Meeting>('/meetings', b),
  patchMeeting: (id: number, b: Partial<MeetingCreate>) => patch<Meeting>(`/meetings/${id}`, b),
  addAction: (id: number, b: { text: string; owner?: string; due_on?: string }) =>
    post<MeetingAction>(`/meetings/${id}/actions`, b),
  patchAction: (id: number, aid: number, b: { text?: string; owner?: string; due_on?: string; done?: boolean }) =>
    patch<MeetingAction>(`/meetings/${id}/actions/${aid}`, b),

  // exhibitions
  appearances: (slug: string, p: Params) => get<Page<Appearance>>(`/conventions/${enc(slug)}/appearances`, p),
  patchAppearance: (slug: string, id: number, b: AppearancePatch) =>
    patch<Appearance>(`/conventions/${enc(slug)}/appearances/${id}`, b),
  bulk: (slug: string, b: BulkInput) => post<unknown>(`/conventions/${enc(slug)}/appearances/bulk`, b),
  addTag: (slug: string, id: number, tag_id: number) =>
    post<unknown>(`/conventions/${enc(slug)}/appearances/${id}/tags`, { tag_id }),
  removeTag: (slug: string, id: number, tag_id: number) =>
    del<unknown>(`/conventions/${enc(slug)}/appearances/${id}/tags/${tag_id}`),
  confirmTag: (slug: string, id: number, tag_id: number) =>
    post<unknown>(`/conventions/${enc(slug)}/appearances/${id}/tags/${tag_id}/confirm`),
  suggest: (slug: string) => post<Record<string, number>>(`/conventions/${enc(slug)}/suggest`),
  categories: (slug: string) => get<CategoryRow[]>(`/conventions/${enc(slug)}/categories`),
  tags: (slug: string) => get<TagList>(`/conventions/${enc(slug)}/tags`),
  createTagGroup: (slug: string, name: string) => post<{ id: number }>(`/conventions/${enc(slug)}/tag-groups`, { name }),
  createTag: (slug: string, name: string, group_id?: number | null) =>
    post<{ id: number }>(`/conventions/${enc(slug)}/tags`, { name, group_id: group_id ?? undefined }),
  patchTag: (slug: string, id: number, b: { name?: string; group_id?: number | null }) =>
    patch<unknown>(`/conventions/${enc(slug)}/tags/${id}`, b),
  createCategoryRule: (slug: string, category: string, tag_id: number) =>
    post<{ id: number }>(`/conventions/${enc(slug)}/category-rules`, { category, tag_id }),
  deleteCategoryRule: (slug: string, id: number) => del<unknown>(`/conventions/${enc(slug)}/category-rules/${id}`),
  coverage: (slug: string) => get<Coverage>(`/conventions/${enc(slug)}/coverage`),
  rebuildVenue: (slug: string) => post<unknown>(`/conventions/${enc(slug)}/venue/rebuild`),
  moveNode: (slug: string, id: number, x: number, y: number) =>
    patch<unknown>(`/conventions/${enc(slug)}/venue/nodes/${id}`, { x, y }),
  dispatch: (slug: string, p: Params) => get<DispatchBoard>(`/conventions/${enc(slug)}/dispatch`, p),
  putDispatch: (slug: string, id: number, b: DispatchPut) =>
    put<unknown>(`/conventions/${enc(slug)}/appearances/${id}/dispatch`, b),
  floor: (slug: string, person: string, hall?: string) =>
    get<FloorList>(`/conventions/${enc(slug)}/floor/${enc(person)}`, { hall }),
  floorNote: (slug: string, appearanceId: number, b: FloorNoteInput) =>
    post<FloorNoteResult>(`/conventions/${enc(slug)}/floor/${appearanceId}/note`, b),
  floorFollow: (slug: string, appearanceId: number, b: { owner?: string; contact_id?: number; notes?: string } = {}) =>
    post<Lead & { created?: boolean }>(`/conventions/${enc(slug)}/floor/${appearanceId}/follow`, b),
}

/** Accept either a page envelope or a bare array (the contract pages most lists; be tolerant). */
export function itemsOf<T>(r: Page<T> | T[] | { items: T[] } | undefined | null): T[] {
  if (!r) return []
  if (Array.isArray(r)) return r
  return r.items ?? []
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403) return 'You need the editor role for this.'
    if (e.status === 409 && typeof e.detail !== 'string') return 'That conflicts with the current state; refresh and try again.'
    return typeof e.detail === 'string' ? e.detail : e.message
  }
  if (e instanceof Error) return e.message
  return String(e)
}
