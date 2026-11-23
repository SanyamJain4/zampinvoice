import { useQuery } from '@tanstack/react-query'
import { Banknote, CheckCircle2, ClipboardCheck, Clock, FileCheck2, Percent, UploadCloud, XCircle } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { DecisionBadge } from '@/components/StatusBadge'
import { Button, Card, CardBody, CardHeader, EmptyState, ErrorBox, PageHeader, PageLoading, Table, Td, Th } from '@/components/ui'
import { api } from '@/services/api'
import { compactMoney, dateTime, money, seconds } from '@/utils/format'

const C = { ok: '#059669', warn: '#d97706', bad: '#dc2626', err: '#475569', brand: '#4f46e5' }

function Kpi({ label, value, icon, tone = 'slate', hint }: { label: string; value: React.ReactNode; icon: React.ReactNode; tone?: 'slate' | 'green' | 'amber' | 'red' | 'indigo'; hint?: string }) {
  const tones = { slate: 'bg-slate-100 text-slate-600', green: 'bg-ok-50 text-ok-600', amber: 'bg-warn-50 text-warn-600', red: 'bg-bad-50 text-bad-600', indigo: 'bg-navy-50 text-navy-600' }
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium text-slate-500">{label}</p>
          <p className="mt-1.5 text-2xl font-semibold tabular-nums tracking-tight text-slate-900">{value}</p>
          {hint && <p className="mt-0.5 text-[11px] text-slate-400">{hint}</p>}
        </div>
        <div className={`rounded-lg p-2 ${tones[tone]}`}>{icon}</div>
      </div>
    </Card>
  )
}

