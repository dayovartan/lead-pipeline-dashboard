# API contract (v0.1)

The contract between `backend/` and `frontend/`. All under `/api`, JSON, snake_case.
Lists page with `?page=1&page_size=50` and return `{items, total, page, page_size}`.
Writes need the `leads_editor` role (403 otherwise). Errors: `{detail}`.

Derived company **kind** (never stored): from the roles on the company's appearances.
`supplier` if any role is supplier or both and none is lead; `lead` if lead/both and no supplier;
`both` if both sides appear; `unmapped` if no confirmed role; `ignore` if every role is ignore.

## Session
- `GET /api/me` → `{email, name, roles[], is_editor}`
- `GET /api/healthz`

## Conventions (exhibitions router)
- `GET /api/conventions` → `[{id, name, slug, city, country, starts_on, ends_on, counts: {appearances, mapped, visited, leads}}]`
- `POST /api/conventions` `{name, slug, city?, country?, starts_on?, ends_on?}`
- `GET /api/conventions/{slug}` → convention + counts + `venue_map_url|null`
- `POST /api/conventions/{slug}/venue-map` (multipart file) → stores on leads-files

## Imports (imports router) — Excel intake
- `POST /api/imports` multipart: `file` (xlsx), `convention_slug`, `dry_run` (default `true`).
  Returns the batch: `{id, convention_id, source, file, dry_run, rows, created, updated, skipped, conflicts, report, at}`.
  `report` = `{sheets: {exhibitors: {...counts}, contacts: {...counts}}, conflicts: [{company_id, company, field, app_value, file_value}], errors: [{row, message}], leads_created}`.
  A dry run writes nothing except the batch row. `POST /api/imports/{id}/apply` runs the same file for real.
- `GET /api/imports?convention_slug=` → batch list. `GET /api/imports/{id}` → one batch.
- `GET /api/imports/template.xlsx` → an empty workbook with the expected sheets and columns.

Expected workbook (LEADS_PLAN 14): sheet **Exhibitors**: Company, Country, City, Address, Phone,
Primary email, Website, Hall/Booth, Categories, Description, Profile URL, Met at booth, Lead status,
Owner, Notes, Follow-up date, Meeting note. Sheet **Contacts**: Company, Name, Title, Email, Phone.
Headers matched case-insensitively. Categories split on `;`, `,` or newline.

## Companies (companies router)
- `GET /api/companies?q=&convention=<slug>&role=&kind=&country=&category=&tag=&has_lead=&sap_linked=&met=&sort=name&page=`
  → items: `{id, name, domain, country, city, website, categories[], kind, sap_card_code, lead_id|null, lead_status|null, appearances: [{convention_slug, hall, booth, role, priority}]}`
- `GET /api/companies/facets?convention=` → `{countries: [{value, count}], categories: [...], roles: [...]}`
- `GET /api/companies/{id}` → company (all columns except raw) + `kind`, `contacts[]`, `appearances[]` (with tags, mapping, dispatch), `leads[]`, `edited_fields[]`
- `PATCH /api/companies/{id}` partial catalogue fields → adds them to `edited_fields`
- `POST /api/companies/{id}/merge {into_id}` manual merge
- `POST /api/companies/{id}/contacts`, `PATCH /api/contacts/{id}` (adds to `edited_fields`)
- `POST /api/companies/{id}/sap-link {card_code}`; `DELETE` same path clears it
- `GET /api/companies/{id}/export.md` Obsidian export

## Leads (leads router)
- `POST /api/companies/{id}/leads {owner?, contact_id?, appearance_id?, notes?}` — "Follow"
- `GET /api/leads?status=&owner=&convention=&q=&include_parked=false` → items: `{id, company: {id, name}, contact: {id, name, email}|null, owner, status, notes, follow_up_on, overdue, last_note, linked_case_count, convention_slug|null, updated_at}`. Sorted by follow_up_on nulls last.
- `GET /api/leads/{id}`, `PATCH /api/leads/{id} {status?, owner?, follow_up_on?, notes?}`
- `GET /api/leads/{id}/activity`
- `GET /api/leads/{id}/cases` → `[{loop_case_id, how, linked_at, linked_by, story: {...}|null, quotation: {...}|null, order: {...}|null, available: bool}]`
- `POST /api/leads/{id}/cases {loop_case_id}`, `DELETE /api/leads/{id}/cases/{loop_case_id}`
- `GET /api/leads/{id}/suggestions` (runs the lookup), `POST /api/leads/{id}/suggestions/{sid}/accept|dismiss`
- `GET /api/companies/{id}/sap-card`, `GET /api/companies/{id}/sap-search?q=`, `GET /api/companies/{id}/supplier-prices` — live MCP reads, `{available: false, reason}` when the MCP is down or no token.

