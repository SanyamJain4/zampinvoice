import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { RuleBadge } from '@/components/StatusBadge'
import { cn } from '@/utils/format'
import type { Rule } from '@/types'

const sevDot: Record<string, string> = { CRITICAL: 'bg-bad-600', HIGH: 'bg-warn-600', MEDIUM: 'bg-navy-500', LOW: 'bg-slate-300' }

export function RuleList({ rules, compact = false, defaultOpenFlagged = true }: { rules: Rule[]; compact?: boolean; defaultOpenFlagged?: boolean }) {
  return (
    <ul className="divide-y divide-slate-100">
      {rules.map((r) => (
        <RuleRow key={r.rule_id} rule={r} compact={compact} defaultOpen={defaultOpenFlagged && (r.status === 'FAIL' || r.status === 'REVIEW')} />
      ))}
    </ul>
  )
}

function RuleRow({ rule, compact, defaultOpen }: { rule: Rule; compact: boolean; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <li className={cn(rule.status === 'FAIL' && 'bg-bad-50/40', rule.status === 'REVIEW' && 'bg-warn-50/50')}>
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full cursor-pointer items-center gap-3 px-4 py-2.5 text-left hover:bg-slate-50/70" aria-expanded={open}>
        {open ? <ChevronDown className="h-4 w-4 shrink-0 text-slate-400" /> : <ChevronRight className="h-4 w-4 shrink-0 text-slate-400" />}
        <span className="w-10 shrink-0 font-mono text-xs text-slate-500">{rule.rule_id}</span>
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-800">{rule.rule_name}</span>
        {rule.hard_block && rule.status === 'FAIL' && <span className="rounded bg-bad-600 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-white">Hard block</span>}
        {!compact && <span className="hidden items-center gap-1.5 text-xs text-slate-400 sm:flex"><span className={cn('h-2 w-2 rounded-full', sevDot[rule.severity])} />{rule.severity.toLowerCase()}</span>}
        <RuleBadge status={rule.status} />
      </button>
      {open && (
        <div className="slide-in space-y-1.5 px-4 pb-3 pl-[4.25rem] text-sm">
          <p className="text-slate-700">{rule.explanation}</p>
          <dl className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-[auto_1fr]">
            <dt className="text-slate-400">Expected</dt><dd className="text-slate-600">{rule.expected}</dd>
            <dt className="text-slate-400">Observed</dt><dd className="font-mono text-slate-700 break-words">{rule.observed}</dd>
          </dl>
        </div>
      )}
    </li>
  )
}
