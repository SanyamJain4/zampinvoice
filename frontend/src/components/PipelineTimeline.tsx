import { useState } from 'react'
import { ChevronDown, ChevronRight, Code2 } from 'lucide-react'
import { StageIcon } from '@/components/StatusBadge'
import { RuleList } from '@/components/RuleList'
import { Badge } from '@/components/ui'
import { cn, duration, fullDateTime, money } from '@/utils/format'
import type { Extraction, LineMatch, Rule, Run, Stage } from '@/types'

const STAGE_BLURB: Record<string, string> = {
  pdf_validation: 'Checks the file is a real, unencrypted PDF within limits and fingerprints it (SHA-256).',
  text_extraction: 'Reads the native text layer; pages with no text are OCR’d.',
  ai_extraction: 'Extracts structured fields from the document text (validated, never invented).',
  invoice_validation: 'Deterministic checks on the document itself: required fields, arithmetic, reliability.',
  vendor_verification: 'Matches the vendor against the approved vendor master.',
  po_matching: 'Finds the purchase order and checks vendor, currency and status.',
  duplicate_detection: 'Looks for the same file, the same vendor + number, or look-alike invoices.',
  financial_reconciliation: 'Maps invoice lines to PO lines; checks amounts, tolerance, tax, dates and remaining PO balance.',
  decision: 'Re-evaluates every control under the PO lock, then persists the decision and allocates balance.',
}

function statusLabel(s: Stage): string {
  return { QUEUED: 'Queued', RUNNING: 'Running…', COMPLETED: 'Completed', WARNING: 'Completed with warnings', FAILED: 'Failed', SKIPPED: 'Skipped' }[s.status]
}

export function PipelineTimeline({ run, defaultOpenKey }: { run: Run; defaultOpenKey?: string }) {
  const done = run.stages.filter((s) => s.status === 'COMPLETED' || s.status === 'WARNING' || s.status === 'SKIPPED').length
  const pct = Math.round((done / Math.max(run.stages.length, 1)) * 100)
  return (
    <div data-testid="pipeline-timeline">
      <div className="mb-4 flex items-center gap-3">
        <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
          <div className={cn('h-full rounded-full transition-all duration-500', run.status === 'FAILED' ? 'bg-bad-600' : 'bg-navy-600')} style={{ width: `${pct}%` }} />
        </div>
        <span className="w-10 text-right text-xs font-medium tabular-nums text-slate-500">{pct}%</span>
      </div>
      <ol className="relative space-y-1">
        {run.stages.map((s, i) => (
          <StageRow key={s.key} stage={s} index={i + 1} last={i === run.stages.length - 1} defaultOpen={s.key === defaultOpenKey} />
        ))}
      </ol>
      {run.status === 'FAILED' && run.error_message && (
        <p className="mt-3 rounded-lg border border-bad-100 bg-bad-50 px-3 py-2 text-sm text-bad-700" role="alert">{run.error_message}</p>
      )}
    </div>
  )
}

