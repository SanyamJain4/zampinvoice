import { useQuery } from '@tanstack/react-query'
import { Boxes, CheckCircle2, Search, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Drawer } from '@/components/Drawer'
import { DecisionBadge, PoStatusBadge } from '@/components/StatusBadge'
import { Card, EmptyState, ErrorBox, Input, PageHeader, PageLoading, Select, Table, Td, Th } from '@/components/ui'
import { api } from '@/services/api'
import { dateOnly, money } from '@/utils/format'

export default function PurchaseOrders() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [openId, setOpenId] = useState<number | null>(null)
  const q = useQuery({ queryKey: ['purchase-orders', search, status], queryFn: () => api.purchaseOrders({ search: search || undefined, status: status || undefined }), refetchInterval: 6000, placeholderData: (p) => p })
  const detail = useQuery({ queryKey: ['po', openId], queryFn: () => api.purchaseOrder(openId!), enabled: openId !== null, refetchInterval: 6000 })

  return (
    <>
      <PageHeader title="Purchase orders" subtitle="Remaining balance is always recomputed from approved invoices, never trusted from an editable field." />
      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 p-4">
          <div className="relative min-w-[220px] flex-1"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" /><Input className="pl-9" placeholder="Search PO number or vendor" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search purchase orders" /></div>
          <Select className="w-52" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
            <option value="">All statuses</option><option value="OPEN">Open</option><option value="PARTIALLY_INVOICED">Partially invoiced</option><option value="FULLY_INVOICED">Fully invoiced</option><option value="CLOSED">Closed</option>
          </Select>
        </div>
        {q.isLoading ? <PageLoading /> : q.isError ? <div className="p-4"><ErrorBox error={q.error} onRetry={() => q.refetch()} /></div> : q.data!.items.length === 0 ? <EmptyState icon={<Boxes className="h-6 w-6" />} title="No purchase orders match" hint="Clear the search or filter." /> : (
          <Table>
            <thead><tr><Th>PO number</Th><Th>Vendor</Th><Th>Cur.</Th><Th className="text-right">Original value</Th><Th className="text-right">Invoiced</Th><Th className="text-right">Remaining</Th><Th>Status</Th><Th className="text-right">Invoices</Th></tr></thead>
            <tbody>
              {q.data!.items.map((p) => {
                const pct = Math.min(100, (Number(p.invoiced_amount) / Number(p.authorized_total)) * 100)
                return (
                  <tr key={p.id} className="cursor-pointer hover:bg-slate-50" onClick={() => setOpenId(p.id)} data-testid="po-row">
                    <Td className="font-mono text-xs font-medium text-slate-900">{p.po_number}</Td>
                    <Td>{p.vendor_name}</Td><Td className="text-slate-500">{p.currency}</Td>
                    <Td className="text-right tabular-nums">{money(p.authorized_total, p.currency)}</Td>
                    <Td className="text-right tabular-nums"><div>{money(p.invoiced_amount, p.currency)}</div><div className="mt-1 h-1 w-full overflow-hidden rounded bg-slate-100"><div className="h-full bg-navy-600" style={{ width: `${pct}%` }} /></div></Td>
                    <Td className="text-right font-medium tabular-nums">{money(p.remaining_balance, p.currency)}</Td>
                    <Td><PoStatusBadge status={p.status} /></Td>
                    <Td className="text-right tabular-nums">{p.linked_invoices}</Td>
                  </tr>
                )
              })}
            </tbody>
          </Table>
        )}
      </Card>

      <Drawer open={openId !== null} onClose={() => setOpenId(null)} title={detail.data ? `Purchase order ${detail.data.po_number}` : 'Purchase order'} subtitle={detail.data && `${detail.data.vendor_name} · issued ${dateOnly(detail.data.issue_date)} · ${detail.data.description ?? ''}`}>
        {!detail.data ? <PageLoading /> : (
          <div className="space-y-6">
            <div className="grid grid-cols-3 gap-3">
              {[['Authorized', detail.data.authorized_total], ['Approved invoices', detail.data.invoiced_amount], ['Remaining', detail.data.remaining_balance]].map(([k, v]) => (
                <div key={k} className="rounded-lg border border-slate-200 p-3"><p className="text-xs text-slate-500">{k}</p><p className="mt-0.5 text-base font-semibold tabular-nums">{money(v, detail.data!.currency)}</p></div>
              ))}
            </div>
            <p className="flex items-center gap-2 text-xs">
              <PoStatusBadge status={detail.data.status} />
              {detail.data.balance.reconciled ? <span className="inline-flex items-center gap-1 text-ok-700"><CheckCircle2 className="h-3.5 w-3.5" /> Cached balance reconciled with approved invoices</span> : <span className="inline-flex items-center gap-1 text-bad-700"><TriangleAlert className="h-3.5 w-3.5" /> Cached balance differs from reconciliation</span>}
            </p>
            <div>
              <h3 className="mb-2 text-sm font-semibold text-slate-900">Line items</h3>
              <div className="overflow-hidden rounded-lg border border-slate-200">
                <Table>
                  <thead><tr><Th>#</Th><Th>Item</Th><Th className="text-right">Qty</Th><Th className="text-right">Invoiced</Th><Th className="text-right">Left</Th><Th className="text-right">Unit price</Th><Th className="text-right">Authorized</Th></tr></thead>
                  <tbody>{detail.data.lines.map((l) => <tr key={l.id}><Td>{l.line_no}</Td><Td>{l.item_description}<div className="font-mono text-[11px] text-slate-400">{l.sku} · tax {Number(l.tax_rate)}%</div></Td><Td className="text-right tabular-nums">{l.quantity}</Td><Td className="text-right tabular-nums">{l.quantity_invoiced}</Td><Td className="text-right tabular-nums">{l.quantity_remaining}</Td><Td className="text-right tabular-nums">{money(l.unit_price)}</Td><Td className="text-right tabular-nums">{money(l.authorized_amount)}</Td></tr>)}</tbody>
                </Table>
              </div>
            </div>
            <div>
              <h3 className="mb-2 text-sm font-semibold text-slate-900">Linked invoices ({detail.data.invoices.length})</h3>
              {detail.data.invoices.length === 0 ? <p className="text-sm text-slate-500">No invoices linked yet.</p> : (
                <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
                  {detail.data.invoices.map((i) => (
                    <li key={i.id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                      <Link to={`/invoices/${i.id}`} className="font-medium text-navy-700 hover:underline">{i.invoice_number ?? `#${i.id}`}</Link>
                      <span className="flex-1 text-slate-500">{i.source === 'HISTORY' ? 'seeded history' : i.filename}</span>
                      <span className="tabular-nums">{money(i.total_amount, i.currency)}</span><DecisionBadge decision={i.final_decision} processing={i.processing_status} />
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </Drawer>
    </>
  )
}
