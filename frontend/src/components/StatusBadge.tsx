import { AlertTriangle, CheckCircle2, CircleSlash, Clock, Loader2, MinusCircle, OctagonX, ShieldAlert, XCircle } from 'lucide-react'
import { Badge } from '@/components/ui'
import { decisionLabel, humanize } from '@/utils/format'

export function DecisionBadge({ decision, processing }: { decision: string | null | undefined; processing?: string }) {
  if (!decision) {
    const label = processing === 'PROCESSING' ? 'Processing' : 'Not processed'
    return <Badge tone={processing === 'PROCESSING' ? 'indigo' : 'slate'}>{processing === 'PROCESSING' && <Loader2 className="h-3 w-3 animate-spin" />}{label}</Badge>
  }
  switch (decision) {
    case 'APPROVED': return <Badge tone="green"><CheckCircle2 className="h-3 w-3" />Approved</Badge>
    case 'NEEDS_REVIEW': return <Badge tone="amber"><AlertTriangle className="h-3 w-3" />Needs review</Badge>
    case 'REJECTED': return <Badge tone="red"><OctagonX className="h-3 w-3" />Rejected</Badge>
    case 'PROCESSING_ERROR': return <Badge tone="slate" className="!bg-slate-800 !text-white"><ShieldAlert className="h-3 w-3" />Processing error</Badge>
    default: return <Badge>{decisionLabel(decision)}</Badge>
  }
}

export function SeverityBadge({ severity }: { severity: string | null | undefined }) {
  if (!severity || severity === 'NONE') return <span className="text-slate-400">—</span>
  const tone = severity === 'CRITICAL' ? 'red' : severity === 'HIGH' ? 'amber' : severity === 'MEDIUM' ? 'indigo' : 'slate'
  return <Badge tone={tone}>{humanize(severity)}</Badge>
}

export function RuleBadge({ status }: { status: string }) {
  switch (status) {
    case 'PASS': return <Badge tone="green"><CheckCircle2 className="h-3 w-3" />Pass</Badge>
    case 'FAIL': return <Badge tone="red"><XCircle className="h-3 w-3" />Fail</Badge>
    case 'REVIEW': return <Badge tone="amber"><AlertTriangle className="h-3 w-3" />Review</Badge>
    default: return <Badge><CircleSlash className="h-3 w-3" />N/A</Badge>
  }
}

export function StageIcon({ status, className = 'h-5 w-5' }: { status: string; className?: string }) {
  switch (status) {
    case 'COMPLETED': return <CheckCircle2 className={`${className} text-ok-600`} />
    case 'WARNING': return <AlertTriangle className={`${className} text-warn-600`} />
    case 'FAILED': return <XCircle className={`${className} text-bad-600`} />
    case 'RUNNING': return <Loader2 className={`${className} animate-spin text-navy-600`} />
    case 'SKIPPED': return <MinusCircle className={`${className} text-slate-300`} />
    default: return <Clock className={`${className} text-slate-300`} />
  }
}

export function PoStatusBadge({ status }: { status: string }) {
  const tone = status === 'OPEN' ? 'indigo' : status === 'PARTIALLY_INVOICED' ? 'amber' : status === 'FULLY_INVOICED' ? 'green' : 'slate'
  return <Badge tone={tone}>{humanize(status)}</Badge>
}

export function VendorStatusBadge({ status }: { status: string }) {
  const tone = status === 'APPROVED' ? 'green' : status === 'INACTIVE' ? 'amber' : 'red'
  return <Badge tone={tone}>{humanize(status)}</Badge>
}