function StageRow({ stage, index, last, defaultOpen }: { stage: Stage; index: number; last: boolean; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const [raw, setRaw] = useState(false)
  const running = stage.status === 'RUNNING'
  const hasBody = stage.status !== 'QUEUED' && (stage.data || stage.warnings.length > 0 || stage.error)
  return (
    <li className="relative pl-10" data-testid={`stage-${stage.key}`} data-status={stage.status}>
      {!last && <span className="absolute left-[15px] top-8 h-[calc(100%-1.25rem)] w-px bg-slate-200" />}
      <span className={cn('absolute left-1 top-1.5 flex h-7 w-7 items-center justify-center rounded-full bg-white', running && 'pulse-ring')}>
        <StageIcon status={stage.status} />
      </span>
      <button
        type="button"
        disabled={!hasBody}
        onClick={() => setOpen(!open)}
        className={cn('flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left', hasBody ? 'cursor-pointer hover:bg-slate-50' : 'cursor-default', running && 'bg-navy-50/60')}
        aria-expanded={open}
      >
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-900">
            <span className="text-xs text-slate-400">Stage {index}</span> {stage.name}
            {stage.status === 'WARNING' && <Badge tone="amber">{stage.warnings.length} warning{stage.warnings.length > 1 ? 's' : ''}</Badge>}
          </p>
          <p className="truncate text-xs text-slate-500">{running ? STAGE_BLURB[stage.key] : stage.status === 'QUEUED' ? 'Waiting…' : stage.status === 'SKIPPED' ? (stage.data?.note ?? 'Skipped') : STAGE_BLURB[stage.key]}</p>
        </div>
        <div className="shrink-0 text-right">
          <p className={cn('text-xs font-medium', stage.status === 'FAILED' ? 'text-bad-600' : stage.status === 'WARNING' ? 'text-warn-700' : stage.status === 'COMPLETED' ? 'text-ok-700' : 'text-slate-500')}>{statusLabel(stage)}</p>
          <p className="text-[11px] tabular-nums text-slate-400">{stage.duration_ms !== null ? duration(stage.duration_ms) : stage.started_at ? 'in progress' : ''}</p>
        </div>
        {hasBody && (open ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />)}
      </button>
      {open && hasBody && (
        <div className="slide-in mb-2 ml-3 space-y-3 rounded-lg border border-slate-200 bg-slate-50/60 p-4 text-sm">
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-[11px] text-slate-500">
            <span>Started {fullDateTime(stage.started_at)}</span>
            <span>Finished {fullDateTime(stage.completed_at)}</span>
          </div>
          {stage.error && <p className="rounded-md bg-bad-50 px-3 py-2 text-bad-700">{stage.error}</p>}
          {stage.warnings.length > 0 && (
            <ul className="space-y-1 rounded-md bg-warn-50 px-3 py-2 text-xs text-warn-700">
              {stage.warnings.map((w, i) => <li key={i}>⚠ {w}</li>)}
            </ul>
          )}
          {!raw && stage.data && <StageData stage={stage} />}
          {raw && <pre className="max-h-72 overflow-auto rounded-md bg-slate-900 p-3 text-[11px] leading-relaxed text-slate-100">{JSON.stringify(stage.data, null, 2)}</pre>}
          {stage.data && (
            <button type="button" onClick={() => setRaw(!raw)} className="inline-flex cursor-pointer items-center gap-1 text-[11px] font-medium text-navy-700 hover:underline">
              <Code2 className="h-3 w-3" /> {raw ? 'Show summary' : 'Show raw stage data'}
            </button>
          )}
        </div>
      )}
    </li>
  )
}

function Fact({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2">
      <p className="text-[10px] font-medium uppercase tracking-wide text-slate-400">{k}</p>
      <p className="mt-0.5 break-words text-sm font-medium text-slate-900">{v ?? '—'}</p>
    </div>
  )
}

function StageData({ stage }: { stage: Stage }) {
  const d = stage.data
  if (!d) return null
  switch (stage.key) {
    case 'pdf_validation':
      return <div className="grid grid-cols-2 gap-2 sm:grid-cols-4"><Fact k="Pages" v={d.pages} /><Fact k="Size" v={`${d.size_kb} KB`} /><Fact k="Encrypted" v={d.encrypted ? 'Yes' : 'No'} /><Fact k="SHA-256" v={<span className="font-mono text-xs">{String(d.sha256).slice(0, 12)}…</span>} /></div>
    case 'text_extraction':
      return (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Fact k="Method" v={d.method === 'TEXT' ? 'Native text layer' : d.method === 'OCR' ? 'OCR (scanned)' : 'Mixed'} />
            <Fact k="Pages" v={d.pages?.length} /><Fact k="Characters" v={d.total_chars} />
            <Fact k="OCR confidence" v={d.ocr_confidence ? `${Math.round(d.ocr_confidence * 100)}%` : 'n/a'} />
          </div>
          <pre className="max-h-40 overflow-auto rounded-md bg-white p-3 text-[11px] leading-relaxed text-slate-700 ring-1 ring-slate-200">{d.preview}</pre>
        </div>
      )
    case 'ai_extraction': {
      const e: Extraction = d.extracted
      return (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Fact k="Engine" v={d.provider === 'heuristic' ? 'Rule-based parser (offline)' : `${d.provider}`} /><Fact k="Model" v={d.model} />
            <Fact k="Attempts" v={d.attempts} /><Fact k="Missing fields" v={d.missing_fields?.length ? d.missing_fields.join(', ') : 'None'} />
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Fact k="Vendor" v={e.vendor_name} /><Fact k="Invoice #" v={e.invoice_number} /><Fact k="Date" v={e.invoice_date} /><Fact k="PO" v={e.po_number} />
            <Fact k="Currency" v={e.currency} /><Fact k="Subtotal" v={money(e.subtotal)} /><Fact k="Tax" v={money(e.tax_amount)} /><Fact k="Grand total" v={money(e.grand_total)} />
          </div>
          <p className="text-xs text-slate-500">{e.line_items.length} line item(s) extracted.</p>
        </div>
      )
    }
    case 'vendor_verification':
      return (
        <div className="space-y-2">
          <p className="text-slate-700">{d.vendor?.message}</p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3"><Fact k="Result" v={String(d.vendor?.status).replace(/_/g, ' ')} /><Fact k="Matched by" v={d.vendor?.method} /><Fact k="Vendor" v={d.vendor?.vendor?.legal_name} /></div>
          <Rules rules={d.rules} />
        </div>
      )
    case 'po_matching':
      return (
        <div className="space-y-2">
          <p className="text-slate-700">{d.po?.message}</p>
          {d.balance && (
            <div className="grid grid-cols-3 gap-2"><Fact k="Authorized" v={money(d.balance.authorized_total, d.po?.po?.currency)} /><Fact k="Already approved" v={money(d.balance.approved_total, d.po?.po?.currency)} /><Fact k="Remaining" v={money(d.balance.remaining_before, d.po?.po?.currency)} /></div>
          )}
          <Rules rules={d.rules} />
        </div>
      )
    case 'duplicate_detection':
      return (
        <div className="space-y-2">
          <p className="text-slate-700">{d.duplicate?.message}</p>
          <Rules rules={d.rules} />
        </div>
      )
    case 'financial_reconciliation':
      return (
        <div className="space-y-2">
          <LineTable lines={d.line_matching?.lines ?? []} />
          <Rules rules={d.rules} />
        </div>
      )
    case 'decision':
      return (
        <div className="space-y-2">
          <p className="text-slate-800">{d.decision?.main_reason}</p>
          <Rules rules={d.rules} />
        </div>
      )
    default:
      return <Rules rules={d.rules} />
  }
}

function Rules({ rules }: { rules?: Rule[] }) {
  if (!rules?.length) return null
  return <div className="overflow-hidden rounded-md border border-slate-200 bg-white"><RuleList rules={rules} compact /></div>
}

export function LineTable({ lines }: { lines: LineMatch[] }) {
  if (!lines.length) return <p className="text-xs text-slate-500">No line items to match.</p>
  const tone = (s: string) => (s === 'MATCHED' ? 'green' : s === 'PRICE_MISMATCH' || s === 'QTY_EXCEEDED' ? 'red' : 'amber')
  return (
    <div className="overflow-x-auto rounded-md border border-slate-200 bg-white">
      <table className="w-full text-xs">
        <thead className="bg-slate-50 text-left text-slate-500"><tr><th className="px-3 py-2">#</th><th className="px-3 py-2">Invoice line</th><th className="px-3 py-2">PO line</th><th className="px-3 py-2 text-right">Qty</th><th className="px-3 py-2 text-right">Unit price</th><th className="px-3 py-2 text-right">PO price</th><th className="px-3 py-2">Result</th></tr></thead>
        <tbody>
          {lines.map((l) => (
            <tr key={l.index} className="border-t border-slate-100 align-top">
              <td className="px-3 py-2 text-slate-400">{l.index}</td>
              <td className="px-3 py-2 text-slate-800">{l.description}</td>
              <td className="px-3 py-2 text-slate-600">{l.po_description ?? '—'}</td>
              <td className="px-3 py-2 text-right tabular-nums">{l.invoice_qty ?? '—'}</td>
              <td className="px-3 py-2 text-right tabular-nums">{l.invoice_unit_price ? money(l.invoice_unit_price) : '—'}</td>
              <td className="px-3 py-2 text-right tabular-nums">{l.po_unit_price ? money(l.po_unit_price) : '—'}</td>
              <td className="px-3 py-2"><Badge tone={tone(l.status) as 'green' | 'red' | 'amber'}>{l.status.replace(/_/g, ' ').toLowerCase()}</Badge><p className="mt-1 max-w-xs text-[11px] text-slate-500">{l.note}</p></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
