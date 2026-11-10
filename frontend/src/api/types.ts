// Types mirroring docs/API.md (v0.1). If the backend deviates, adjust here and in client.ts.
// Fields marked "assumed" are not spelled out in the contract; the UI treats them as optional.

export type Role = 'lead' | 'supplier' | 'both' | 'ignore'
export type Priority = 'must_visit' | 'nice_to_visit' | 'skip'
export type Kind = 'lead' | 'supplier' | 'both' | 'unmapped' | 'ignore'
export type LeadStatus = 'new' | 'met' | 'follow_up' | 'talking' | 'parked'

export const ROLES: Role[] = ['lead', 'supplier', 'both', 'ignore']
export const PRIORITIES: Priority[] = ['must_visit', 'nice_to_visit', 'skip']
export const KINDS: Kind[] = ['lead', 'supplier', 'both', 'unmapped', 'ignore']
export const LEAD_STATUSES: LeadStatus[] = ['new', 'met', 'follow_up', 'talking', 'parked']
export const BOARD_STATUSES: LeadStatus[] = ['new', 'met', 'follow_up', 'talking']

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Me {
  email: string
  name: string
  roles: string[]
  is_editor: boolean
}

// ---------- conventions ----------
export interface ConventionCounts {
  appearances: number
  mapped: number
  visited: number
  leads: number
}
export interface Convention {
  id: number
  name: string
  slug: string
  city: string | null
  country: string | null
  starts_on: string | null
  ends_on: string | null
  counts: ConventionCounts
  venue_map_url?: string | null
}
export interface ConventionCreate {
  name: string
  slug: string
  city?: string
  country?: string
  starts_on?: string
  ends_on?: string
}

// ---------- imports ----------
export interface ImportConflict {
  company_id: number
  company: string
  field: string
  app_value: unknown
  file_value: unknown
}
export interface ImportReport {
  // per-sheet counts; keys like created/updated/skipped/conflicts/rows (shape assumed: flat numbers)
  sheets?: Record<string, Record<string, number>>
  conflicts?: (ImportConflict & { contact_id?: number })[]
  errors?: { row: number | string; message: string; sheet?: string }[]
  leads_created?: number
  suggested?: unknown
  venue?: unknown
  original_name?: string
  from_batch_id?: number | null
  applied_batch_id?: number | null
  failed?: boolean | string | null
}
export interface ImportBatch {
  id: number
  convention_id: number
  convention_slug?: string
  actor?: string | null
  source: string | null
  file: string | null
  dry_run: boolean
  rows: number
  created: number
  updated: number
  skipped: number
  conflicts: number
  report: ImportReport | null
  at: string
}

