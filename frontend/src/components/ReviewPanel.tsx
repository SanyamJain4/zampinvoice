import { useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Lock, MessageSquareWarning, Pencil, ShieldAlert, XCircle } from 'lucide-react'
import { useState } from 'react'
import { PipelineTimeline } from '@/components/PipelineTimeline'
import { Badge, Button, Card, CardBody, CardHeader, Input, Label, Textarea } from '@/components/ui'
import { useRunStream } from '@/hooks/useRunStream'
import { ApiError, api } from '@/services/api'
import type { InvoiceDetail } from '@/types'

const FIELDS: { key: string; label: string; type?: string }[] = [
  { key: 'vendor_name', label: 'Vendor name' },
  { key: 'vendor_tax_id', label: 'Vendor tax ID' },
  { key: 'invoice_number', label: 'Invoice number' },
  { key: 'invoice_date', label: 'Invoice date', type: 'date' },
  { key: 'po_number', label: 'PO number' },
  { key: 'currency', label: 'Currency (ISO)' },
  { key: 'subtotal', label: 'Subtotal' },
  { key: 'tax_amount', label: 'Tax amount' },
  { key: 'grand_total', label: 'Grand total' },
]

export function ReviewPanel({ inv }: { inv: InvoiceDetail }) {
  const qc = useQueryClient()
  const [mode, setMode] = useState<'decide' | 'correct'>('decide')
  const [justification, setJustification] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<{ message: string; blocking: ApiError['blocking'] } | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [vals, setVals] = useState<Record<string, string>>({})
  const [reason, setReason] = useState('')
  const [revalRun, setRevalRun] = useState<string | null>(null)

  const refresh = () => ['invoice', 'invoices', 'reviews', 'metrics', 'trends', 'purchase-orders', 'audit', 'runs'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }))
  const { run } = useRunStream(revalRun, () => { refresh(); setNotice('Validation re-run finished. Check the updated results below.') })
  const ex = inv.extraction
  const blockers = inv.approval_blockers
  const jOk = justification.trim().length >= 10

  const act = async (action: 'APPROVE' | 'REJECT' | 'REQUEST_CLARIFICATION') => {
    setBusy(action); setError(null); setNotice(null)
    try {
      await api.review(inv.id, action, justification.trim())
      setJustification('')
      setNotice(action === 'APPROVE' ? 'Invoice approved. The action is recorded in the audit trail.' : action === 'REJECT' ? 'Invoice rejected and recorded.' : 'Clarification requested. The invoice stays in the queue.')
      refresh()
    } catch (e) {
      if (e instanceof ApiError) setError({ message: e.message, blocking: e.blocking })
      else setError({ message: 'The action could not be completed.', blocking: [] })
    } finally { setBusy(null) }
  }

  const saveCorrections = async () => {
    const changes: Record<string, string> = {}
    FIELDS.forEach(({ key }) => {
      const cur = (ex as unknown as Record<string, string | null>)?.[key] ?? ''
      if (key in vals && vals[key] !== cur) changes[key] = vals[key]
    })
    if (!Object.keys(changes).length) { setError({ message: 'Change at least one value first.', blocking: [] }); return }
    setBusy('correct'); setError(null); setNotice(null)
    try {
      const r = await api.correct(inv.id, changes, reason.trim())
      setRevalRun(r.run_id); setVals({}); setReason(''); setMode('decide')
      refresh()
    } catch (e) {
      setError({ message: e instanceof Error ? e.message : 'Corrections could not be saved.', blocking: [] })
    } finally { setBusy(null) }
  }

  return (
    <Card className="border-warn-100" data-testid="review-panel">
      <CardHeader
        title={<span className="flex items-center gap-2"><MessageSquareWarning className="h-4 w-4 text-warn-600" /> Manual review</span>}
        subtitle={inv.review_state === 'CLARIFICATION_REQUESTED' ? 'Clarification has been requested from the vendor.' : 'A person decides. Hard financial controls cannot be bypassed.'}
        action={
          <div className="flex rounded-lg border border-slate-200 p-0.5 text-xs">
            <button className={`cursor-pointer rounded-md px-2.5 py-1 ${mode === 'decide' ? 'bg-navy-50 font-medium text-navy-700' : 'text-slate-500'}`} onClick={() => setMode('decide')}>Decide</button>
            <button className={`flex cursor-pointer items-center gap-1 rounded-md px-2.5 py-1 ${mode === 'correct' ? 'bg-navy-50 font-medium text-navy-700' : 'text-slate-500'}`} onClick={() => setMode('correct')}><Pencil className="h-3 w-3" /> Correct data</button>
          </div>
        }
      />
      <CardBody className="space-y-4">
        {run && run.status !== 'COMPLETED' && (
          <div className="rounded-lg border border-navy-100 bg-navy-50/40 p-3"><p className="mb-2 text-xs font-medium text-navy-700">Re-running validation on the corrected data…</p><PipelineTimeline run={run} /></div>
        )}
        {notice && <p className="rounded-lg bg-ok-50 px-3 py-2 text-sm text-ok-700" role="status">{notice}</p>}
        {error && (
          <div className="rounded-lg border border-bad-100 bg-bad-50 px-3 py-2 text-sm text-bad-700" role="alert">
            <p>{error.message}</p>
            {error.blocking.length > 0 && <ul className="mt-1 list-disc pl-5 text-xs">{error.blocking.map((b) => <li key={b.rule_id}><b>{b.rule_id} {b.rule_name}:</b> {b.explanation}</li>)}</ul>}
          </div>
        )}

        {blockers.length > 0 && mode === 'decide' && (
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
            <p className="mb-1 flex items-center gap-1.5 font-semibold"><Lock className="h-3.5 w-3.5 text-slate-500" /> Approval is locked by hard controls</p>
            <ul className="list-disc space-y-0.5 pl-5">{blockers.map((b) => <li key={b.rule_id}><b>{b.rule_id} {b.rule_name}</b>: {b.explanation}</li>)}</ul>
            <p className="mt-2 text-slate-500">You can still <b>reject</b> or <b>request clarification</b>, or correct the data if the extraction was wrong.</p>
          </div>
        )}

        {mode === 'decide' ? (
          <>
            <div>
              <Label hint="(required, min. 10 characters; stored in the audit trail)">Justification</Label>
              <Textarea rows={3} value={justification} onChange={(e) => setJustification(e.target.value)} placeholder="What did you verify? e.g. “Confirmed with vendor by phone; package = PO lines 1-3.”" aria-label="Justification" data-testid="justification" />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="success" disabled={!jOk || !inv.can_approve_manually} loading={busy === 'APPROVE'} onClick={() => act('APPROVE')} title={!inv.can_approve_manually ? 'Locked by hard financial controls' : undefined} data-testid="approve-btn">{inv.can_approve_manually ? <CheckCircle2 className="h-4 w-4" /> : <ShieldAlert className="h-4 w-4" />} Approve</Button>
              <Button variant="danger" disabled={!jOk} loading={busy === 'REJECT'} onClick={() => act('REJECT')} data-testid="reject-btn"><XCircle className="h-4 w-4" /> Reject</Button>
              <Button variant="warn" disabled={!jOk} loading={busy === 'REQUEST_CLARIFICATION'} onClick={() => act('REQUEST_CLARIFICATION')} data-testid="clarify-btn"><MessageSquareWarning className="h-4 w-4" /> Request clarification</Button>
            </div>
            {inv.decision.corrected_data && <Badge tone="indigo">Based on reviewer-corrected data: explicit approval required</Badge>}
          </>
        ) : (
          <>
            <p className="text-xs text-slate-500">Fix values the extraction got wrong, compare against the PDF on the left. Saving re-runs every check; corrected invoices are never auto-approved.</p>
            <div className="grid gap-3 sm:grid-cols-2">
              {FIELDS.map((f) => {
                const cur = (ex as unknown as Record<string, string | null>)?.[f.key] ?? ''
                return (
                  <div key={f.key}>
                    <Label>{f.label}</Label>
                    <Input type={f.type ?? 'text'} value={f.key in vals ? vals[f.key] : cur} onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })} placeholder={cur ? undefined : 'not found'} aria-label={f.label} data-testid={`field-${f.key}`} />
                  </div>
                )
              })}
            </div>
            <div>
              <Label hint="(required)">Reason for correction</Label>
              <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Invoice number is printed in the footer stamp" aria-label="Reason for correction" data-testid="correction-reason" />
            </div>
            <Button loading={busy === 'correct'} disabled={reason.trim().length < 5} onClick={saveCorrections} data-testid="save-corrections"><Pencil className="h-4 w-4" /> Save & re-run validation</Button>
          </>
        )}
      </CardBody>
    </Card>
  )
}
