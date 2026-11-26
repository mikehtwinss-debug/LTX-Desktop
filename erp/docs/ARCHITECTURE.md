# ERP — Architecture and Phase 1 contract

`erp/` is a self-contained, self-hosted ERP (materials management, financial accounting, later controlling,
sales, production, …) for Turkish companies. It shares a git repository with an unrelated Electron app.
**Nothing outside `erp/` belongs to this project, and the repository-root `CLAUDE.md` / `AGENTS.md` rules do not
apply here.** This document is the contract every contributor (human or agent) codes against.

The repository is public. Never commit real company names, logos, people's names, tax numbers, credentials or
customer data. Everything company-specific (name, logo, form codes, signer titles) is data entered in the
running system, not code. Demo/seed data uses obviously fictional names ("Örnek Sanayi A.Ş.").

## 1. Scope

| Phase | Content | Status |
|---|---|---|
| 1 | Foundation, FI core (GL, AP/AR, bank/cash, VAT), MM (purchasing, quotation comparison, PO PDF, inventory, invoice verification) | **this phase** |
| 2 | CO: cost element/center accounting, internal orders, profit centers, allocations, budget | later |
| 3 | SD (quotation → order → delivery → invoice) + GİB e-Fatura / e-Arşiv / e-İrsaliye via private integrator | later |
| 4 | Fixed assets, bank reconciliation, cheques/notes, FX revaluation, withholding | later |
| 5 | PP (BOM, routing, production orders, MRP) | later |
| 6 | WM (bins), QM, PM | later |
| 7 | HR / payroll | later |

Phase 1 must leave room for the later phases: cost-object columns already exist on journal and document lines,
partners carry e-invoice fields, units carry UN/ECE codes, stock has a stock type.

## 2. Stack

- **Backend** `erp/backend`: Python 3.13, FastAPI, SQLAlchemy 2.x (sync ORM, typed `Mapped[...]`), psycopg 3,
  Pydantic v2, pydantic-settings, Alembic, PyJWT, argon2-cffi, ReportLab (PDF), openpyxl (Excel), pytest, ruff.
  Dependencies managed with `uv` (`pyproject.toml` + `uv.lock`). Database: PostgreSQL 16 only (no SQLite).
- **Frontend** `erp/frontend`: React 18, TypeScript (strict), Vite, Ant Design 5 (`tr_TR` locale), TanStack Query 5,
  React Router 6, axios, dayjs, big.js. Package manager **npm** with `package-lock.json` (the repo root is a pnpm
  workspace for the other app; never run pnpm inside `erp/`).
- **Deployment**: `erp/docker-compose.yml` — `db` (postgres:16), `backend` (uvicorn), `frontend` (nginx serving
  the Vite build and proxying `/api`), `backup` (scheduled `pg_dump`). No outbound network is required at runtime.

## 3. Layout and ownership

```
erp/
  README.md                 Turkish install/run guide
  CLAUDE.md                 pointer to this document
  docker-compose.yml  .env.example  .gitignore
  docs/ARCHITECTURE.md
  backend/
    pyproject.toml  uv.lock  alembic.ini  Dockerfile
    alembic/                           migrations (single initial migration generated at the end of a phase)
    app/
      main.py                          create_app(), feature discovery
      models.py                        imports every model module (complete metadata)
      core/                            config, db, types, errors, context, transaction route, pagination,
                                       numbering, audit, approval, periods, settings, pdf, excel, storage
      assets/fonts/                    bundled DejaVu Sans (regular, bold) + licence
      seed/                            CLI + data files (TDHP chart, tax codes, units, roles, demo data)
      modules/
        auth/                          users, roles, permissions, login          [foundation]
        org/                           companies, plants, warehouses, purchasing groups, currencies, rates,
                                       units, number ranges, settings, audit viewer, attachments, approvals API
                                                                                 [foundation]
        co/                            cost centers (minimal master data)        [foundation]
        fi/
          models/{gl,partners,treasury,documents}.py                             [foundation writes, feature owns]
          posting.py                   journal posting engine                    [foundation]
          gl/                          chart of accounts, manual journals, periods, reports      [fi.gl]
          partners/                    vendors, customers, payment terms         [fi.partners]
          ap_ar/                       FI invoices, payments, clearing, aging, statements, treasury accounts
                                                                                 [fi.ap_ar]
        mm/
          models/{master,inventory,purchasing,invoice}.py                        [foundation writes, feature owns]
          master/                      materials, groups, valuation classes, account determination  [mm.master]
          inventory/                   movement engine, stock, batches, physical inventory, reports [mm.inventory]
          purchasing/                  requisitions, RFQs, quotations, comparison, purchase orders,
                                       info records, goods receipt for PO, PDFs/Excel                [mm.purchasing]
          invoice/                     supplier invoice verification                                 [mm.invoice]
    tests/
      conftest.py  factories.py        [foundation]
      <feature>/                       one directory per feature, owned by that feature
  frontend/
    package.json  package-lock.json  vite.config.ts  tsconfig.json  index.html  Dockerfile  nginx.conf
    src/
      main.tsx  App.tsx
      app/                             layout, router, auth provider, feature registry, error boundary
      lib/                             api client, formatters, decimal helpers, permissions, query client
      components/                      shared building blocks (section 9)
      modules/<feature>/               index.tsx (registration) + pages + api.ts, owned by that feature
```

A *feature* is a backend package containing `api.py` (and usually `service.py`, `schemas.py`, `permissions.py`)
plus a frontend directory `src/modules/<feature>/`. **A contributor working on a feature edits only that
feature's files** (its backend package, its model file, its tests directory, its frontend directory). Needed
changes to foundation files are made as small additive edits (never rewrites) and reported.

### Feature discovery (no shared registration files)

- Backend: `create_app()` imports every package under `app.modules` (so `__init__.py` side effects such as
  approval-handler and number-range registration run), then includes `router` from every `api.py` it finds.
  `ERP_FEATURES` (comma-separated dotted names relative to `app.modules`, e.g. `auth,org,co,fi.gl`) restricts
  discovery; it exists so that work-in-progress sibling features cannot break someone else's test run.
  `auth`, `org`, `co` are always loaded.
