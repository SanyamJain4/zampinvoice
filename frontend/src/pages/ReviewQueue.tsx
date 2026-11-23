import { useQuery } from '@tanstack/react-query'
import { ClipboardCheck, PartyPopper } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { SeverityBadge } from '@/components/StatusBadge'
import { Badge, Button, Card, EmptyState, ErrorBox, PageHeader, PageLoading, Table, Td, Th } from '@/components/ui'
import { api } from '@/services/api'
import { dateTime, humanize, money } from '@/utils/format'

export default function ReviewQueue() {
  const nav = useNavigate()
  const [resolved, setResolved] = useState(false)
  const q = useQuery({ queryKey: ['reviews', resolved], queryFn: () => api.reviews(resolved), refetchInterval: 5000 })

  return (
    <>
      <PageHeader title="Review queue" subtitle="Invoices the system could not safely decide on its own, most severe first." actions={
        <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-600"><input type="checkbox" checked={resolved} onChange={(e) => setResolved(e.target.checked)} /> Include manually resolved</label>
      } />
      <Card>
        {q.isLoading ? <PageLoading /> : q.isError ? <div className="p-4"><ErrorBox error={q.error} onRetry={() => q.refetch()} /></div> : q.data!.items.length === 0 ? (
          <EmptyState icon={resolved ? <ClipboardCheck className="h-6 w-6" /> : <PartyPopper className="h-6 w-6" />} title="The queue is empty" hint="Nothing needs a human right now. Invoices with missing data, mismatches or other uncertainty land here." action={<Link to="/process"><Button variant="secondary">Process an invoice</Button></Link>} />
        ) : (
          <Table>
            <thead><tr><Th>Vendor</Th><Th>Invoice #</Th><Th className="text-right">Amount</Th><Th>Reason for review</Th><Th>Severity</Th><Th>Uploaded</Th><Th>Status</Th><Th /></tr></thead>
            <tbody>
              {q.data!.items.map((i) => (
                <tr key={i.id} className="cursor-pointer align-top hover:bg-slate-50" onClick={() => nav(`/invoices/${i.id}`)} data-testid="review-row">
                  <Td className="font-medium text-slate-900">{i.vendor_name ?? '—'}</Td>
                  <Td>{i.invoice_number ?? <span className="text-slate-400">— none —</span>}</Td>
                  <Td className="whitespace-nowrap text-right tabular-nums">{money(i.total_amount, i.currency)}</Td>
                  <Td className="max-w-md"><p className="line-clamp-2 text-slate-700">{i.reason}</p>{i.flagged_rules && <p className="mt-1 flex flex-wrap gap-1">{i.flagged_rules.map((r) => <span key={r} className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600">{r}</span>)}</p>}</Td>
                  <Td><SeverityBadge severity={i.severity} /></Td>
                  <Td className="whitespace-nowrap text-slate-500">{dateTime(i.created_at)}</Td>
                  <Td>{i.final_decision === 'NEEDS_REVIEW' ? <Badge tone={i.review_state === 'CLARIFICATION_REQUESTED' ? 'indigo' : 'amber'}>{i.review_state === 'CLARIFICATION_REQUESTED' ? 'Awaiting vendor' : 'Open'}</Badge> : <Badge tone={i.final_decision === 'APPROVED' ? 'green' : 'red'}>{humanize(i.final_decision ?? '')} (manual)</Badge>}</Td>
                  <Td className="text-right"><Link to={`/invoices/${i.id}`} onClick={(e) => e.stopPropagation()}><Button size="sm" variant="secondary">Review</Button></Link></Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  )
}
