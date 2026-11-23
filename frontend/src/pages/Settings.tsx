import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Cpu, Gauge, RotateCcw, ScanText, ShieldAlert } from 'lucide-react'
import { useState } from 'react'
import { Badge, Button, Card, CardBody, CardHeader, ErrorBox, Kv, PageHeader, PageLoading } from '@/components/ui'
import { api } from '@/services/api'

export default function SettingsPage() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  if (q.isLoading) return <PageLoading />
  if (q.isError) return <ErrorBox error={q.error} onRetry={() => q.refetch()} />
  const s = q.data!
  const offline = s.extraction.provider === 'heuristic'

  const reset = async () => {
    if (!window.confirm('Delete all processed invoices, runs and audit history and reload the original vendors / POs? This cannot be undone.')) return
    setBusy(true); setMsg(null)
    try { await api.reset(); setMsg('Demo data reset. The database now holds only the seeded vendors, POs and PO history.'); qc.invalidateQueries() } catch (e) { setMsg(e instanceof Error ? e.message : 'Reset failed.') } finally { setBusy(false) }
  }

  return (
    <>
      <PageHeader title="Settings" subtitle="Read-only view of the running configuration. Values come from environment variables (see .env.example)." />
      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title={<span className="flex items-center gap-2"><Cpu className="h-4 w-4 text-navy-600" /> AI extraction</span>} action={<Badge tone={offline ? 'amber' : 'green'}>{offline ? 'Offline parser' : 'AI active'}</Badge>} />
          <CardBody>
            <dl>
              <Kv k="Provider" v={s.extraction.provider} /><Kv k="Model" v={s.extraction.model} />
              <Kv k="API keys configured" v={Object.entries(s.extraction.configured_keys).map(([k, v]) => <Badge key={k} tone={v ? 'green' : 'slate'} className="ml-1">{k}</Badge>)} />
              <Kv k="Retries / timeout" v={`${s.extraction.max_retries} retries · ${s.extraction.timeout_s}s`} />
            </dl>
            {s.extraction.error && <p className="mt-3 rounded-lg bg-bad-50 p-3 text-xs text-bad-700">{s.extraction.error}</p>}
            {offline && <p className="mt-3 rounded-lg bg-warn-50 p-3 text-xs text-warn-700">No LLM key is set, so invoices are read by the built-in rule-based parser. Add <code>ANTHROPIC_API_KEY</code>, <code>OPENAI_API_KEY</code> or <code>GEMINI_API_KEY</code> to the backend environment and restart to enable AI extraction. Decisions are identical either way: the rules never use an LLM.</p>}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={<span className="flex items-center gap-2"><ScanText className="h-4 w-4 text-navy-600" /> OCR</span>} action={<Badge tone={s.ocr.available ? 'green' : 'red'}>{s.ocr.available ? 'Ready' : 'Unavailable'}</Badge>} />
          <CardBody><dl><Kv k="Engine" v={s.ocr.engine} /><Kv k="Used when a page has fewer than" v={`${s.ocr.min_chars_per_page} characters`} /><Kv k="Low-confidence threshold" v={`${Math.round(s.ocr.low_confidence_threshold * 100)}%`} /></dl></CardBody>
        </Card>
        <Card>
          <CardHeader title={<span className="flex items-center gap-2"><Gauge className="h-4 w-4 text-navy-600" /> Financial policy</span>} subtitle="Applied by the deterministic rule engine" />
          <CardBody><dl>
            <Kv k="Percentage tolerance" v={`${s.policy.tolerance_pct}%`} /><Kv k="Fixed monetary tolerance" v={Number(s.policy.tolerance_abs) > 0 ? s.policy.tolerance_abs : 'Disabled'} />
            <Kv k="Arithmetic rounding allowance" v={s.policy.rounding_tolerance} /><Kv k="Stale invoice age" v={`${s.policy.max_invoice_age_days} days`} />
            <Kv k="Upload limit" v={`${s.limits.max_upload_mb} MB · ${s.limits.max_pages} pages`} />
          </dl>
          <p className="mt-3 text-xs text-slate-500">Tolerance applies to price/total variance only. It can never push an invoice past the authorized PO value or the remaining PO balance.</p></CardBody>
        </Card>
        <Card>
          <CardHeader title={<span className="flex items-center gap-2"><ShieldAlert className="h-4 w-4 text-navy-600" /> Access & company</span>} />
          <CardBody><dl><Kv k="Buyer (our company)" v={s.buyer.name} /><Kv k="Buyer tax ID" v={s.buyer.tax_id} mono /><Kv k="Acting reviewer" v={s.demo_user} /></dl><p className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">{s.auth_note}</p></CardBody>
        </Card>
      </div>
      <Card className="mt-5">
        <CardHeader title="Demo data" subtitle="Start a clean demonstration run" />
        <CardBody className="flex flex-wrap items-center gap-4">
          <Button variant="danger" onClick={reset} loading={busy} data-testid="reset-demo"><RotateCcw className="h-4 w-4" /> Reset demo data</Button>
          <p className="text-xs text-slate-500">Removes processed invoices, runs and audit events; restores vendors, purchase orders and the PO invoice history.</p>
          {msg && <p className="w-full text-sm text-ok-700" role="status">{msg}</p>}
        </CardBody>
      </Card>
    </>
  )
}