- Each feature declares `PERMISSIONS: dict[str, str]` (key → Turkish description) in `permissions.py`; discovery
  collects them and the seed/startup step syncs them into `auth_permission`.
- Frontend: `src/app/registry.ts` collects `import.meta.glob('../modules/*/index.tsx', { eager: true })`. Each
  `index.tsx` default-exports a `FeatureModule` (`{ key, menu, routes }`). Menu groups are fixed keys:
  `finans`, `malzeme`, `yonetim`.

## 4. Cross-cutting conventions

**Language.** Identifiers, comments, commit messages and this document are English. Everything a user sees is
Turkish: API error messages, UI labels, PDF/Excel text, seed data names. Enum *values* stored in the database
are upper-case English keys (`PENDING_APPROVAL`); the UI maps them to Turkish labels.

**Tables.** snake_case with an area prefix: `auth_`, `org_`, `co_`, `fi_`, `mm_`. Primary keys are `BigInteger`
identity columns named `id`. Business keys (`code`, `number`) are unique per company. Enums use
`sqlalchemy.Enum(PyEnum, native_enum=False, length=32)`.

**Mixins** (`core/db.py`): `IdMixin`; `TimestampMixin` (`created_at`, `updated_at` timestamptz UTC,
`created_by_id`, `updated_by_id` filled automatically from `session.info["user_id"]`); `CompanyMixin`
(`company_id` FK, indexed); `VersionMixin` (`version` int used as SQLAlchemy `version_id_col`; update payloads
carry `version`, a mismatch returns HTTP 409 `STALE_DATA`). Editable master data and editable documents use
`VersionMixin`.

**Numbers.** Never `float`. Column types in `core/types.py`: `Money = Numeric(18, 2)`, `Qty = Numeric(18, 3)`,
`Price = Numeric(18, 6)`, `Rate = Numeric(18, 6)`, `Pct = Numeric(9, 4)`. Helpers `q_money`, `q_qty`, `q_price`
quantize with `ROUND_HALF_UP`. JSON carries decimals as strings; request models accept strings or numbers.
The server is the only authority for totals, taxes and valuations; the UI may preview with big.js.

**Dates.** Business dates are `date`; timestamps are timezone-aware UTC. Fiscal year = calendar year, 12 periods.

**Multi-company.** Every request runs in one company: header `X-Company-Id` (fallback: the user's default
company). The user must hold at least one role in that company. All queries filter by `company_id`.

**Request context.** `core/context.py`: `RequestContext(db, user, company_id)` with `Ctx = Annotated[RequestContext,
Depends(get_ctx)]`. Every service function takes `ctx` first: `def create_po(ctx: RequestContext, data: POCreate)`.
Routes are thin: parse → call service → return schema.

**Transactions.** One database transaction per HTTP request, owned by `core/transaction.py::TransactionalRoute`
(a custom `APIRoute` class set on every router via `APIRouter(route_class=TransactionalRoute)` — use
`core.routing.make_router(prefix, tags)`). The route wrapper creates the session from `app.state.session_factory`,
stores it on `request.state.db`, runs the endpoint, then **commits before the response is returned**, rolls back
on any exception and always closes. `get_db` only returns `request.state.db` (no `yield`, no cleanup). Services
never call `commit()`; they `flush()` when they need generated keys. Row locks (`with_for_update()`) protect
number ranges, stock balances, valuation rows, open items and document status transitions.
File downloads are built in memory and returned as `Response(content=..., media_type=...)`.

**Errors.** `core/errors.py`: `AppError(code, message, status=400, details=None)` and subclasses `NotFound` (404),
`Forbidden` (403), `Conflict` (409), `ValidationFailed` (422). JSON shape for every error:
`{"code": "PERIOD_CLOSED", "message": "<Turkish, user-readable>", "details": {...}}`. Pydantic validation errors
are converted to the same shape with `code = "VALIDATION_ERROR"` and `details.fields`. Integrity errors on delete
become 409 `IN_USE` ("Kayıt kullanımda olduğu için silinemez").

**Lists.** `GET /api/<resource>?page=1&page_size=50&sort=-created_at&q=<text>&<field>=<value>` →
`{"items": [...], "total": n, "page": 1, "page_size": 50}`. `core/pagination.py` provides `ListParams` and
`paginate(ctx, stmt, params, search=[cols], sort={name: col}, filters={name: col})`. `page_size` ≤ 500.
Select boxes use the same endpoints with `q`.

**Permissions.** Keys `<area>.<object>.<action>`: `mm.po.view|create|edit|approve|cancel`, `fi.journal.post`, ….
`require("mm.po.create")` is a route dependency. Superusers pass every check. Seeded roles: `admin`, `muhasebe`,
`satinalma`, `depo`, `yonetici` (approver), `izleyici` (read only).

**Documents.** Posted documents are never deleted or edited; they are cancelled by a reversal document.
Status transitions are explicit service functions that lock the row first. Drafts may be edited and deleted.
PostgreSQL triggers reject `DELETE` on journal and material-document tables and `UPDATE` of anything but a
white-listed set of bookkeeping columns.

**Audit.** Models with `__audit__ = True` get an `org_audit_log` row for each insert/update/delete (changed
columns with old/new values) from a `before_flush` listener; services add explicit entries for status changes
(`audit.log(ctx, action, entity, entity_id, summary)`).

**Numbering.** `core/numbering.py::next_number(ctx, key, *, year=None) -> str` locks the range row, lazily
creating it from `register_number_range(key, prefix, padding, yearly)` declarations made at import time by the
owning feature. Format `prefix + (YY if yearly) + zero-padded sequence`. Ranges are editable in the admin UI.
Defaults: `PR` → `TLP` + 7 digits, `RFQ` → `TKT`, `QUOTE` → `TEK`, `QCMP` → `MKY`, `PO` → `SIP`, `MATDOC` → `MB`
(yearly), `SINV` → `FK` (yearly), `PINV` (physical inventory) → `SYM`, `FIINV` → `FF` (yearly), `PAY` → `OD`
(yearly), `JE` → yearly, 8 digits, no prefix.

**Settings.** `org_company_setting(company_id, key, value JSONB)` via `core/settings.py::get_setting(ctx, key)`
with code-declared defaults (`register_setting(key, default, description)`).

