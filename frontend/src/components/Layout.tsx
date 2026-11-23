import { useQuery } from '@tanstack/react-query'
import { Boxes, ClipboardCheck, FileSearch, FileText, History, LayoutDashboard, Menu, ScrollText, Settings, ShieldCheck, Store, UploadCloud, X } from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { Badge } from '@/components/ui'
import { api } from '@/services/api'
import { cn } from '@/utils/format'

const nav = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/process', label: 'Process Invoice', icon: UploadCloud },
  { to: '/invoices', label: 'All Invoices', icon: FileText },
  { to: '/reviews', label: 'Review Queue', icon: ClipboardCheck, badge: true },
  { to: '/purchase-orders', label: 'Purchase Orders', icon: Boxes },
  { to: '/vendors', label: 'Vendor Management', icon: Store },
  { to: '/history', label: 'Processing History', icon: History },
  { to: '/audit', label: 'Audit Trail', icon: ScrollText },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function Layout() {
  const [open, setOpen] = useState(false)
  const metrics = useQuery({ queryKey: ['metrics'], queryFn: api.metrics, refetchInterval: 8000 })
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 20000, retry: false })
  const pending = metrics.data?.open_reviews ?? 0
  const offline = health.isError

  const sidebar = (
    <div className="flex h-full flex-col bg-navy-950 text-slate-300">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/10 ring-1 ring-white/20"><FileSearch className="h-5 w-5 text-white" /></div>
        <div>
          <p className="text-[15px] font-semibold leading-tight text-white">InvoiceIQ</p>
          <p className="text-[11px] leading-tight text-slate-400">AP Automation</p>
        </div>
      </div>
      <nav className="flex-1 space-y-0.5 px-3 py-2" aria-label="Main">
        {nav.map(({ to, label, icon: Icon, end, badge }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            onClick={() => setOpen(false)}
            className={({ isActive }) => cn('group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors', isActive ? 'bg-white/10 text-white' : 'hover:bg-white/5 hover:text-white')}
          >
            <Icon className="h-[18px] w-[18px] shrink-0 opacity-80" />
            <span className="flex-1">{label}</span>
            {badge && pending > 0 && <span className="rounded-full bg-warn-600 px-1.5 py-0.5 text-[10px] font-semibold text-white" data-testid="review-badge">{pending}</span>}
          </NavLink>
        ))}
      </nav>
      <div className="m-3 rounded-lg bg-white/5 p-3 text-[11px] leading-relaxed text-slate-400">
        <p className="flex items-center gap-1.5 font-medium text-slate-200"><ShieldCheck className="h-3.5 w-3.5" /> Decisions only</p>
        This system never executes payments. AI extracts; deterministic rules decide; humans own uncertain cases.
      </div>
    </div>
  )

  return (
    <div className="flex h-full">
      <aside className="hidden w-64 shrink-0 lg:block">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/50" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-64 shadow-xl">{sidebar}</div>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 lg:px-8">
          <button className="cursor-pointer rounded-lg p-1.5 text-slate-600 hover:bg-slate-100 lg:hidden" onClick={() => setOpen(!open)} aria-label="Toggle navigation">
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
          <div className="flex-1" />
          <div className="flex items-center gap-2 text-xs">
            {offline ? (
              <Badge tone="red">Backend offline</Badge>
            ) : health.data ? (
              <>
                <Badge tone={health.data.extraction_provider === 'heuristic' ? 'amber' : 'green'} title="How invoice fields are extracted">
                  {health.data.extraction_provider === 'heuristic' ? 'Extraction: offline parser' : `Extraction: ${health.data.extraction_provider}`}
                </Badge>
                <Badge tone={health.data.ocr_available ? 'indigo' : 'slate'}>OCR {health.data.ocr_available ? 'ready' : 'unavailable'}</Badge>
              </>
            ) : null}
            <span className="ml-2 hidden rounded-full bg-navy-50 px-2.5 py-1 font-medium text-navy-700 sm:inline">Demo reviewer</span>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1280px] px-4 py-6 lg:px-8"><Outlet /></div>
        </main>
      </div>
    </div>
  )
}