// ---------- companies ----------
export interface AppearanceBrief {
  convention_slug: string
  hall: string | null
  booth: string | null
  role: Role | null
  priority: Priority | null
}
export interface CompanyListItem {
  id: number
  name: string
  domain: string | null
  country: string | null
  city: string | null
  website: string | null
  categories: string[]
  kind: Kind
  sap_card_code: string | null
  lead_id: number | null
  lead_status: LeadStatus | null
  appearances: AppearanceBrief[]
}
export interface Facet {
  value: string
  count: number
}
export interface Facets {
  countries: Facet[]
  categories: Facet[]
  roles: Facet[]
}
export interface Contact {
  id: number
  company_id?: number
  name: string | null
  title: string | null
  email: string | null
  phone: string | null
  edited_fields?: string[]
}
/** GET /api/contacts/{id} (backend addition). */
export interface ContactDetail extends Contact {
  company: { id: number; name: string } | null
  leads?: CompanyLeadBrief[]
}
export interface ContactInput {
  name?: string | null
  title?: string | null
  email?: string | null
  phone?: string | null
}
export interface Tag {
  id: number
  name: string
  group: string | null
  group_id?: number | null
  suggested: boolean
  confirmed: boolean
}
export interface Mapping {
  suggested_role: Role | null
  suggested_priority: Priority | null
  confirmed_by: string | null
  confirmed_at: string | null
}
export interface Dispatch {
  assignee: string | null
  visited: boolean
  visited_at: string | null
  note: string | null
}
/** Appearance as embedded in the company detail (assumed superset of AppearanceBrief). */
export interface CompanyAppearance extends AppearanceBrief {
  id: number
  convention_id?: number
  convention_name?: string
  convention_starts_on?: string | null
  hall_booth_raw?: string | null
  met_at_booth?: boolean | null
  tags?: Tag[]
  mapping?: Mapping | null
  dispatch?: Dispatch | null
}
export interface CompanyLeadBrief {
  id: number
  status: LeadStatus
  owner: string | null
  follow_up_on: string | null
  notes: string | null
  contact_id?: number | null
  appearance_id?: number | null
  convention_slug?: string | null
  created_at?: string
  updated_at?: string
}
export interface CompanyDetail {
  id: number
  name: string
  name_normalized?: string
  domain: string | null
  country: string | null
  city: string | null
  address: string | null
  phone: string | null
  primary_email: string | null
  website: string | null
  categories: string[]
  description: string | null
  profile_url: string | null
  sap_card_code: string | null
  source?: string | null
  kind: Kind
  contacts: Contact[]
  appearances: CompanyAppearance[]
  leads: CompanyLeadBrief[]
  edited_fields: string[]
}
export type CompanyPatch = Partial<
  Pick<
    CompanyDetail,
    'name' | 'domain' | 'country' | 'city' | 'address' | 'phone' | 'primary_email' | 'website' | 'categories' | 'description' | 'profile_url'
  >
>

// ---------- leads ----------
export interface LeadListItem {
  id: number
  company: { id: number; name: string }
  contact: { id: number; name: string; email: string | null } | null
  owner: string | null
  status: LeadStatus
  notes: string | null
  follow_up_on: string | null
  overdue: boolean
  last_note: string | null
  linked_case_count: number
  convention_slug: string | null
  updated_at: string
  // backend additions
  company_id?: number
  contact_id?: number | null
  appearance_id?: number | null
  created_at?: string
  pending_suggestion_count?: number
}
export type Lead = LeadListItem
export interface LeadPatch {
  status?: LeadStatus
  owner?: string | null
  follow_up_on?: string | null
  notes?: string | null
}
export interface FollowInput {
  owner?: string
  contact_id?: number
  appearance_id?: number
  notes?: string
}
export interface LeadActivity {
  kind: string
  at: string
  actor: string | null
  data: Record<string, unknown> | null
}
export interface LeadCase {
  loop_case_id: string
  how: 'manual' | 'suggested'
  linked_at: string
  linked_by: string | null
  story: Record<string, unknown> | null
  quotation: Record<string, unknown> | null
  order: Record<string, unknown> | null
  available: boolean
  reason?: string | null
}
/** Shape assumed from the case_suggestions table. */
export interface CaseSuggestion {
  id: number
  lead_id?: number
  loop_case_id: string
  reason: 'card_code' | 'contact_email' | 'domain' | string
  status: 'pending' | 'accepted' | 'dismissed'
  created_at?: string
  story?: Record<string, unknown> | null
}

export interface SapCard {
  card_code: string
  card: Record<string, unknown> | null
  text?: string | null
}
export interface SapSearch {
  query: string
  matches: Record<string, unknown>[]
  more?: boolean
}
export interface SupplierPrices {
  query?: string | null
  item_code?: string | null
  prices: Record<string, unknown>[]
}

/** Live MCP reads: either the payload or {available:false, reason}. */
export type McpUnavailable = { available: false; reason?: string }
export type McpResult<T> = (T & { available?: true }) | McpUnavailable
export function isUnavailable(r: unknown): r is McpUnavailable {
  return !!r && typeof r === 'object' && (r as { available?: unknown }).available === false
}

