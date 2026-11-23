import { X } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'

export function Drawer({ open, onClose, title, subtitle, children }: { open: boolean; onClose: () => void; title: ReactNode; subtitle?: ReactNode; children: ReactNode }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-slate-900/40" onClick={onClose} />
      <div className="slide-in absolute inset-y-0 right-0 flex w-full max-w-2xl flex-col bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-6 py-4">
          <div><h2 className="text-base font-semibold text-slate-900">{title}</h2>{subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}</div>
          <button className="cursor-pointer rounded-lg p-1.5 text-slate-500 hover:bg-slate-100" onClick={onClose} aria-label="Close"><X className="h-5 w-5" /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-6">{children}</div>
      </div>
    </div>
  )
}
