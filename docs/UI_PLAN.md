# Lead Pipeline Dashboard — UI plan (draft 2)

**Status: planning only — nothing built.** Companion to [LEADS_PLAN.md](LEADS_PLAN.md) (V2) and [EXHIBITION_MAPPING_PLAN.md](EXHIBITION_MAPPING_PLAN.md).

One app, two knowledge bases, one flow from show floor to signed case.

---

## 1. Stack (chosen)

This is its own app: own repo, deployment, Entra app (`leads-auth`), backend and frontend. Nothing is copied from Mission Control's stack.

- **Frontend:** one React SPA, Vite + TypeScript. React Router for the two routes, TanStack Query for API data, TanStack Table for the big tables (server-side paging, sort and filter; 3,665+ rows).
- **UI kit:** Tailwind CSS + shadcn/ui (Radix-based, copied into the repo, no runtime dependency to track). Good keyboard and phone behaviour out of the box.
- **Diagrams:** React Flow (`@xyflow/react`, MIT) for the floor → hall/room → booth → company hierarchy, with ELK.js (`elkjs`, EPL) for automatic nested layout and dotted group frames. Chosen over Cytoscape.js and JointJS because nested groups, custom React nodes and drag-to-save positions are first-class, and the free tier covers it.
- **Markdown:** `@uiw/react-md-editor` for meeting summaries (edit + preview), same component in read-only mode elsewhere.
- **Backend:** FastAPI + SQLAlchemy/Alembic + Postgres 16, served from the same `leads` container that serves the built SPA as static files.
- **Floor list:** a phone-first route of the same SPA, installable as a PWA so it opens without signal and queues taps until it's back online (open question 1).
- **Exports:** Excel (openpyxl) and print from the API; Obsidian markdown export for meetings.

---

## 2. Site map

```
leads.dayo-tech.com
├── /leads                         Leads knowledge base (after the floor)
│   ├── /leads/board               followed leads, columns by status
│   ├── /leads/companies           directory: companies + suppliers, search, filters
│   ├── /leads/companies/:id       company window (drawer on desktop, page on phone)
│   └── /leads/contacts/:id        contact window
├── /exhibitions                   Exhibition knowledge base (before and at the show)
│   ├── /exhibitions               list of shows (electronica 2026, …) + "New show"
│   └── /exhibitions/:slug
│       ├── /intake                Excel load: dry run, counts, conflicts, history
│       ├── /map                   role / tags / priority per appearance, bulk edit
│       ├── /tags                  the show's tag list and groups (decided per show)
│       ├── /coverage              venue map or React Flow hierarchy, visited vs not
│       ├── /dispatch              hall-grouped board, filters, assign, export
│       └── /floor/:person         phone floor list: checkboxes + quick note
└── (shared)                       top bar: route switch, show picker, global search, user
```

The **show picker** in the top bar sets the current convention for both routes (Leads filters by it, Exhibitions works inside it).

---

## 3. Shared pieces

- **Company window** — one component used in both routes, with tabs that depend on the route:
  - Always: details, contacts, appearances across shows (hall/booth per show), meeting notes.
  - Exhibitions route: role, tags, priority, visit status. No MCP calls.
  - Leads route: lead status, owner, follow-up, linked and suggested cases (cases-mcp), SAP card and quote/order numbers (sap-mcp), mail threads (cases-mcp `search_mails`).
- **Meetings timeline** — newest first. A meeting is a dated entry: date (and time if known), place or show, who met (people picker), company, contacts, a markdown summary, and **follow-up actions** (text, owner, due date, done). “Add meeting” opens the editor inline. Pressing a card on the leads board opens this timeline for that company or contact. Email and Microsoft 365 calendar sync come later, from the dashboard, not in this phase.
- **Global search** — one box: companies, contacts, notes text (`ILIKE` / built-in full text).
- **Tags** — chips grouped by tag group, usable as filters everywhere.

---

## 4. Screens, one line each

**Leads**
- **Board:** columns new / met / follow_up / talking (parked hidden). Card: company, contact, owner, follow-up date (overdue in red), last note line, linked-case count. Filters: show, owner, tag group, role.
- **Companies:** table with filters (show, role, tag, country, has lead, SAP-linked). Row opens the company window. “Follow” creates a lead.

**Exhibitions**
- **Intake:** upload the Excel, see a dry run (new / updated / unchanged / conflicts), then load. Batch history.
- **Map:** the exhibitor table with role, tag and priority columns; suggested values shown dashed until confirmed; bulk select and set.
- **Tags:** raw organizer categories with counts → map them to our tags and groups for this show.
- **Coverage:** venue map image if the show has one (reference, with hall overlay counts), otherwise the React Flow hierarchy. Colour by status: must-visit uncovered, visited, skipped. Click a booth → company window.
- **Dispatch:** hall columns sorted by booth, filtered by tag, role and priority; optional assignee; “Export floor list” (Excel, print, phone link).
- **Floor list (phone):** one hall at a time, booth order, big checkbox, one-line note, “add contact”, “follow this company” (creates a lead). Saves each tap.

---

## 5. The hand-off between the two routes

At the show, “visited” plus a note is captured on the floor list. Two actions link the routes:
1. **Note** — a floor note is stored as a short meeting (`source = floor`), so it shows up in the Leads timeline later.
2. **Follow** — creates a lead from the appearance (company, contact, show), visible on the Leads board.

Nothing else crosses over: Exhibitions never calls an MCP, and Leads reads exhibition data only through the shared company, contact, appearance and note tables.

---

## 6. Data this UI relies on

All in the app's own database (`leads-db`), defined in LEADS_PLAN.md section 6 and EXHIBITION_MAPPING_PLAN.md section 4:

- `meetings`, `meeting_contacts`, `meeting_actions` — the timeline and its follow-ups.
- `convention_appearances.role` (`lead` / `supplier` / `both` / `ignore`) and `priority`, per show. The company “kind” shown in the UI is derived from these.
- `hardware_tags`, `tag_groups`, `appearance_tags` — chips and filters.
- `venue_nodes` — the coverage diagram, filled from hall/booth on import, positions saved when people drag.
- `dispatch_assignments` — visited, who, note.

## 7. Deploy and persistence

```
leads stack (docker compose -p leads)
├── leads      FastAPI API + built SPA   networks: leads-front, leads-data   no state
├── leads-db   Postgres 16               network: leads-data                 volume: leads-pgdata (external)
└── volume leads-files (external)        Excel uploads, venue map images
leads-auth (dayo-internal-services/stacks/sso)   networks: proxy, leads-front
```

- Volumes are `external: true`, created once with `docker volume create`, so `docker compose down`, `up`, a rebuild or `down -v` never deletes data. The `leads` image holds no state, so the frontend and backend can be rebuilt freely.
- Migrations run on container start and only add.
- A nightly `pg_dump` plus a copy of `leads-files` is still needed: a surviving volume isn't a backup.

---

## 8. Open UI questions

1. Floor list offline: is a saved-for-offline page enough (it queues taps until signal), or must it work fully offline all day?
2. Should Leads and Exhibitions share one company table view with a route-specific column set, or stay two separate tables?
3. Who may edit what in Exhibitions (viewer vs editor), or is everyone an editor at a show?