## 5. Data model (Phase 1)

Notation: `name: type` · `→ table` foreign key · `?` nullable · `[C]` has `company_id` · `[V]` versioned ·
`[A]` audited. All tables have `id` and timestamps unless noted.

### auth
- `auth_user` [V][A]: username (unique), full_name, email?, password_hash, is_active, is_superuser,
  default_company_id?, must_change_password, last_login_at?
- `auth_role` [A]: code (unique), name, description?, is_system
- `auth_permission`: key (unique), description
- `auth_role_permission`: role_id, permission_id (unique pair)
- `auth_user_role` [A]: user_id, role_id, company_id? (null = all companies)

### org
- `org_company` [V][A]: code (unique), name, legal_name, tax_office?, tax_number?, address?, district?, city?,
  country (default `TR`), phone?, email?, website?, currency_code (default `TRY`), logo (bytea)?, logo_mime?,
  is_active
- `org_plant` [C][V][A]: code, name, address?, city?, is_active — the valuation area
- `org_warehouse` [C][V][A]: plant_id, code, name, is_active
- `org_purchasing_group` [C][A]: code, name, is_active
- `org_currency`: code (ISO, unique), name, symbol, is_active
- `org_exchange_rate` [A]: currency_code, rate_date, rate_type (`ALIS` default, `SATIS`), rate (local currency
  per 1 unit) — unique (currency_code, rate_date, rate_type). Lookup = latest row on or before the date; missing →
  `RATE_MISSING`. Rates are entered manually (closed system) or imported from a file.
- `org_uom` [A]: code (unique: `ADET`, `KG`, `LT`, `M`, `M2`, `M3`, `TON`, `PAKET`, `KOLI`, `SET`, `SAAT`…), name,
  decimals, unece_code? (for UBL later), is_active
- `org_number_range` [C]: key, year (0 when not yearly), prefix, padding, next_value — unique (company, key, year)
- `org_company_setting` [C]: key, value (JSONB) — unique (company, key)
- `org_audit_log` [C?]: at, user_id?, action, entity, entity_id?, summary?, changes (JSONB)? — append only
- `org_attachment` [C]: object_type, object_id, filename, mime, size, storage_path, uploaded_by_id — files live
  under `ERP_STORAGE_DIR`
- `org_approval_rule` [C][A]: object_type, level, min_amount (local currency, inclusive), approver_role_id?,
  approver_user_id?, is_active — a document of amount A needs every active level whose `min_amount <= A`,
  in level order
- `org_approval_request` [C]: object_type, object_id, amount, status (`PENDING`, `APPROVED`, `REJECTED`,
  `CANCELLED`), requested_by_id, requested_at, completed_at?, current_level?
- `org_approval_step`: request_id, level, approver_role_id?, approver_user_id?, status (`WAITING`, `PENDING`,
  `APPROVED`, `REJECTED`, `SKIPPED`), acted_by_id?, acted_at?, comment?

### co (minimal now; full in Phase 2)
- `co_cost_center` [C][V][A]: code, name, function (`URETIM`, `HIZMET`, `ARGE`, `PAZARLAMA`, `YONETIM`,
  `FINANSMAN` — maps to TDHP 730/740/750/760/770/780), valid_from?, valid_to?, is_active
- `co_internal_order` [C]: code, name, is_active (placeholder)
- `co_profit_center` [C]: code, name, is_active (placeholder)

### fi — `models/gl.py`
- `fi_gl_account` [C][V][A]: code (unique per company; dotted sub-accounts `320.01`), name, parent_id?, level,
  account_type (`ASSET`, `LIABILITY`, `EQUITY`, `REVENUE`, `EXPENSE`, `COST`, `OFFBALANCE`, `TECHNICAL`),
  normal_side (`D`/`C`), is_postable, recon_type (`NONE`, `VENDOR`, `CUSTOMER`), requires_cost_center,
  currency_code?, is_blocked, description?
- `fi_period` [C][A]: year, period (1–12), start_date, end_date, status (`OPEN`, `CLOSED`) — unique (company,
  year, period)
- `fi_tax_code` [C][V][A]: code, name, tax_type (`INPUT`, `OUTPUT`), rate (Pct), gl_account_id, is_active
- `fi_journal_entry` [C]: fiscal_year, period, number, doc_type (`GL`, `VI` vendor invoice, `VC` vendor credit,
  `VP` vendor payment, `CI` customer invoice, `CC` customer credit, `CP` customer payment, `MD` material
  document, `IV` MM invoice verification, `FX` exchange difference, `RF` reflection, `OP` opening, `CL` closing),
  posting_date, document_date, reference?, header_text?, currency_code, exchange_rate, status (`POSTED`,
  `REVERSED`), is_reversal, reversal_of_id?, reversed_by_id?, reversal_reason?, source_type?, source_id?,
  journal_no? (legal yevmiye sequence, assigned at period close), total_local — unique (company, fiscal_year, number)
- `fi_journal_line`: entry_id, line_no, company_id, posting_date (denormalised), gl_account_id, side (`D`/`C`),
  amount (document currency, ≥ 0), amount_local (> 0 unless amount > 0), vendor_id?, customer_id?,
  cost_center_id?, internal_order_id?, profit_center_id?, tax_code_id?, tax_base_local?, is_tax_line,
  due_date?, payment_term_id?, payment_block, material_id?, plant_id?, quantity?, uom_id?, assignment?, text?,
  is_open_item, open_amount, open_amount_local, cleared_at?
- `fi_clearing` [C]: clearing_date, note?, status (`ACTIVE`, `RESET`), fx_entry_id?
- `fi_clearing_item`: clearing_id, journal_line_id, amount, amount_local
- `fi_reflection_rule` [C]: expense_prefix (e.g. `770`), reflection_account_id (`771`), target_account_id (`632`)

### fi — `models/partners.py`
- `fi_payment_term` [C][A]: code, name, days
- `fi_vendor` [C][V][A]: code, name, tax_number?, tax_office?, is_person, address?, district?, city?, country,
  phone?, email?, contact_name?, iban?, bank_name?, currency_code, payment_term_id?, recon_account_id,
  is_blocked, purchasing_block, einvoice_registered, einvoice_alias?, notes?
