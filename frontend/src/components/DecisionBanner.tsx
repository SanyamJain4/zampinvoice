import { AlertTriangle, ArrowRight, CheckCircle2, OctagonX, ShieldAlert, UserCheck } from 'lucide-react'
import type { DecisionDetail } from '@/types'
import { cn, money } from '@/utils/format'

const styles = {
  APPROVED: { box: 'border-ok-100 bg-ok-50', icon: <CheckCircle2 className="h-7 w-7 text-ok-600" />, title: 'Approved', text: 'text-ok-700' },
  NEEDS_REVIEW: { box: 'border-warn-100 bg-warn-50', icon: <AlertTriangle className="h-7 w-7 text-warn-600" />, title: 'Needs review', text: 'text-warn-700' },
  REJECTED: { box: 'border-bad-100 bg-bad-50', icon: <OctagonX className="h-7 w-7 text-bad-600" />, title: 'Rejected', text: 'text-bad-700' },
  PROCESSING_ERROR: { box: 'border-slate-300 bg-slate-100', icon: <ShieldAlert className="h-7 w-7 text-slate-600" />, title: 'Processing error', text: 'text-slate-700' },
} as const

export function DecisionBanner({ decision, source, error }: { decision: Partial<DecisionDetail> & { status?: string }; source?: string | null; error?: string | null }) {
  const key = (decision.status ?? 'NEEDS_REVIEW') as keyof typeof styles
  const s = styles[key] ?? styles.NEEDS_REVIEW
  const alloc = decision.allocation
  return (
    <div className={cn('slide-in rounded-xl border p-5', s.box)} data-testid="decision-banner" data-decision={key}>
      <div className="flex items-start gap-4">
        <div className="mt-0.5">{s.icon}</div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className={cn('text-lg font-semibold', s.text)}>{s.title}</h2>
            {source === 'MANUAL' && <span className="inline-flex items-center gap-1 rounded-full bg-white/70 px-2 py-0.5 text-xs font-medium text-slate-600"><UserCheck className="h-3 w-3" /> Manual decision</span>}
            {key === 'PROCESSING_ERROR' && <span className="rounded-full bg-white/70 px-2 py-0.5 text-xs text-slate-600">Not a business rejection</span>}
          </div>
          <p className="mt-1 text-sm text-slate-800">{error || decision.main_reason}</p>
          {alloc && (
            <div className="mt-3 inline-flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg bg-white/70 px-3 py-2 text-xs text-slate-700">
              <span>PO <b>{alloc.po_number}</b></span>
              <span>Remaining before <b>{money(alloc.remaining_before, alloc.currency)}</b></span>
              <ArrowRight className="h-3 w-3 text-slate-400" />
              <span>This invoice <b>{money(alloc.invoice_total, alloc.currency)}</b></span>
              <ArrowRight className="h-3 w-3 text-slate-400" />
              <span>Remaining after <b>{money(alloc.remaining_after, alloc.currency)}</b></span>
            </div>
          )}
          {decision.recommended_next_action && (
            <p className="mt-3 text-xs text-slate-600"><span className="font-semibold text-slate-700">Recommended next action:</span> {decision.recommended_next_action}</p>
          )}
        </div>
      </div>
    </div>
  )
}
