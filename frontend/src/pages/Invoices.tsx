import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, FileText, Search, UploadCloud } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { DecisionBadge } from '@/components/StatusBadge'
import { Badge, Button, Card, EmptyState, ErrorBox, Input, PageHeader, PageLoading, Select, Table, Td, Th } from '@/components/ui'
import { api } from '@/services/api'
import { dateOnly, dateTime, money, seconds } from '@/utils/format'

export function InvoiceTable({ items, onRowClick }: { items: Awaited<ReturnType<typeof api.invoices>>['items']; onRowClick: (id: number) => void }) {
  return (
    <Table>
      <thead><tr><Th>Invoice #</Th><Th>Vendor</Th><Th>PO</Th><Th>Invoice date</Th><Th className="text-right">Amount</Th><Th>Status</Th><Th>Source</Th><Th>Uploaded</Th><Th className="text-right">Duration</Th></tr></thead>
      <tbody>
        {items.map((i) => (
          <tr key={i.id} className="cursor-pointer hover:bg-slate-50" onClick={() => onRowClick(i.id)} data-testid="invoice-row">
            <Td className="font-medium text-slate-900">{i.invoice_number ?? <span className="font-normal text-slate-400" title={i.filename ?? ''}>— (no number)</span>}</Td>
            <Td>{i.vendor_name ?? '—'}</Td>
            <Td className="font-mono text-xs">{i.po_number ?? '—'}</Td>
            <Td className="text-slate-500">{dateOnly(i.invoice_date)}</Td>
            <Td className="text-right tabular-nums">{money(i.total_amount, i.currency)}</Td>
            <Td><DecisionBadge decision={i.final_decision} processing={i.processing_status} />{i.decision_source === 'MANUAL' && <span className="ml-1 text-[10px] text-slate-400">manual</span>}</Td>
            <Td>{i.source === 'HISTORY' ? <Badge>seeded history</Badge> : <span className="text-xs text-slate-500">upload</span>}</Td>
            <Td className="text-slate-500">{dateTime(i.created_at)}</Td>
            <Td className="text-right tabular-nums text-slate-500">{seconds(i.duration_s)}</Td>
          </tr>
        ))}
      </tbody>
    </Table>
  )
}

export default function Invoices() {
  const nav = useNavigate()
  const [sp, setSp] = useSearchParams()
  const [search, setSearch] = useState(sp.get('search') ?? '')
  const [decision, setDecision] = useState(sp.get('decision') ?? '')
  const [history, setHistory] = useState(false)
  const [page, setPage] = useState(1)
  const size = 15
  const q = useQuery({
    queryKey: ['invoices', { search, decision, history, page }],
    queryFn: () => api.invoices({ page, page_size: size, search: search || undefined, decision: decision || undefined, include_history: history }),
    refetchInterval: 5000,
    placeholderData: (p) => p,
  })
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / size)) : 1

  return (
    <>
      <PageHeader title="All invoices" subtitle="Every invoice that has entered the pipeline, with its decision." actions={<Link to="/process"><Button><UploadCloud className="h-4 w-4" /> Process invoice</Button></Link>} />
      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 p-4">
          <div className="relative min-w-[220px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <Input className="pl-9" placeholder="Search invoice #, vendor, PO or filename" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); setSp(e.target.value ? { search: e.target.value } : {}) }} aria-label="Search invoices" />
          </div>
          <Select className="w-44" value={decision} onChange={(e) => { setDecision(e.target.value); setPage(1) }} aria-label="Filter by decision">
            <option value="">All decisions</option>
            <option value="APPROVED">Approved</option>
            <option value="NEEDS_REVIEW">Needs review</option>
            <option value="REJECTED">Rejected</option>
            <option value="PROCESSING_ERROR">Processing error</option>
          </Select>
          <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-600"><input type="checkbox" checked={history} onChange={(e) => { setHistory(e.target.checked); setPage(1) }} /> Include seeded PO history</label>
        </div>
        {q.isLoading ? <PageLoading /> : q.isError ? <div className="p-4"><ErrorBox error={q.error} onRetry={() => q.refetch()} /></div> : q.data!.items.length === 0 ? (
          <EmptyState icon={<FileText className="h-6 w-6" />} title={search || decision ? 'No invoices match these filters' : 'No invoices yet'} hint={search || decision ? 'Try clearing the search or filter.' : 'Process an invoice and it will appear here.'} />
        ) : (
          <>
            <InvoiceTable items={q.data!.items} onRowClick={(id) => nav(`/invoices/${id}`)} />
            <div className="flex items-center justify-between px-4 py-3 text-xs text-slate-500">
              <span>{q.data!.total} invoice{q.data!.total === 1 ? '' : 's'}</span>
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="icon" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></Button>
                <span className="tabular-nums">Page {page} of {pages}</span>
                <Button variant="ghost" size="icon" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next page"><ChevronRight className="h-4 w-4" /></Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </>
  )
}
