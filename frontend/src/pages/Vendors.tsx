import { useQuery } from '@tanstack/react-query'
import { Search, Store } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Drawer } from '@/components/Drawer'
import { DecisionBadge, PoStatusBadge, VendorStatusBadge } from '@/components/StatusBadge'
import { Card, EmptyState, ErrorBox, Input, Kv, PageHeader, PageLoading, Select, Table, Td, Th } from '@/components/ui'
import { api } from '@/services/api'
import { money } from '@/utils/format'

export default function Vendors() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [openId, setOpenId] = useState<number | null>(null)
  const q = useQuery({ queryKey: ['vendors', search, status], queryFn: () => api.vendors({ search: search || undefined, status: status || undefined }), placeholderData: (p) => p })
  const detail = useQuery({ queryKey: ['vendor', openId], queryFn: () => api.vendor(openId!), enabled: openId !== null })

  return (
    <>
      <PageHeader title="Vendor management" subtitle="The vendor master used for verification. Inactive vendors go to review; blocked vendors are rejected." />
      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 p-4">
          <div className="relative min-w-[220px] flex-1"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" /><Input className="pl-9" placeholder="Search name, tax ID or vendor ID" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search vendors" /></div>
          <Select className="w-44" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by approval status"><option value="">All statuses</option><option value="APPROVED">Approved</option><option value="INACTIVE">Inactive</option><option value="BLOCKED">Blocked</option></Select>
        </div>
        {q.isLoading ? <PageLoading /> : q.isError ? <div className="p-4"><ErrorBox error={q.error} onRetry={() => q.refetch()} /></div> : q.data!.items.length === 0 ? <EmptyState icon={<Store className="h-6 w-6" />} title="No vendors match" /> : (
          <Table>
            <thead><tr><Th>Vendor ID</Th><Th>Legal name</Th><Th>Aliases</Th><Th>Tax ID</Th><Th>Country</Th><Th>Approval</Th><Th className="text-right">POs</Th><Th className="text-right">Invoices</Th></tr></thead>
            <tbody>
              {q.data!.items.map((v) => (
                <tr key={v.id} className="cursor-pointer hover:bg-slate-50" onClick={() => setOpenId(v.id)} data-testid="vendor-row">
                  <Td className="font-mono text-xs">{v.vendor_id}</Td><Td className="font-medium text-slate-900">{v.legal_name}</Td>
                  <Td className="text-xs text-slate-500">{v.aliases.length ? v.aliases.join(', ') : '—'}</Td><Td className="font-mono text-xs">{v.tax_id}</Td><Td>{v.country}</Td>
                  <Td><VendorStatusBadge status={v.approval_status} /></Td><Td className="text-right tabular-nums">{v.purchase_orders}</Td><Td className="text-right tabular-nums">{v.invoices}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <Drawer open={openId !== null} onClose={() => setOpenId(null)} title={detail.data?.legal_name ?? 'Vendor'} subtitle={detail.data && `${detail.data.vendor_id} · ${detail.data.country}`}>
        {!detail.data ? <PageLoading /> : (
          <div className="space-y-6">
            <Card className="p-4"><dl>
              <Kv k="Approval status" v={<VendorStatusBadge status={detail.data.approval_status} />} /><Kv k="Tax identifier" v={detail.data.tax_id} mono />
              <Kv k="Approved aliases" v={detail.data.aliases.length ? detail.data.aliases.join(', ') : 'None'} /><Kv k="Country" v={detail.data.country} />
            </dl></Card>
            <div>
              <h3 className="mb-2 text-sm font-semibold">Purchase orders ({detail.data.purchase_order_list.length})</h3>
              <div className="overflow-hidden rounded-lg border border-slate-200"><Table>
                <thead><tr><Th>PO</Th><Th className="text-right">Value</Th><Th className="text-right">Remaining</Th><Th>Status</Th></tr></thead>
                <tbody>{detail.data.purchase_order_list.map((p) => <tr key={p.id}><Td className="font-mono text-xs">{p.po_number}</Td><Td className="text-right tabular-nums">{money(p.authorized_total, p.currency)}</Td><Td className="text-right tabular-nums">{money(p.remaining_balance, p.currency)}</Td><Td><PoStatusBadge status={p.status} /></Td></tr>)}</tbody>
              </Table></div>
            </div>
            <div>
              <h3 className="mb-2 text-sm font-semibold">Related invoices ({detail.data.invoice_list.length})</h3>
              {detail.data.invoice_list.length === 0 ? <p className="text-sm text-slate-500">No invoices from this vendor yet.</p> : (
                <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
                  {detail.data.invoice_list.map((i) => <li key={i.id} className="flex items-center gap-3 px-4 py-2.5 text-sm"><Link to={`/invoices/${i.id}`} className="font-medium text-navy-700 hover:underline">{i.invoice_number ?? `#${i.id}`}</Link><span className="flex-1 font-mono text-xs text-slate-500">{i.po_number}</span><span className="tabular-nums">{money(i.total_amount, i.currency)}</span><DecisionBadge decision={i.final_decision} /></li>)}
                </ul>
              )}
            </div>
          </div>
        )}
      </Drawer>
    </>
  )
}
