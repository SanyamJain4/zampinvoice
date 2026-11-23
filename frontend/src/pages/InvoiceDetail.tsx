import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Copy, RotateCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { DecisionBanner } from '@/components/DecisionBanner'
import { LineTable, PipelineTimeline } from '@/components/PipelineTimeline'
import { PdfViewer } from '@/components/PdfViewer'
import { ReviewPanel } from '@/components/ReviewPanel'
import { RuleList } from '@/components/RuleList'
import { DecisionBadge, PoStatusBadge, RuleBadge } from '@/components/StatusBadge'
import { Badge, Button, Card, CardBody, CardHeader, ErrorBox, Kv, PageLoading, Table, Td, Th } from '@/components/ui'
import { useRunStream } from '@/hooks/useRunStream'
import { api } from '@/services/api'
import type { AuditEvent, InvoiceDetail as Inv } from '@/types'
import { cn, dateOnly, fullDateTime, humanize, money, seconds } from '@/utils/format'

const TABS = [
  { id: 'checks', label: 'Decision & checks' },
  { id: 'po', label: 'PO & line matching' },
  { id: 'log', label: 'Processing log' },
  { id: 'json', label: 'Extracted JSON' },
  { id: 'audit', label: 'Audit trail' },
] as const

export default function InvoiceDetail() {
  const { id } = useParams()
  const qc = useQueryClient()
  const [tab, setTab] = useState<(typeof TABS)[number]['id']>('checks')
  const q = useQuery({
    queryKey: ['invoice', id],
    queryFn: () => api.invoice(id!),
    refetchInterval: (query) => (query.state.data?.processing_status === 'PROCESSING' ? 1200 : false),
  })
  const [retryRun, setRetryRun] = useState<string | null>(null)
  const retry = useRunStream(retryRun, () => ['invoice', 'invoices', 'metrics', 'trends', 'reviews', 'purchase-orders', 'runs'].forEach((k) => qc.invalidateQueries({ queryKey: [k] })))
  const activeRunId = q.data?.processing_status === 'PROCESSING' ? q.data.runs[q.data.runs.length - 1]?.run_id : null
  const live = useRunStream(activeRunId)

  if (q.isLoading) return <PageLoading />
  if (q.isError) return <ErrorBox error={q.error} onRetry={() => q.refetch()} />
  const inv = q.data!
  const ex = inv.extraction
  const processing = inv.processing_status === 'PROCESSING'
  const canRetry = inv.source === 'UPLOAD' && !processing && inv.final_decision !== 'APPROVED'

  return (
    <>
      <Link to="/invoices" className="mb-3 inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-navy-700"><ArrowLeft className="h-3.5 w-3.5" /> All invoices</Link>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex flex-wrap items-center gap-3 text-xl font-semibold tracking-tight text-slate-900">
            {inv.invoice_number ?? <span className="text-slate-500">Invoice (no number found)</span>}
            <DecisionBadge decision={inv.final_decision} processing={inv.processing_status} />
          </h1>
          <p className="mt-1 text-sm text-slate-500">{inv.vendor_name ?? 'Unknown vendor'} · {inv.filename} · uploaded {fullDateTime(inv.created_at)}{inv.duration_s ? ` · processed in ${seconds(inv.duration_s)}` : ''}</p>
        </div>
        {canRetry && (
          <Button variant="secondary" size="sm" onClick={async () => { const r = await api.process(inv.id, true); setRetryRun(r.run_id); q.refetch() }}><RotateCw className="h-4 w-4" /> {inv.final_decision === 'PROCESSING_ERROR' || !inv.final_decision ? 'Retry processing' : 'Re-run from scratch'}</Button>
        )}
      </div>

      {processing && live.run && (
        <Card className="mb-5"><CardHeader title="Processing in progress…" subtitle="This page updates automatically." /><CardBody><PipelineTimeline run={live.run} /></CardBody></Card>
      )}
      {retry.run && retry.run.status !== 'COMPLETED' && !processing && (
        <Card className="mb-5"><CardBody><PipelineTimeline run={retry.run} /></CardBody></Card>
      )}

      {inv.final_decision && inv.final_decision !== null && <div className="mb-5"><DecisionBanner decision={inv.decision} source={inv.decision_source} error={inv.final_decision === 'PROCESSING_ERROR' ? inv.decision_reason : null} /></div>}

      {inv.final_decision === 'NEEDS_REVIEW' && <div className="mb-5"><ReviewPanel inv={inv} /></div>}

      <div className="grid gap-5 xl:grid-cols-2">
        <Card className={cn("flex flex-col overflow-hidden xl:sticky xl:top-4 xl:self-start", inv.has_file ? "h-[640px]" : "h-auto")}>
          <CardHeader title="Original invoice" subtitle={`${inv.page_count ?? '?'} page(s) · SHA-256 ${inv.file_hash?.slice(0, 10) ?? '—'}…`} />
          <div className="min-h-0 flex-1">{inv.has_file ? <PdfViewer invoiceId={inv.id} pages={inv.page_count} /> : <p className="p-8 text-center text-sm text-slate-500">This is a seeded historical record with no PDF.</p>}</div>
        </Card>

        <div className="space-y-5">
          <Card>
            <CardHeader title="Extracted details" subtitle={inv.extraction_method ? `Extracted by ${inv.extraction_method === 'heuristic-parser' ? 'the offline rule-based parser' : inv.extraction_method}${inv.ocr_confidence ? ` · OCR confidence ${Math.round(inv.ocr_confidence * 100)}%` : ''}` : undefined} />
            <CardBody>
              {!ex ? <p className="text-sm text-slate-500">Nothing was extracted.</p> : (
                <>
                  <dl className="divide-y divide-slate-100">
                    <Field k="Vendor" v={ex.vendor_name} ev={ex.evidence.vendor_name} />
                    <Field k="Vendor tax ID" v={ex.vendor_tax_id} ev={ex.evidence.vendor_tax_id} mono />
                    <Field k="Invoice number" v={ex.invoice_number} ev={ex.evidence.invoice_number} missing />
                    <Field k="Invoice date" v={ex.invoice_date ? dateOnly(ex.invoice_date) : null} ev={ex.evidence.invoice_date} missing />
                    <Field k="Due date" v={ex.due_date ? dateOnly(ex.due_date) : null} ev={ex.evidence.due_date} />
                    <Field k="PO reference" v={ex.po_number} ev={ex.evidence.po_number} mono missing />
                    <Field k="Currency" v={ex.currency} ev={ex.evidence.currency} />
                    <Field k="Subtotal" v={ex.subtotal ? money(ex.subtotal, ex.currency) : null} ev={ex.evidence.subtotal} />
                    {ex.discount && <Field k="Discount" v={money(ex.discount, ex.currency)} />}
                    {ex.shipping && <Field k="Shipping" v={money(ex.shipping, ex.currency)} />}
                    <Field k="Tax" v={ex.tax_amount ? money(ex.tax_amount, ex.currency) : null} ev={ex.evidence.tax_amount} />
                    <Field k="Grand total" v={ex.grand_total ? money(ex.grand_total, ex.currency) : null} ev={ex.evidence.grand_total} bold missing />
                  </dl>
                  {inv.corrections.length > 0 && <p className="mt-3 rounded-lg bg-navy-50 px-3 py-2 text-xs text-navy-700">{inv.corrections.length} value(s) corrected by a reviewer: {[...new Set(inv.corrections.map((c) => humanize(c.field)))].join(', ')}.</p>}
                  {ex.warnings.length > 0 && <ul className="mt-3 space-y-1 rounded-lg bg-warn-50 px-3 py-2 text-xs text-warn-700">{ex.warnings.map((w, i) => <li key={i}>⚠ {w}</li>)}</ul>}
                </>
              )}
            </CardBody>
            {ex && (
              <div className="border-t border-slate-100">
                <p className="px-5 pt-3 text-xs font-semibold uppercase tracking-wide text-slate-400">Line items ({ex.line_items.length})</p>
                <Table>
                  <thead><tr><Th>Description</Th><Th className="text-right">Qty</Th><Th className="text-right">Unit price</Th><Th className="text-right">Tax</Th><Th className="text-right">Line total</Th></tr></thead>
                  <tbody>
                    {ex.line_items.map((l, i) => (
                      <tr key={i}><Td>{l.description}{l.sku && <span className="ml-1 font-mono text-[11px] text-slate-400">{l.sku}</span>}</Td><Td className="text-right tabular-nums">{l.quantity ?? '—'}</Td><Td className="text-right tabular-nums">{l.unit_price ? money(l.unit_price) : '—'}</Td><Td className="text-right tabular-nums">{l.tax_rate ? `${Number(l.tax_rate)}%` : '—'}</Td><Td className="text-right tabular-nums">{money(l.line_total)}</Td></tr>
                    ))}
                    {ex.line_items.length === 0 && <tr><Td colSpan={5} className="text-center text-slate-400">No line items extracted</Td></tr>}
                  </tbody>
                </Table>
              </div>
            )}
          </Card>

          <Card>
            <CardHeader title="Vendor & purchase order" />
            <CardBody>
              <dl>
                <Kv k="Vendor match" v={inv.vendor_match ? <span>{inv.vendor_match.vendor?.legal_name ?? humanize(inv.vendor_match.status)} <Badge tone={inv.vendor_match.status === 'VERIFIED_APPROVED' ? 'green' : inv.vendor_match.status === 'BLOCKED' ? 'red' : 'amber'}>{humanize(inv.vendor_match.status)}</Badge></span> : '—'} />
                <Kv k="Matched by" v={inv.vendor_match?.method ? humanize(inv.vendor_match.method) : '—'} />
                <Kv k="Purchase order" v={inv.po ? <Link className="text-navy-700 hover:underline" to="/purchase-orders">{inv.po.po_number}</Link> : (inv.po_number ?? '—')} />
                {inv.po && <>
                  <Kv k="PO vendor" v={inv.po.vendor_name} />
                  <Kv k="PO status" v={<PoStatusBadge status={inv.po.status} />} />
                  <Kv k="Authorized / invoiced / remaining" v={`${money(inv.po.authorized_total, inv.po.currency)} / ${money(inv.po.invoiced_amount, inv.po.currency)} / ${money(inv.po.remaining_balance, inv.po.currency)}`} />
                </>}
              </dl>
              {inv.vendor_match && inv.vendor_match.status !== 'VERIFIED_APPROVED' && <p className="mt-2 text-xs text-slate-500">{inv.vendor_match.message}</p>}
            </CardBody>
          </Card>
        </div>
      </div>

      <div className="mt-6">
        <div className="mb-4 flex gap-1 overflow-x-auto border-b border-slate-200" role="tablist">
          {TABS.map((t) => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)} className={cn('cursor-pointer whitespace-nowrap border-b-2 px-4 py-2.5 text-sm font-medium', tab === t.id ? 'border-navy-600 text-navy-700' : 'border-transparent text-slate-500 hover:text-slate-800')}>{t.label}</button>
          ))}
        </div>
        {tab === 'checks' && <ChecksTab inv={inv} />}
        {tab === 'po' && <PoTab inv={inv} />}
        {tab === 'log' && <LogTab inv={inv} />}
        {tab === 'json' && <JsonTab inv={inv} />}
        {tab === 'audit' && <AuditTab events={inv.audit} />}
      </div>
    </>
  )
}

