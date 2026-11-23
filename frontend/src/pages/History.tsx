import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, History as HistoryIcon } from 'lucide-react'
import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { StageIcon } from '@/components/StatusBadge'
import { DecisionBadge } from '@/components/StatusBadge'
import { Badge, Button, Card, EmptyState, ErrorBox, PageHeader, PageLoading, Select, Table, Td, Th } from '@/components/ui'
import { api } from '@/services/api'
import { cn, dateTime, duration, money, seconds } from '@/utils/format'

const dot: Record<string, string> = { COMPLETED: 'bg-ok-600', WARNING: 'bg-warn-600', FAILED: 'bg-bad-600', RUNNING: 'bg-navy-600', SKIPPED: 'bg-slate-300', QUEUED: 'bg-slate-200' }

export default function HistoryPage() {
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const size = 15
  const q = useQuery({ queryKey: ['runs', page, status], queryFn: () => api.runs({ page, page_size: size, status: status || undefined }), refetchInterval: 5000, placeholderData: (p) => p })
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / size)) : 1

  return (
    <>
      <PageHeader title="Processing history" subtitle="Every pipeline run with per-stage timing. Failed runs are processing errors, not business rejections." />
      <Card>
        <div className="flex items-center gap-3 border-b border-slate-100 p-4">
          <Select className="w-48" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }} aria-label="Filter runs by status"><option value="">All runs</option><option value="COMPLETED">Completed</option><option value="FAILED">Failed</option><option value="RUNNING">Running</option></Select>
        </div>
        {q.isLoading ? <PageLoading /> : q.isError ? <div className="p-4"><ErrorBox error={q.error} onRetry={() => q.refetch()} /></div> : q.data!.items.length === 0 ? <EmptyState icon={<HistoryIcon className="h-6 w-6" />} title="No runs yet" hint="Each time an invoice is processed, a run with its stage timings is recorded here." /> : (
          <>
            <Table>
              <thead><tr><Th>Run</Th><Th>Invoice</Th><Th>Type</Th><Th>Stages</Th><Th>Run status</Th><Th>Decision</Th><Th>Started</Th><Th className="text-right">Duration</Th></tr></thead>
              <tbody>
                {q.data!.items.map((r) => (
                  <Fragment key={r.run_id}>
                    <tr className="cursor-pointer hover:bg-slate-50" onClick={() => setOpen(open === r.run_id ? null : r.run_id)} data-testid="run-row">
                      <Td className="font-mono text-xs">{r.run_id.slice(0, 8)}</Td>
                      <Td><Link to={`/invoices/${r.invoice_id}`} className="font-medium text-navy-700 hover:underline" onClick={(e) => e.stopPropagation()}>{r.invoice_number ?? r.filename}</Link><div className="text-xs text-slate-500">{r.vendor_name} {r.total_amount && `· ${money(r.total_amount, r.currency)}`}</div></Td>
                      <Td><Badge tone={r.kind === 'FULL' ? 'indigo' : 'amber'}>{r.kind === 'FULL' ? 'Full' : 'Re-validation'}</Badge></Td>
                      <Td><div className="flex gap-1">{r.stages.map((s) => <span key={s.key} title={`${s.name}: ${s.status}`} className={cn('h-2.5 w-2.5 rounded-full', dot[s.status])} />)}</div></Td>
                      <Td><Badge tone={r.status === 'COMPLETED' ? 'green' : r.status === 'FAILED' ? 'red' : 'indigo'}>{r.status.toLowerCase()}</Badge></Td>
                      <Td><DecisionBadge decision={r.final_decision} /></Td>
                      <Td className="whitespace-nowrap text-slate-500">{dateTime(r.started_at)}</Td>
                      <Td className="text-right tabular-nums text-slate-500">{seconds(r.duration_s)}</Td>
                    </tr>
                    {open === r.run_id && (
                      <tr><td colSpan={8} className="border-b border-slate-100 bg-slate-50/60 px-6 py-4">
                        <div className="grid gap-x-8 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3">
                          {r.stages.map((s) => (
                            <div key={s.key} className="flex items-center gap-2 text-xs"><StageIcon status={s.status} className="h-4 w-4" /><span className="flex-1 text-slate-700">{s.name}</span><span className="tabular-nums text-slate-500">{duration(s.duration_ms)}</span></div>
                          ))}
                        </div>
                        {r.error_message && <p className="mt-3 text-xs text-bad-700">{r.error_message}</p>}
                      </td></tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </Table>
            <div className="flex items-center justify-between px-4 py-3 text-xs text-slate-500">
              <span>{q.data!.total} run{q.data!.total === 1 ? '' : 's'}</span>
              <div className="flex items-center gap-1"><Button variant="ghost" size="icon" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></Button><span className="tabular-nums">Page {page} of {pages}</span><Button variant="ghost" size="icon" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next page"><ChevronRight className="h-4 w-4" /></Button></div>
            </div>
          </>
        )}
      </Card>
    </>
  )
}