- `fi_customer` [C][V][A]: same shape with `credit_limit?` instead of `purchasing_block`

### fi — `models/treasury.py`, `models/documents.py`
- `fi_treasury_account` [C][V][A]: kind (`BANK`, `CASH`), code, name, bank_name?, branch?, iban?, currency_code,
  gl_account_id, is_active
- `fi_invoice` [C]: kind (`VENDOR_INVOICE`, `VENDOR_CREDIT`, `CUSTOMER_INVOICE`, `CUSTOMER_CREDIT`), number,
  vendor_id?, customer_id?, reference (external invoice no), invoice_date, posting_date, due_date,
  payment_term_id?, currency_code, exchange_rate, net_total, tax_total, gross_total, text?, status (`POSTED`,
  `REVERSED`), journal_entry_id
- `fi_invoice_line`: invoice_id, line_no, gl_account_id, description?, cost_center_id?, net_amount,
  tax_code_id?, tax_amount
- `fi_payment` [C]: number, direction (`OUT`, `IN`), vendor_id?, customer_id?, treasury_account_id,
  payment_date, amount, currency_code, exchange_rate, method (`HAVALE`, `NAKIT`, `KREDI_KARTI`, `DIGER`),
  reference?, text?, status (`POSTED`, `REVERSED`), journal_entry_id, clearing_id?

### mm — `models/master.py`
- `mm_material_group` [C][A]: code, name
- `mm_valuation_class` [C][A]: code (`HAMMADDE`, `YARI_MAMUL`, `MAMUL`, `TICARI_MAL`, `DIGER_STOK`), name
- `mm_account_determination` [C][A]: key (`STOCK`, `GR_IR`, `PRICE_DIFF`, `CONSUMPTION`, `SCRAP`,
  `INVENTORY_GAIN`, `INVENTORY_LOSS`, `INITIAL_STOCK`, `RECEIPT_OTHER`), valuation_class_id?, modifier?
  (cost-center function for `CONSUMPTION`), gl_account_id — resolution: most specific match wins
- `mm_material` [C][V][A]: code, name, description?, material_type (`HAMMADDE`, `YARI_MAMUL`, `MAMUL`,
  `TICARI_MAL`, `SARF`, `HIZMET`), material_group_id?, base_uom_id, order_uom_id?, order_uom_factor (base units
  per order unit, default 1), valuation_class_id?, valuation_method (`MAP` moving average, `STD` standard),
  purchase_tax_code_id?, is_stock_managed, is_batch_managed, is_serial_managed (reserved), shelf_life_days?,
  barcode? (unique per company), lead_time_days?, is_blocked, notes?
- `mm_material_plant` [V]: material_id, plant_id, stock_qty, stock_value, moving_avg_price, standard_price,
  min_stock, reorder_point, reorder_qty, max_stock?, default_warehouse_id? — unique (material, plant); the
  valuation row, locked for every valued movement

### mm — `models/inventory.py`
- `mm_batch` [A]: material_id, batch_no, production_date?, expiry_date?, vendor_batch_no?, is_blocked —
  unique (material, batch_no)
- `mm_stock_balance`: material_id, plant_id, warehouse_id, batch_id?, stock_type (`UNRESTRICTED`, `QUALITY`,
  `BLOCKED`), quantity — unique (material, warehouse, batch, stock_type) with NULL-safe partial indexes;
  CHECK quantity ≥ 0
- `mm_material_document` [C]: number, year, posting_date, document_date, reference?, header_text?, status
  (`POSTED`, `REVERSED`), reversal_of_id?, reversed_by_id?, journal_entry_id?, source_type?, source_id?
- `mm_material_document_line`: document_id, line_no, movement_type, material_id, plant_id, warehouse_id,
  batch_id?, stock_type, quantity (base unit, > 0), direction (+1/−1), entry_quantity, entry_uom_id,
  amount_local, po_line_id?, cost_center_id?, internal_order_id?, gl_account_id?, dest_plant_id?,
  dest_warehouse_id?, dest_batch_id?, dest_stock_type?, text?, reversed_line_id?
- `mm_physical_inventory` [C][V]: number, plant_id, warehouse_id, count_date, status (`OPEN`, `COUNTED`, `POSTED`,
  `CANCELLED`), note?, material_document_id?
- `mm_physical_inventory_line`: inventory_id, line_no, material_id, batch_id?, stock_type, book_qty?,
  counted_qty?, is_counted

Movement types (static registry in code, Turkish names in the UI): `101` siparişe mal girişi · `102` mal girişi
iptali · `122` satıcıya iade · `201` masraf yerine çıkış · `202` masraf yerine çıkış iptali · `311` depolar arası
transfer · `301` işyerleri arası transfer · `321` kalite → kullanılabilir · `343` bloke → kullanılabilir · `344`
kullanılabilir → bloke · `501` siparişsiz giriş · `551` hurda çıkışı · `561` açılış stok girişi · `701` sayım
fazlası · `702` sayım eksiği.

### mm — `models/purchasing.py`
- `mm_info_record` [C][V][A]: vendor_id, material_id, vendor_material_code?, price, currency_code, uom_id,
  discount_pct, lead_time_days?, valid_from?, valid_to?, last_po_line_id?
- `mm_requisition` [C][V]: number, request_date, requester_id, plant_id?, cost_center_id?, project_name?,
  description?, status (`DRAFT`, `PENDING_APPROVAL`, `APPROVED`, `REJECTED`, `CLOSED`, `CANCELLED`)
- `mm_requisition_line`: requisition_id, line_no, material_id?, description, quantity, uom_id, required_date?,
  warehouse_id?, cost_center_id?, estimated_price?, currency_code?, budget_unit_price?, preferred_vendor_id?,
  ordered_qty, status (`OPEN`, `IN_RFQ`, `PARTIALLY_ORDERED`, `ORDERED`, `CLOSED`)
- `mm_rfq` [C][V]: number, rfq_date, deadline?, project_name?, subject?, requester_name?, requisition_id?,
  budget_name?, budget_currency?, buyer_id, status (`DRAFT`, `SENT`, `QUOTED`, `DECIDED`, `CLOSED`, `CANCELLED`)