export default function Dashboard() {
  const nav = useNavigate()
  const metrics = useQuery({ queryKey: ['metrics'], queryFn: api.metrics, refetchInterval: 6000 })
  const trends = useQuery({ queryKey: ['trends'], queryFn: () => api.trends(14), refetchInterval: 10000 })
  const recent = useQuery({ queryKey: ['invoices', 'recent'], queryFn: () => api.invoices({ page_size: 8 }), refetchInterval: 6000 })

  if (metrics.isLoading) return <PageLoading />
  if (metrics.isError) return <ErrorBox error={metrics.error} onRetry={() => metrics.refetch()} />
  const m = metrics.data!
  const t = trends.data
  const empty = m.total_processed === 0 && m.processing_errors === 0 && m.in_progress === 0
  const inrValue = Number(m.total_value_by_currency.INR ?? 0)
  const otherCur = Object.entries(m.total_value_by_currency).filter(([c]) => c !== 'INR')

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle="Live view of invoices processed by the pipeline. Every number is computed from persisted records."
        actions={<Link to="/process"><Button><UploadCloud className="h-4 w-4" /> Process invoice</Button></Link>}
      />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Kpi label="Invoices processed" value={m.total_processed} icon={<FileCheck2 className="h-5 w-5" />} tone="indigo" hint={m.processing_errors ? `${m.processing_errors} processing error(s)` : undefined} />
        <Kpi label="Approved" value={m.approved} icon={<CheckCircle2 className="h-5 w-5" />} tone="green" />
        <Kpi label="Pending review" value={m.needs_review} icon={<ClipboardCheck className="h-5 w-5" />} tone="amber" />
        <Kpi label="Rejected / blocked" value={m.rejected} icon={<XCircle className="h-5 w-5" />} tone="red" />
        <Kpi label="Automated approval rate" value={m.auto_approval_rate === null ? '—' : `${m.auto_approval_rate}%`} icon={<Percent className="h-5 w-5" />} tone="green" hint="Approved with no human touch" />
        <Kpi label="Avg. processing time" value={seconds(m.avg_processing_seconds)} icon={<Clock className="h-5 w-5" />} tone="indigo" hint="Upload to decision" />
        <Kpi label="Invoice value processed" value={compactMoney(inrValue)} icon={<Banknote className="h-5 w-5" />} tone="slate" hint={otherCur.length ? `+ ${otherCur.map(([c, v]) => money(v, c)).join(', ')}` : 'INR'} />
        <Kpi label="Approved value" value={compactMoney(Number(m.approved_value_by_currency.INR ?? 0))} icon={<Banknote className="h-5 w-5" />} tone="green" hint="INR, ready for payment run" />
      </div>

      {empty ? (
        <Card className="mt-6">
          <EmptyState
            icon={<UploadCloud className="h-6 w-6" />}
            title="No invoices processed yet"
            hint="Upload a PDF or load one of the bundled samples. The charts below fill in from real runs."
            action={<Link to="/process"><Button>Process your first invoice</Button></Link>}
          />
        </Card>
      ) : (
        <div className="mt-6 grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader title="Daily processing volume" subtitle="Last 14 days, by outcome" />
            <CardBody className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={t?.daily.map((d) => ({ ...d, day: d.date.slice(5) }))} margin={{ left: -20 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="day" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                  <Tooltip cursor={{ fill: '#f1f5f9' }} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="APPROVED" name="Approved" stackId="a" fill={C.ok} />
                  <Bar dataKey="NEEDS_REVIEW" name="Needs review" stackId="a" fill={C.warn} />
                  <Bar dataKey="REJECTED" name="Rejected" stackId="a" fill={C.bad} />
                  <Bar dataKey="PROCESSING_ERROR" name="Error" stackId="a" fill={C.err} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Decision distribution" />
            <CardBody className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={t?.distribution.filter((d) => d.value > 0)} dataKey="value" nameKey="name" innerRadius={52} outerRadius={82} paddingAngle={2}>
                    {t?.distribution.filter((d) => d.value > 0).map((d) => (
                      <Cell key={d.name} fill={d.name === 'Approved' ? C.ok : d.name === 'Needs review' ? C.warn : d.name === 'Rejected' ? C.bad : C.err} />
                    ))}
                  </Pie>
                  <Tooltip />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
                </PieChart>
              </ResponsiveContainer>
            </CardBody>
          </Card>
          <Card className="lg:col-span-2">
            <CardHeader title="Vendor-wise invoice volume" subtitle="Top vendors by number of invoices" />
            <CardBody className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={t?.vendors} layout="vertical" margin={{ left: 40, right: 12 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#e2e8f0" />
                  <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                  <YAxis type="category" dataKey="vendor" width={150} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} tickFormatter={(v: string) => (v.length > 22 ? v.slice(0, 21) + '…' : v)} />
                  <Tooltip cursor={{ fill: '#f1f5f9' }} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="approved" name="Approved" stackId="v" fill={C.ok} />
                  <Bar dataKey="review" name="Review" stackId="v" fill={C.warn} />
                  <Bar dataKey="rejected" name="Rejected" stackId="v" fill={C.bad} radius={[0, 3, 3, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Monthly trend" subtitle="Invoices processed" />
            <CardBody className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={t?.monthly} margin={{ left: -20 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="month" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                  <Tooltip />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
                  <Line type="monotone" dataKey="count" name="Processed" stroke={C.brand} strokeWidth={2.5} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="approved" name="Approved" stroke={C.ok} strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </CardBody>
          </Card>
        </div>
      )}

      <Card className="mt-6">
        <CardHeader title="Recent activity" subtitle="Latest invoices through the pipeline" action={<Link to="/invoices" className="text-xs font-medium text-navy-700 hover:underline">View all</Link>} />
        {recent.data && recent.data.items.length > 0 ? (
          <Table>
            <thead><tr><Th>Invoice #</Th><Th>Vendor</Th><Th>PO</Th><Th className="text-right">Amount</Th><Th>Uploaded</Th><Th>Status</Th><Th className="text-right">Duration</Th><Th /></tr></thead>
            <tbody>
              {recent.data.items.map((i) => (
                <tr key={i.id} className="cursor-pointer hover:bg-slate-50" onClick={() => nav(`/invoices/${i.id}`)}>
                  <Td className="font-medium text-slate-900">{i.invoice_number ?? <span className="text-slate-400">—</span>}</Td>
                  <Td>{i.vendor_name ?? '—'}</Td>
                  <Td className="font-mono text-xs">{i.po_number ?? '—'}</Td>
                  <Td className="text-right tabular-nums">{money(i.total_amount, i.currency)}</Td>
                  <Td className="text-slate-500">{dateTime(i.created_at)}</Td>
                  <Td><DecisionBadge decision={i.final_decision} processing={i.processing_status} /></Td>
                  <Td className="text-right tabular-nums text-slate-500">{seconds(i.duration_s)}</Td>
                  <Td className="text-right"><Link to={`/invoices/${i.id}`} className="text-xs font-medium text-navy-700 hover:underline" onClick={(e) => e.stopPropagation()}>View</Link></Td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : (
          <EmptyState title="Nothing here yet" hint="Processed invoices appear here in real time." />
        )}
      </Card>
      <p className="mt-3 text-[11px] text-slate-400">{m.note}</p>
    </>
  )
}
