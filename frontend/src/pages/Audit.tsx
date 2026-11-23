import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, ScrollText } from 'lucide-react'
import { useState } from 'react'
import { Button, Card, CardBody, EmptyState, ErrorBox, PageHeader, PageLoading, Select } from '@/components/ui'
import { AuditList } from '@/pages/InvoiceDetail'
import { api } from '@/services/api'
import { humanize } from '@/utils/format'

export default function Audit() {
  const [page, setPage] = useState(1)
  const [type, setType] = useState('')
  const size = 25
  const q = useQuery({ queryKey: ['audit', page, type], queryFn: () => api.audit({ page, page_size: size, event_type: type || undefined }), refetchInterval: 6000, placeholderData: (p) => p })
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / size)) : 1
  return (
    <>
      <PageHeader title="Audit trail" subtitle="Append-only record of every important action: who did what, when, what changed, and why." />
      <Card>
        <div className="flex items-center gap-3 border-b border-slate-100 p-4">
          <Select className="w-64" value={type} onChange={(e) => { setType(e.target.value); setPage(1) }} aria-label="Filter by event type">
            <option value="">All event types</option>{q.data?.event_types.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
          </Select>
          <span className="text-xs text-slate-500">{q.data?.total ?? 0} events</span>
        </div>
        {q.isLoading ? <PageLoading /> : q.isError ? <div className="p-4"><ErrorBox error={q.error} onRetry={() => q.refetch()} /></div> : q.data!.items.length === 0 ? <EmptyState icon={<ScrollText className="h-6 w-6" />} title="No audit events" /> : (
          <CardBody>
            <AuditList events={q.data!.items} showInvoice />
            <div className="mt-5 flex items-center justify-end gap-1 text-xs text-slate-500">
              <Button variant="ghost" size="icon" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Newer"><ChevronLeft className="h-4 w-4" /></Button>
              <span className="tabular-nums">Page {page} of {pages}</span>
              <Button variant="ghost" size="icon" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Older"><ChevronRight className="h-4 w-4" /></Button>
            </div>
          </CardBody>
        )}
      </Card>
    </>
  )
}
