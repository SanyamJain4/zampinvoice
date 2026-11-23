# Architecture

## Components
| Module | Responsibility |
|---|---|
| `services/pdf_processor.py` | File validation (signature, corruption, encryption, limits, SHA-256); per-page native text via PyMuPDF **spans grouped by baseline** (so side-by-side blocks don't interleave); OCR fallback per page; page rendering for the UI |
| `services/ocr_service.py` | RapidOCR (ONNX) wrapper, thread-safe, returns boxes + confidence |
| `services/ai_extractor.py` | Provider selection, strict-schema calls (Anthropic tool use / OpenAI JSON / Gemini JSON), bounded retries, never fabricates |
| `services/heuristic_extractor.py` | Offline parser used when no key is configured (labelled in UI/runs) |
| `schemas/extraction.py` | Pydantic models + lenient-in/strict-out normalisation (`Decimal`, ISO dates, currency) |
| `services/vendor_matcher.py` | Tax ID → name → alias → normalised → fuzzy *suggestion*; conflict detection |
| `services/po_matcher.py` | PO lookup, balance derivation, line matching (SKU/description/qty/price), bundle detection |
| `services/duplicate_detector.py` | File hash, vendor + number, suspicious look-alikes |
| `services/validation_engine.py` | Rules R01–R16 → structured `RuleResult` |
| `services/decision_engine.py` | Rules → `APPROVED / NEEDS_REVIEW / REJECTED` + reasons + next action; defines non-bypassable controls |
| `services/workflow_service.py` | Run/stage orchestration, persistence, the **locked decision section**, corrections and manual review |
| `api/*` | REST + SSE; explicit serializers (money as strings) |

## Run model
`POST /api/invoices/upload` stores the file (random name, signature + size check). `POST /api/invoices/{id}/process` creates a `ProcessingRun` with 9 `StageEvent`
rows (`QUEUED`) and submits it to a 4-worker pool. Each stage sets `RUNNING`, does real work, then `COMPLETED / WARNING / FAILED` with timestamps, duration,
warnings and a JSON payload — **every transition is committed immediately**.
`GET /api/runs/{id}/events` (SSE) streams a full snapshot whenever the persisted state changes; the UI falls back to polling `GET /api/runs/{id}`.
After a restart, runs still `QUEUED/RUNNING` are marked failed ("interrupted") so nothing looks stuck.

## Concurrency model (why two invoices can't overdraw a PO)
Stages 4–8 are for display and early feedback. **Stage 9 recomputes vendor, PO, duplicates, line matching and the PO balance and runs all 16 rules inside one critical section**:
1. in-process `RLock` (serialises workers of one process);
2. `BEGIN IMMEDIATE` (SQLite) takes the database write lock for the whole read-decide-write transaction, so other *processes* serialise too; on PostgreSQL a `SELECT … FOR UPDATE` on the PO row does the same.
The decision, validations, audit event and PO reconciliation are one transaction. The same section protects manual approvals.
If anything changed between a stage and the final evaluation, the stage shows "re-evaluated under lock; outcome changed for Rxx".

## Data model
```
vendors 1─* purchase_orders 1─* po_lines
vendors 1─* invoices *─1 purchase_orders          invoices 1─* invoice_lines ─(matched_po_line_id)→ po_lines
invoices 1─* processing_runs 1─* stage_events      invoices 1─* validation_results      invoices 1─* audit_events
```
* Money is `Decimal` end to end (`Money` type stores exact text; the API returns strings).
* `purchase_orders.remaining_balance` is a cache; truth = `authorized_total − Σ approved invoices` (`po_matcher.po_balance`). `reconcile_po` refreshes cache + status (OPEN / PARTIALLY_INVOICED / FULLY_INVOICED; CLOSED is administrative).
* `invoices.extraction_data` keeps the validated extraction; `corrections` keeps every reviewer change (field, original, corrected, who, when, why).

## API
```
POST /api/invoices/upload            POST /api/invoices/{id}/process      GET /api/invoices  GET /api/invoices/{id}
GET  /api/invoices/{id}/file|pages/{n}.png                                 PATCH /api/invoices/{id}/extraction
POST /api/invoices/{id}/review       GET /api/reviews                      GET /api/runs  /api/runs/{id}  /api/runs/{id}/events
GET  /api/vendors[/{id}]             GET /api/purchase-orders[/{id}]       GET /api/dashboard/metrics|trends
GET  /api/audit                      GET /api/health  /api/settings        GET /api/samples  POST /api/samples/{file}/load  POST /api/admin/reset
```
Errors are `{ "error": true, "message": "...", ... }` — human-readable, no stack traces or secrets; validation errors list offending fields.

## Frontend
Routes: Overview · Process Invoice (drag-drop, batch, PDF preview, live timeline) · All Invoices · Invoice detail (PDF with page/zoom ↔ extracted data; decision, rule-by-rule, PO & line matching, processing log, JSON, audit; review panel) ·
Review Queue · Purchase Orders (drawer) · Vendors (drawer) · Processing History · Audit Trail · Settings.
Data via TanStack Query (auto-refetch); live runs via `useRunStream` (SSE → polling fallback). Every number on every page comes from the API.