- `mm_rfq_line`: rfq_id, line_no, requisition_line_id?, material_id?, description, quantity, uom_id,
  required_date?, budget_unit_price?
- `mm_rfq_vendor`: rfq_id, vendor_id, status (`INVITED`, `QUOTED`, `DECLINED`)
- `mm_quotation` [C][V]: rfq_id, vendor_id, number, vendor_ref?, quote_date, valid_until?, currency_code,
  discount_pct, vat_rate (default 20), contact_name?, contact_phone?, contact_email?, freight_text? (`DAHİL`,
  `HARİÇ`, free text), freight_amount?, delivery_place?, payment_text?, payment_days?, delivery_text?,
  delivery_days?, warranty_text?, technical_status (`NOT_EVALUATED`, `COMPLIANT`, `RESERVED`, `NON_COMPLIANT`),
  technical_note?, notes?, status (`ENTERED`, `SELECTED`, `PARTIALLY_SELECTED`, `NOT_SELECTED`)
- `mm_quotation_line`: quotation_id, rfq_line_id, offer_status (`OFFERED`, `NOT_OFFERED`, `INCLUDED`, `EXCLUDED`,
  `UNSPECIFIED`), unit_price?, discount_pct, delivery_days?, brand?, note?
- `mm_quotation_comparison` [C][V]: rfq_id, number, comparison_date, comparison_currency, rates (JSONB snapshot:
  currency → rate, plus source date), ranking (JSONB), notes?, status (`DRAFT`, `PENDING_APPROVAL`, `APPROVED`,
  `REJECTED`), prepared_by_id
- `mm_comparison_selection`: comparison_id, rfq_line_id, quotation_line_id, awarded_qty, is_cheapest,
  justification? (mandatory when not the cheapest compliant offer)
- `mm_comparison_mark`: comparison_id, quotation_id, rfq_line_id? (null = whole quotation), mark (`GREEN`,
  `YELLOW`)
- `mm_purchase_order` [C][V]: number, order_date, vendor_id, buyer_id, purchasing_group_id?, plant_id,
  currency_code, exchange_rate, payment_term_id?, payment_text?, delivery_terms?, delivery_address?, notes?
  (printed), internal_notes?, status (`DRAFT`, `PENDING_APPROVAL`, `APPROVED`, `REJECTED`, `PARTIALLY_RECEIVED`,
  `RECEIVED`, `CLOSED`, `CANCELLED`), revision, approved_at?, comparison_id?, rfq_id?, net_total,
  discount_total, tax_total, gross_total, net_total_local
- `mm_purchase_order_line`: order_id, line_no, requisition_line_id?, quotation_line_id?, material_id?,
  description, quantity, uom_id, base_qty_factor, unit_price, discount_pct, net_amount, tax_code_id?,
  tax_amount, delivery_date?, warehouse_id?, account_assignment (`STOCK`, `COST_CENTER`), cost_center_id?,
  gl_account_id?, received_qty, invoiced_qty, invoiced_amount, received_value_local, is_closed,
  over_delivery_pct
- `mm_purchase_order_revision`: order_id, revision, snapshot (JSONB of the full order as printed), pdf (bytea),
  reason?, created_by_id