// ---------- meetings ----------
export interface MeetingAction {
  id: number
  text: string
  owner: string | null
  due_on: string | null
  done_at: string | null
}
export interface Meeting {
  id: number
  company_id: number
  company_name: string
  lead_id: number | null
  appearance_id: number | null
  met_on: string
  starts_at: string | null
  place: string | null
  met_by: string[]
  summary_md: string | null
  source: string | null
  contacts: { id: number; name: string; email?: string | null; title?: string | null }[]
  actions: MeetingAction[]
  created_by: string | null
  created_at: string
  updated_at?: string
}
export interface MeetingCreate {
  company_id: number
  met_on: string
  lead_id?: number
  appearance_id?: number
  starts_at?: string
  place?: string
  met_by: string[]
  summary_md?: string
  contact_ids: number[]
  actions: { text: string; owner?: string; due_on?: string }[]
  source?: string
}

// ---------- exhibitions ----------
export interface Appearance {
  id: number
  company: { id: number; name: string; country: string | null; website: string | null; categories: string[] }
  hall: string | null
  booth: string | null
  hall_booth_raw: string | null
  role: Role | null
  priority: Priority | null
  mapping: Mapping | null
  tags: Tag[]
  dispatch: Dispatch | null
  lead_id: number | null
  met_at_booth?: boolean | null
}
export interface AppearancePatch {
  role?: Role | null
  priority?: Priority | null
  met_at_booth?: boolean
}
export interface BulkInput {
  ids: number[]
  role?: Role
  priority?: Priority
  add_tag_ids?: number[]
  remove_tag_ids?: number[]
  assignee?: string | null
  confirm?: boolean
}
/** Shape assumed: one row per raw organizer category. */
export interface CategoryRow {
  category: string
  count: number
  tag_ids: number[]
  rules?: { id: number; tag_id: number }[]
  keyword?: string | null
}
export interface TagWithCount {
  id: number
  name: string
  count: number
  group_id?: number | null
  confirmed_count?: number
}
export interface TagList {
  groups: { id: number; name: string; tags: TagWithCount[] }[]
  ungrouped: TagWithCount[]
}
export interface CoverageStats {
  unplaced?: number
  total: number
  visited: number
  must_visit_uncovered: number
  skipped: number
}
export interface VenueNode {
  id: number
  parent_id: number | null
  kind: 'floor' | 'hall' | 'room' | 'booth'
  label: string
  x: number | null
  y: number | null
  stats: CoverageStats
}
export interface CoverageBooth {
  node_id: number
  appearance_id: number
  company_id?: number // assumed; falls back to opening via appearance
  company_name: string
  priority: Priority | null
  visited: boolean
  role: Role | null
  suggested_role?: Role | null
  tags?: { tag_id: number; confirmed: boolean }[]
}
export interface Coverage {
  nodes: VenueNode[]
  booths: CoverageBooth[]
}
export interface DispatchBoard {
  halls: { hall: string | null; appearances: Appearance[] }[]
}
export interface DispatchPut {
  assignee?: string | null
  visited?: boolean
  note?: string | null
}
/** GET /floor/{person}?hall= — person "all" lists everything not ignored/skipped. */
export interface FloorList {
  person: string
  hall: string | null
  halls: (string | null)[]
  items: Appearance[]
}
export interface FloorNoteResult {
  meeting: Meeting
  contact_id: number | null
  dispatch: Dispatch
}
export interface FloorNoteInput {
  text: string
  contact?: { name: string; email?: string; title?: string; phone?: string }
}

// ---------- search ----------
export interface SearchResult {
  companies: { id: number; name: string; country: string | null }[]
  contacts: { id: number; name: string; email: string | null; company_id: number; company_name: string }[]
  meetings: { id: number; company_id: number; company_name: string; met_on: string; snippet: string }[]
}