function Field({ k, v, ev, mono, bold, missing }: { k: string; v: string | null | undefined; ev?: { page: number | null; snippet: string | null }; mono?: boolean; bold?: boolean; missing?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2 text-sm">
      <dt className="shrink-0 text-slate-500">{k}</dt>
      <dd className={cn('min-w-0 text-right', mono && 'font-mono text-xs', bold && 'text-base font-semibold')}>
        {v ? <span className="text-slate-900">{v}</span> : missing ? <Badge tone="amber">not found</Badge> : <span className="text-slate-400">—</span>}
        {ev?.snippet && <span className="ml-2 cursor-help rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500" title={ev.snippet}>p.{ev.page ?? '?'}</span>}
      </dd>
    </div>
  )
}

function ChecksTab({ inv }: { inv: Inv }) {
  const d = inv.decision
  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader title="Rule-by-rule results" subtitle="16 deterministic checks. No LLM is involved in any rule or amount." action={d.rules_summary && <div className="flex gap-1.5 text-xs"><Badge tone="green">{d.rules_summary.PASS} pass</Badge>{d.rules_summary.FAIL > 0 && <Badge tone="red">{d.rules_summary.FAIL} fail</Badge>}{d.rules_summary.REVIEW > 0 && <Badge tone="amber">{d.rules_summary.REVIEW} review</Badge>}<Badge>{d.rules_summary.NOT_APPLICABLE} n/a</Badge></div>} />
        {inv.validations.length ? <RuleList rules={inv.validations} /> : <p className="p-6 text-sm text-slate-500">No checks have run yet.</p>}
      </Card>
      <div className="space-y-5">
        <Card>
          <CardHeader title="Why this decision" />
          <CardBody className="space-y-3 text-sm">
            <p className="text-slate-800">{d.main_reason ?? inv.decision_reason ?? '—'}</p>
            {d.detailed_reasons && d.detailed_reasons.length > 1 && d.status !== 'APPROVED' && (
              <ul className="list-disc space-y-1 pl-5 text-xs text-slate-600">{d.detailed_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
            )}
            {d.manual && <p className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600"><b>Manual {d.manual.action.toLowerCase()}</b> by {d.manual.by}: “{d.manual.justification}”{d.manual.overridden_rules?.length ? ` (overrode ${d.manual.overridden_rules.join(', ')})` : ''}</p>}
            <Kv k="Needs a human?" v={d.requires_manual_intervention ? 'Yes' : 'No'} />
            <Kv k="Severity" v={d.severity ? humanize(d.severity) : '—'} />
          </CardBody>
        </Card>
        {d.evidence && d.evidence.length > 0 && (
          <Card>
            <CardHeader title="Evidence from the document" subtitle="Where each value was found" />
            <ul className="divide-y divide-slate-100 text-xs">
              {d.evidence.map((e) => <li key={e.field} className="px-5 py-2"><span className="font-medium text-slate-700">{humanize(e.field)}</span> <span className="text-slate-400">page {e.page ?? '?'}</span><p className="mt-0.5 font-mono text-[11px] text-slate-500">{e.snippet}</p></li>)}
            </ul>
          </Card>
        )}
      </div>
    </div>
  )
}

function PoTab({ inv }: { inv: Inv }) {
  const lm = inv.line_matching
  return (
    <div className="space-y-5">
      <Card>
        <CardHeader title="Line-item matching" subtitle="Each invoice line is mapped to a PO line (SKU, description, quantity, unit price)." />
        <CardBody>
          {lm && lm.lines.length ? (
            <>
              <LineTable lines={lm.lines} />
              {lm.expected_total && <p className="mt-3 text-xs text-slate-600">Expected total at PO prices (qty × PO price + PO tax): <b>{money(lm.expected_total, inv.currency)}</b> · invoice total <b>{money(inv.total_amount, inv.currency)}</b></p>}
            </>
          ) : <p className="text-sm text-slate-500">No line matching was performed.</p>}
        </CardBody>
      </Card>
      {inv.po && (
        <Card>
          <CardHeader title={`Purchase order ${inv.po.po_number}`} subtitle={`${inv.po.vendor_name} · issued ${dateOnly(inv.po.issue_date)}`} action={<PoStatusBadge status={inv.po.status} />} />
          <Table>
            <thead><tr><Th>#</Th><Th>Item</Th><Th>SKU</Th><Th className="text-right">Qty</Th><Th className="text-right">Unit price</Th><Th className="text-right">Tax</Th><Th className="text-right">Authorized</Th></tr></thead>
            <tbody>{inv.po.lines.map((l) => <tr key={l.id}><Td>{l.line_no}</Td><Td>{l.item_description}</Td><Td className="font-mono text-xs">{l.sku}</Td><Td className="text-right tabular-nums">{l.quantity}</Td><Td className="text-right tabular-nums">{money(l.unit_price)}</Td><Td className="text-right tabular-nums">{Number(l.tax_rate)}%</Td><Td className="text-right tabular-nums">{money(l.authorized_amount)}</Td></tr>)}</tbody>
          </Table>
          <div className="grid gap-3 border-t border-slate-100 p-5 text-sm sm:grid-cols-3">
            <div><p className="text-xs text-slate-500">Authorized</p><p className="font-semibold">{money(inv.po.authorized_total, inv.po.currency)}</p></div>
            <div><p className="text-xs text-slate-500">Approved so far</p><p className="font-semibold">{money(inv.po.invoiced_amount, inv.po.currency)}</p></div>
            <div><p className="text-xs text-slate-500">Remaining</p><p className="font-semibold">{money(inv.po.remaining_balance, inv.po.currency)}</p></div>
          </div>
        </Card>
      )}
      <Card>
        <CardHeader title="Duplicate detection" />
        <CardBody className="text-sm">
          <p className="flex items-center gap-2">{inv.duplicate ? <RuleBadge status={inv.duplicate.status === 'NONE' ? 'PASS' : inv.duplicate.status === 'CONFIRMED' ? 'FAIL' : 'REVIEW'} /> : null}<span className="text-slate-700">{inv.duplicate?.message ?? 'Not evaluated.'}</span></p>
          {inv.duplicate?.matches.map((m) => (
            <p key={m.invoice_id} className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">Earlier invoice <Link className="font-medium text-navy-700 hover:underline" to={`/invoices/${m.invoice_id}`}>#{m.invoice_id} {m.invoice_number}</Link> ({m.decision}): {m.reason}</p>
          ))}
        </CardBody>
      </Card>
    </div>
  )
}

function LogTab({ inv }: { inv: Inv }) {
  const [sel, setSel] = useState(inv.runs.length - 1)
  useEffect(() => setSel(inv.runs.length - 1), [inv.runs.length])
  const stub = inv.runs[sel]
  const full = useQuery({ queryKey: ['run', stub?.run_id], queryFn: () => api.run(stub.run_id), enabled: !!stub })
  if (!inv.runs.length) return <p className="text-sm text-slate-500">This invoice has not been processed.</p>
  return (
    <Card>
      <CardHeader title="Processing log" subtitle="Per-stage timestamps, durations, warnings and the data each stage produced." action={inv.runs.length > 1 && (
        <select className="rounded-lg border border-slate-200 px-2 py-1 text-xs" value={sel} onChange={(e) => setSel(Number(e.target.value))} aria-label="Select run">
          {inv.runs.map((r, i) => <option key={r.run_id} value={i}>Run {i + 1} · {r.kind.toLowerCase()} · {fullDateTime(r.started_at)}</option>)}
        </select>
      )} />
      <CardBody>
        <div className="mb-4 flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-500">
          <span>Run <span className="font-mono">{stub.run_id.slice(0, 8)}</span></span><span>Started {fullDateTime(stub.started_at)}</span><span>Finished {fullDateTime(stub.completed_at)}</span><span>Duration {seconds(stub.duration_s)}</span>
        </div>
        {full.data ? <PipelineTimeline run={full.data} /> : <PageLoading />}
      </CardBody>
    </Card>
  )
}

function JsonTab({ inv }: { inv: Inv }) {
  const [showText, setShowText] = useState(false)
  const body = showText ? inv.extracted_text ?? '' : JSON.stringify(inv.extraction, null, 2)
  return (
    <Card>
      <CardHeader title={showText ? 'Raw document text' : 'Extracted JSON'} subtitle={showText ? 'What the PDF reader / OCR produced (this is the only input the extractor sees).' : 'Validated against the Pydantic schema.'}
        action={<div className="flex gap-2"><Button variant="secondary" size="sm" onClick={() => setShowText(!showText)}>{showText ? 'Show JSON' : 'Show raw text'}</Button><Button variant="ghost" size="sm" onClick={() => navigator.clipboard?.writeText(body)}><Copy className="h-4 w-4" /> Copy</Button></div>} />
      <pre className="max-h-[560px] overflow-auto bg-slate-900 p-5 text-xs leading-relaxed text-slate-100" data-testid="json-view">{body || 'Nothing extracted.'}</pre>
    </Card>
  )
}

export function AuditList({ events, showInvoice }: { events: AuditEvent[]; showInvoice?: boolean }) {
  return (
    <ol className="relative ml-2 space-y-4 border-l border-slate-200 pl-6">
      {events.map((e) => (
        <li key={e.id} className="relative">
          <span className="absolute -left-[31px] top-1.5 h-2.5 w-2.5 rounded-full bg-navy-600 ring-4 ring-white" />
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Badge tone={e.event_type.includes('MANUAL') || e.event_type.includes('CORRECTED') || e.event_type.includes('CLARIF') ? 'amber' : e.event_type.includes('FAILED') ? 'red' : 'indigo'}>{humanize(e.event_type)}</Badge>
            {showInvoice && e.invoice_id && <Link className="text-xs font-medium text-navy-700 hover:underline" to={`/invoices/${e.invoice_id}`}>#{e.invoice_id} {e.invoice_number}</Link>}
            <span className="text-xs text-slate-400">{fullDateTime(e.timestamp)} · {e.actor}</span>
          </div>
          {e.reason && <p className="mt-1 text-sm text-slate-700">{e.reason}</p>}
          {(e.previous_value != null || e.new_value != null) && (
            <div className="mt-1.5 grid gap-2 text-[11px] sm:grid-cols-2">
              {e.previous_value != null && <pre className="overflow-auto rounded bg-bad-50 p-2 text-bad-700">{fmt(e.previous_value)}</pre>}
              {e.new_value != null && <pre className="max-h-40 overflow-auto rounded bg-ok-50 p-2 text-ok-700">{fmt(e.new_value)}</pre>}
            </div>
          )}
        </li>
      ))}
    </ol>
  )
}
const fmt = (v: unknown) => (typeof v === 'string' ? v : JSON.stringify(v, null, 1))

function AuditTab({ events }: { events: AuditEvent[] }) {
  return <Card><CardHeader title="Audit trail" subtitle="Every action on this invoice: who, when, what changed, and why." /><CardBody>{events.length ? <AuditList events={events} /> : <p className="text-sm text-slate-500">No events.</p>}</CardBody></Card>
}