### mm — `models/invoice.py`
- `mm_supplier_invoice` [C]: number, vendor_id, reference (vendor's invoice no), invoice_date, posting_date,
  due_date, payment_term_id?, currency_code, exchange_rate, net_total, tax_total, gross_total, status
  (`POSTED`, `BLOCKED`, `REVERSED`), block_reasons (JSONB), released_by_id?, released_at?, journal_entry_id,
  ettn? (reserved for e-Fatura) — unique (company, vendor, reference) among non-reversed
- `mm_supplier_invoice_line`: invoice_id, line_no, po_line_id?, quantity?, net_amount, tax_code_id?, tax_amount,
  gl_account_id? and cost_center_id? (unplanned cost lines such as freight), variance_local, text?

## 6. Core service contracts

### 6.1 Journal posting engine — `app/modules/fi/posting.py` (foundation)

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class LineIn:
    account: str | int | None = None   # GL code or id; None → derived from vendor/customer recon account
    debit: Decimal = Decimal(0)        # document currency; exactly one of debit/credit may be non-zero
    credit: Decimal = Decimal(0)
    local_debit: Decimal | None = None   # explicit local amounts (FX-exact postings, local-only FX lines)
    local_credit: Decimal | None = None
    vendor_id: int | None = None
    customer_id: int | None = None
    cost_center_id: int | None = None
    internal_order_id: int | None = None
    profit_center_id: int | None = None
    tax_code_id: int | None = None
    tax_base: Decimal | None = None
    is_tax_line: bool = False
    due_date: date | None = None
    payment_term_id: int | None = None
    payment_block: bool = False
    material_id: int | None = None
    plant_id: int | None = None
    quantity: Decimal | None = None
    uom_id: int | None = None
    assignment: str | None = None
    text: str | None = None

@dataclass(frozen=True, slots=True, kw_only=True)
class EntryIn:
    doc_type: FiDocType
    posting_date: date
    document_date: date | None = None
    currency_code: str | None = None     # default: company currency
    exchange_rate: Decimal | None = None # default: looked up for posting_date
    reference: str | None = None
    header_text: str | None = None
    source_type: str | None = None       # e.g. "MM_MATDOC", "MM_SINV", "FI_INVOICE", "FI_PAYMENT", "FI_CLEARING"
    source_id: int | None = None
    lines: Sequence[LineIn]

def post_entry(ctx: RequestContext, entry: EntryIn) -> JournalEntry: ...
def reverse_entry(ctx: RequestContext, entry_id: int, *, reason: str, posting_date: date | None = None,
                  from_source: bool = False) -> JournalEntry: ...
```

`post_entry` rules, each with its own error code:
1. Posting period of `posting_date` exists and is `OPEN` (`PERIOD_CLOSED`, `PERIOD_MISSING`).
2. At least two lines; every line has exactly one positive side, or is a local-only line (document amount 0,
   explicit local amount > 0).
3. Accounts exist in the company, are postable and not blocked (`ACCOUNT_NOT_POSTABLE`, `ACCOUNT_BLOCKED`).
4. Reconciliation accounts: a line on a `VENDOR`/`CUSTOMER` recon account requires the matching partner id; a
   partner id is only allowed on a matching recon account (`RECON_ACCOUNT_MISMATCH`). `account=None` with a
   partner resolves to the partner's recon account.
5. `requires_cost_center` accounts need an active cost center or internal order (`COST_OBJECT_REQUIRED`).
6. Local amount = `q_money(amount × rate)` unless given explicitly. Debits = credits in document currency and
   in local currency (`ENTRY_NOT_BALANCED`). When only implicit conversion rounding breaks the local balance
   (difference ≤ 0.01 × number of lines) the largest line absorbs it; with explicit local amounts no adjustment
   is made.
7. Partner lines become open items (`is_open_item`, `open_amount = amount`, `open_amount_local`); `due_date`
   defaults from the payment term, else the posting date.
8. `number = next_number(ctx, "JE", year=fiscal_year)`.

`reverse_entry` creates a mirror entry (`is_reversal`), links both, marks the original `REVERSED`. It refuses
entries that are already reversed (`ALREADY_REVERSED`) or have partially/fully cleared lines
(`HAS_CLEARED_ITEMS`). Entries with a `source_type` can only be reversed by their owning module
(`from_source=True`); the generic GL endpoint rejects them (`REVERSE_VIA_SOURCE`).

### 6.2 Approval engine — `core/approval.py` (foundation)

```python
def register_approval_handler(object_type: str, handler: Callable[[RequestContext, int, bool, ApprovalRequest], None]) -> None
def submit(ctx, object_type: str, object_id: int, amount_local: Decimal) -> ApprovalRequest   # no matching rule → APPROVED at once
def act(ctx, request_id: int, decision: Literal["approve", "reject"], comment: str | None) -> ApprovalRequest
def cancel(ctx, object_type: str, object_id: int) -> None
def history(ctx, object_type: str, object_id: int) -> list[ApprovalRequest]
def inbox(ctx) -> list[ApprovalRequest]     # requests whose current step the user may act on
```
The handler runs inside the same transaction when a request reaches `APPROVED` or `REJECTED` and moves the
document status. A user may act on a step when they are the named user or hold the step's role in the company.
The requester cannot approve their own document unless setting `approval.allow_self_approval` is true
(default false). Object types in Phase 1: `PR`, `QCMP`, `PO`. API (in `org`): `GET /api/approvals/inbox`,
`POST /api/approvals/{id}/approve|reject`, `GET /api/approvals/history?object_type=&object_id=`.

### 6.3 Inventory movement engine — `app/modules/mm/inventory/engine.py` (mm.inventory)

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class MoveIn:
    movement_type: str
    material_id: int
    plant_id: int
    warehouse_id: int
    quantity: Decimal                  # in uom_id (default: base unit)
    uom_id: int | None = None
    batch_id: int | None = None
    batch_no: str | None = None        # receipts may create the batch
    expiry_date: date | None = None
    stock_type: StockType = StockType.UNRESTRICTED
    po_line_id: int | None = None
    cost_center_id: int | None = None
    gl_account_id: int | None = None   # overrides the determined offset account
    dest_plant_id: int | None = None
    dest_warehouse_id: int | None = None
    dest_stock_type: StockType | None = None
    amount_local: Decimal | None = None  # externally given value (101 from PO, 501, 561)
    text: str | None = None

def post_material_document(ctx, *, posting_date: date, lines: Sequence[MoveIn], document_date: date | None = None,
                           reference: str | None = None, header_text: str | None = None,
                           source_type: str | None = None, source_id: int | None = None) -> MaterialDocument: ...
def reverse_material_document(ctx, document_id: int, *, reason: str, posting_date: date | None = None) -> MaterialDocument: ...
```
It locks the `mm_material_plant` row and the affected `mm_stock_balance` rows, refuses negative stock
(`INSUFFICIENT_STOCK`), updates quantity/value/moving average, and posts one journal entry (`doc_type=MD`,
`source_type="MM_MATDOC"`) per document through `post_entry` when any line is value-relevant.

### 6.4 PDF and Excel — `core/pdf.py`, `core/excel.py` (foundation)
`core/pdf.py` registers the bundled DejaVu fonts (full Turkish glyph coverage) and offers a small builder over
ReportLab platypus: company letterhead (logo, legal name, address, tax office/number), document title and
meta grid, line table with repeating header, totals box, free text, signature row, page footer `Sayfa x / y`,
diagonal watermark (`TASLAK`), portrait and landscape A4/A3. Returns `bytes`. `core/excel.py` wraps openpyxl
(styled header, number formats, auto width, `to_bytes`). Money in documents is formatted Turkish style
(`1.234,56`).

### 6.5 Foundation API contracts

Auth (`/api/auth`):
- `POST /api/auth/login` `{username, password}` → `{access_token, token_type: "bearer", user: Me}`; wrong
  credentials → 401 `INVALID_CREDENTIALS`; locked → 423 `ACCOUNT_LOCKED`.
- `GET /api/auth/me` (uses `X-Company-Id`) → `Me = {id, username, full_name, email, is_superuser,
  must_change_password, default_company_id, company_id (active), companies: [{id, code, name}],
  permissions: string[] (for the active company)}`. The frontend refetches it when the company is switched.
- `POST /api/auth/change-password` `{current_password, new_password}` → 204.
- Admin: `/api/users`, `/api/roles` (list contract + CRUD), `GET /api/permissions`.

Approvals (`/api/approvals`): every request is returned as
`{id, object_type, object_id, amount, status, requested_by: {id, full_name}, requested_at, completed_at,
current_level, can_act, document: {number, title, currency, path} | null,
steps: [{level, status, approver_role: {id, name} | null, approver_user: {id, full_name} | null,
acted_by: {id, full_name} | null, acted_at, comment}]}`. `document` comes from the optional
`describe(ctx, object_id)` callable passed to `register_approval_handler`; `path` is the frontend route of the
document.

Attachments (`/api/attachments`): `GET ?object_type=&object_id=` → list; `POST` multipart
(`object_type`, `object_id`, `file`; 20 MB limit, stored under `ERP_STORAGE_DIR` with a generated name);
`GET /{id}/download`; `DELETE /{id}`.

Downloads: PDF/Excel endpoints end in `/pdf` or `/xlsx` and set `Content-Disposition: attachment` with an
ASCII-safe filename.

## 7. Accounting rules (Tek Düzen Hesap Planı)

The full TDHP main-account list (classes 1–9) is seeded per company together with these postable sub-accounts
and defaults. All of them are data and can be changed by the accountant.

| Purpose | Seeded account |
|---|---|
| Cash / bank | `100.01` Merkez Kasa · `102.01` Banka (örnek) |
| Customers (recon) | `120.01` Yurtiçi Alıcılar · `120.02` Yurtdışı Alıcılar |
| Stock by valuation class | `150.01` hammadde · `151.01` yarı mamul · `152.01` mamul · `153.01` ticari mal · `157.01` diğer stoklar |
| Input VAT | `191.01` %1 · `191.10` %10 · `191.20` %20 |
| Count shortage / surplus | `197.01` Sayım ve Tesellüm Noksanları · `397.01` Sayım ve Tesellüm Fazlaları |
| Vendors (recon) | `320.01` Yurtiçi Satıcılar · `320.02` Yurtdışı Satıcılar |
| GR/IR clearing | `329.90` Mal Girişi / Fatura Ara Hesabı |
| Output VAT | `391.01` %1 · `391.10` %10 · `391.20` %20 |
| Sales | `600.01` Yurtiçi Satışlar |
| Purchase price differences | `621.90` Satınalma Fiyat Farkları |
| Realised FX gain / loss | `646.01` Kambiyo Kârları · `656.01` Kambiyo Zararları |
| Other receipt offset | `649.01` Diğer Olağan Gelir ve Kârlar |
| Scrap | `689.01` Diğer Olağandışı Gider ve Zararlar |
| Consumption by cost-center function | `730.01` · `740.01` · `750.01` · `760.01` · `770.01` · `780.01` (all `requires_cost_center`) |
| Direct material (for PP later) | `710.01` |
| Opening / migration clearing | `000.01` Açılış Devir Ara Hesabı (`TECHNICAL`; must be zero before a period is closed) |

Tax codes: `IND0`, `IND1`, `IND10`, `IND20` (input → 191.x) and `HES0`, `HES1`, `HES10`, `HES20` (output → 391.x).

| Event | Journal entry (local currency) |
|---|---|
| Goods receipt for PO, stock line, `MAP` | Dr `STOCK` qty × PO net price · Cr `GR_IR` same |
| Goods receipt for PO, stock line, `STD` | Dr `STOCK` qty × standard price · Dr/Cr `PRICE_DIFF` · Cr `GR_IR` qty × PO net price |
| Goods receipt for PO, cost-center line | Dr line expense account (cost center) · Cr `GR_IR` |
| Receipt reversal / return to vendor | mirror of the receipt at the receipt value; a `MAP` shortfall goes to `PRICE_DIFF` |
| Supplier invoice (MM) | Dr `GR_IR` at the value posted (or to be posted) at receipt · Dr/Cr variance (see below) · Dr input VAT · Cr vendor gross |
| Invoice variance (price or FX) | `MAP` stock line: to `STOCK` for the share still in stock, remainder to `PRICE_DIFF`; `STD` stock line: `PRICE_DIFF`; cost-center line: the line's expense account |
| FI vendor invoice | Dr expense lines · Dr input VAT · Cr vendor |
| Vendor payment | Dr vendor · Cr bank/cash; clearing posts realised FX difference to `646`/`656` |
| FI customer invoice | Dr customer · Cr revenue lines · Cr output VAT |
| Customer payment | Dr bank/cash · Cr customer |
| Issue to cost center (`201`) | Dr `CONSUMPTION` (by cost-center function, or the line's account) · Cr `STOCK` at current valuation price |
| Scrap (`551`) | Dr `SCRAP` · Cr `STOCK` |
| Receipt without PO (`501`) | Dr `STOCK` · Cr `RECEIPT_OTHER` at the entered value (default: current valuation price) |
| Initial stock (`561`) | Dr `STOCK` · Cr `INITIAL_STOCK` at the entered value |
| Count surplus / shortage (`701`/`702`) | Dr `STOCK` · Cr `INVENTORY_GAIN` (397) / Dr `INVENTORY_LOSS` (197) · Cr `STOCK` |
| Transfers, stock-type changes | no journal entry inside one company (valuation rows move at source price for `301`) |
| Period-end reflection | per `fi_reflection_rule`: Dr target (`632`…) · Cr reflection account (`771`…) for the period's 7xx movement |

Foreign currency: every document stores `currency_code` and `exchange_rate`; local amounts are fixed at
posting. The GR/IR account is always cleared at the local value posted at goods receipt, so price and FX
differences surface as invoice variance.

## 8. Feature scopes (Phase 1)

**auth / org / co (foundation).** Login (JWT access token, 12 h), change password, current user with
permissions and companies. Admin CRUD: users, roles and their permissions, companies (with logo upload), plants,
warehouses, purchasing groups, currencies, exchange rates (manual + CSV import), units, number ranges, company
settings, approval rules, cost centers. Approval inbox/history API. Audit log viewer. Attachments API
(`/api/attachments`). Health endpoint.

**fi.gl.** Chart of accounts tree (add sub-accounts, block, flags), manual journal entries (create, view,
reverse, copy), posting periods (open/close with checks; assign `journal_no` in date order on close), tax codes,
reflection rules and the period-end reflection run, year-end closing (income accounts → `690`, closing and
opening entries). Reports with Excel/PDF export: mizan (trial balance, by level), defter-i kebir (account
ledger), yevmiye (journal), bilanço and gelir tablosu in TDHP layout, VAT summary by tax code.

**fi.partners.** Vendors, customers, payment terms; duplicate tax-number warning; VKN/TCKN checksum validation.

**fi.ap_ar.** Treasury accounts (bank/cash). FI vendor/customer invoices and credit notes (multi-line, tax per
line), outgoing/incoming payments with open-item selection, partial payments, payments on account, manual
clearing and clearing reset, realised FX difference. Reports: open items, aging (0–30/31–60/61–90/90+), partner
statement (cari ekstre) with running balance, PDF/Excel. Payment-blocked items cannot be paid.

**mm.master.** Materials (with plant data, barcode lookup, block), material groups, valuation classes, account
determination table. Material list with stock and value columns.

**mm.inventory.** Movement engine (6.3) and screens for every movement type, material document list/detail/
reversal, batches (expiry), stock overview (by material, plant, warehouse, batch, stock type, with value), stock
on a past date, physical inventory (create count document, enter counts, post differences), reports: movement
list, reorder proposals (stock ≤ reorder point → create requisition), slow-moving/aging, turnover, expiring
batches. Excel export everywhere.

**mm.purchasing.** Info records; requisitions with approval; RFQs (from requisition lines or free), invited
vendors; quotation entry; **quotation comparison**; purchase orders (from comparison, requisition or free)
with tiered approval, revisions and PDF; goods receipt against PO (uses the movement engine; over-delivery
tolerance; closes lines; updates PO status); PO history (receipts, invoices); reports: open orders, vendor
performance (on-time delivery, price variance), purchase volume.

- *Comparison.* Shows all quotations of an RFQ side by side: per line unit price, amount; per vendor total,
  discount, discounted total, VAT, grand total, freight, delivery place, payment, delivery time, warranty,
  note; vendor contact. Vendors are ordered cheapest → most expensive by the discounted VAT-exclusive total
  converted to the comparison currency (company setting `mm.comparison_currency`, default `TRY`) with the
  `ALIS` rate of the comparison date; the rate snapshot is stored. Unquoted lines show `TEKLİF VERİLMEDİ`;
  `DAHİL`/`HARİÇ`/unspecified lines show the text and `-` as amount. Quotations past `valid_until` are flagged
  `SÜRESİ DOLMUŞ`. Marks: `GREEN` = best price among technically compliant offers (suggested automatically),
  `YELLOW` = cheaper but with reservations/incomplete scope; both can be set per line and per vendor. The buyer
  awards each line (splitting across vendors allowed); awarding anything but the cheapest compliant offer
  requires a justification. After approval, one click creates one PO per awarded vendor.
- *Comparison output.* Landscape PDF and Excel (live formulas, second sheet with rates and conversion table)
  in the classic "FİYAT MUKAYESE FORMU" layout: header (logo, title, project, subject, requester, sequence no,
  requisition no, date), item table (no, description, unit, quantity, budget, then unit price/amount per
  vendor), totals block, terms block, explanation box (rate line, ranking, legend, notes), signature boxes.
  Title, form code and signer titles come from company settings (`mm.comparison_form`).
- *PO output.* Portrait PDF on company letterhead: number, date, revision, vendor block, delivery and payment
  terms, lines, subtotal/discount/VAT per rate/grand total, notes, approvers with dates. Only approved orders
  print clean; everything else carries the `TASLAK` watermark. Each approved revision's PDF is stored. Changing
  an approved order creates a new revision and restarts approval.

**mm.invoice.** Supplier invoice entry against PO lines (propose open quantities), unplanned cost lines,
three-way match per line (PO price × invoiced quantity vs invoice amount; invoiced quantity vs received
quantity) with tolerances from settings (`mm.invoice.price_tolerance_pct`, `mm.invoice.qty_tolerance_pct`).
Out-of-tolerance invoices post with a payment block and reasons; an authorised user releases them. Duplicate
vendor reference check. Reversal. List of blocked invoices; GR/IR balance report by PO.

## 9. Frontend conventions

- Turkish UI, Ant Design components only (no extra UI kits, no Tailwind). Dense, table-centric screens.
- `lib/api.ts`: axios instance (`/api`, bearer token, `X-Company-Id`), error normalisation to `{code, message}`
  shown via `message.error`; 401 → logout. `lib/format.ts`: `fmtMoney`, `fmtQty`, `fmtDate` (`DD.MM.YYYY`),
  Turkish number parsing. `lib/permissions.ts`: `useCan("mm.po.create")`.
- Shared components (`src/components`): `PageHeader`, `ServerTable` (server-side paging/sorting/filtering bound
  to the list contract), `EntitySelect` (remote-search select for any list endpoint), `MoneyInput`, `QtyInput`,
  `DateInput`, `StatusTag`, `LinesEditor` (editable line grid with add/remove/keyboard navigation and computed
  columns), `ApprovalPanel` (history + approve/reject), `DownloadButton` (PDF/Excel blob download),
  `AttachmentList`, `ConfirmButton`, `BarcodeInput` (keyboard-wedge scanners).
- Data fetching through TanStack Query hooks colocated in `modules/<feature>/api.ts`. Forms use Ant Design
  `Form`; server validation errors map onto fields.
- Routes are lazy-loaded per feature. URL scheme `/<area>/<object>[/<id>]`, e.g. `/mm/siparis/123`.
- Gates: `npm run typecheck` (tsc `--noEmit`) and `npm run build` must pass.

## 10. Testing and local development

- PostgreSQL 16 on `127.0.0.1:5432`, role `erp` / password `erp` (CREATEDB), dev database `erp_dev`.
- `tests/conftest.py` creates a uniquely named database per test session (`erp_test_<random>`), builds the
  schema with `Base.metadata.create_all` plus the trigger DDL, seeds base data and one company (`1000`), and drops
  the database afterwards. Each test runs inside an outer transaction that is rolled back
  (`join_transaction_mode="create_savepoint"`). Fixtures: `db`, `ctx` (admin in company 1000), `client`
  (authenticated `TestClient`), `client_as(role)`; factories in `tests/factories.py`.
- Tests are integration-first: call the HTTP API or the service with real PostgreSQL. Every posting rule in
  section 7 has a test asserting the exact journal lines. Run with
  `cd erp/backend && uv run pytest` (feature work: `ERP_FEATURES=... uv run pytest tests/<feature>`).
- Lint: `uv run ruff check . && uv run ruff format --check .`
- Environment variables use the `ERP_` prefix (`ERP_DATABASE_URL`, `ERP_SECRET_KEY`, `ERP_STORAGE_DIR`,
  `ERP_ADMIN_PASSWORD`, `ERP_FEATURES`, `ERP_TEST_DATABASE_URL`).
- Seed CLI: `uv run python -m app.seed base|company|demo`.