## Meetings (meetings router)
- `GET /api/meetings?company_id=&contact_id=&lead_id=` → `[{id, company_id, company_name, lead_id, appearance_id, met_on, starts_at, place, met_by[], summary_md, source, contacts: [{id, name}], actions: [{id, text, owner, due_on, done_at}], created_by, created_at}]` newest first
- `POST /api/meetings {company_id, met_on, lead_id?, appearance_id?, starts_at?, place?, met_by[], summary_md?, contact_ids[], actions: [{text, owner?, due_on?}], source?}`
- `PATCH /api/meetings/{id}`; `POST /api/meetings/{id}/actions`; `PATCH /api/meetings/{id}/actions/{aid} {text?, owner?, due_on?, done: bool?}`
- `GET /api/meetings/{id}/export.md`
- A lead's `follow_up_on` follows its earliest open action when the lead has none set by hand.

## Exhibitions (exhibitions router), all under `/api/conventions/{slug}`
- `GET /appearances?q=&role=&priority=&tag=&group=&hall=&assignee=&visited=&mapped=&page=` → items: `{id, company: {id, name, country, website, categories[]}, hall, booth, hall_booth_raw, role, priority, mapping: {suggested_role, suggested_priority, confirmed_by, confirmed_at}|null, tags: [{id, name, group, suggested, confirmed}], dispatch: {assignee, visited, visited_at, note}|null, lead_id|null}`
- `PATCH /appearances/{id} {role?, priority?, met_at_booth?}` (confirms mapping)
- `POST /appearances/bulk {ids[], role?, priority?, add_tag_ids[]?, remove_tag_ids[]?, assignee?, confirm?: bool}`
- `POST /appearances/{id}/tags {tag_id}` / `DELETE /appearances/{id}/tags/{tag_id}` / `POST /appearances/{id}/tags/{tag_id}/confirm`
- `POST /suggest` → runs keyword rules + category rules over unconfirmed appearances, returns counts
- `GET /categories` → raw organizer categories with counts and mapped tag ids
- `GET /tags` → `{groups: [{id, name, tags: [{id, name, count}]}], ungrouped: [...]}`; `POST /tag-groups {name}`; `POST /tags {name, group_id?}`; `PATCH /tags/{id} {name?, group_id?}`; `POST /category-rules {category, tag_id}`; `DELETE /category-rules/{id}`
- `GET /coverage` → `{nodes: [{id, parent_id, kind, label, x, y, stats: {total, visited, must_visit_uncovered, skipped}}], booths: [{node_id, appearance_id, company_id, company_name, priority, visited, role, suggested_role, tags: [{tag_id, confirmed}]}]}`; `POST /venue/rebuild` (from hall/booth); `PATCH /venue/nodes/{id} {x, y}`
- `GET /dispatch?tag=&role=&priority=&assignee=` → `{halls: [{hall, appearances: [...same as appearances items]}]}`
- `PUT /appearances/{id}/dispatch {assignee?, visited?, note?}`
- `GET /floor/{person}?hall=` → phone list; `POST /floor/{appearance_id}/note {text, contact?: {name, email, title, phone}}` → creates a short meeting (`source=floor`) and marks visited; `POST /floor/{appearance_id}/follow` → creates a lead
- `GET /dispatch/export.xlsx?assignee=` floor list as Excel

## Search (search router)
- `GET /api/search?q=` → `{companies: [{id, name, country}], contacts: [{id, name, email, company_id, company_name}], meetings: [{id, company_id, company_name, met_on, snippet}]}` (ILIKE + `simple` full text)
