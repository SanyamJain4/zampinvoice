import { useState } from 'react'
import { ChevronLeft, ChevronRight, ExternalLink, Minus, Plus } from 'lucide-react'
import { Button, Spinner } from '@/components/ui'
import { api } from '@/services/api'

/** Server-rendered page images: page navigation + zoom, no client PDF library needed. */
export function PdfViewer({ invoiceId, pages }: { invoiceId: number; pages: number | null }) {
  const [page, setPage] = useState(1)
  const [zoom, setZoom] = useState(1.5)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const total = pages ?? 1
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-3 py-2">
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" aria-label="Previous page" disabled={page <= 1} onClick={() => { setPage(page - 1); setLoading(true) }}><ChevronLeft className="h-4 w-4" /></Button>
          <span className="min-w-16 text-center text-xs tabular-nums text-slate-600">Page {page} / {total}</span>
          <Button variant="ghost" size="icon" aria-label="Next page" disabled={page >= total} onClick={() => { setPage(page + 1); setLoading(true) }}><ChevronRight className="h-4 w-4" /></Button>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" aria-label="Zoom out" disabled={zoom <= 0.8} onClick={() => { setZoom(+(zoom - 0.3).toFixed(1)); setLoading(true) }}><Minus className="h-4 w-4" /></Button>
          <span className="w-10 text-center text-xs tabular-nums text-slate-600">{Math.round((zoom / 1.5) * 100)}%</span>
          <Button variant="ghost" size="icon" aria-label="Zoom in" disabled={zoom >= 3} onClick={() => { setZoom(+(zoom + 0.3).toFixed(1)); setLoading(true) }}><Plus className="h-4 w-4" /></Button>
          <a href={api.fileUrl(invoiceId)} target="_blank" rel="noreferrer" className="ml-1 inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-100" aria-label="Open original PDF"><ExternalLink className="h-4 w-4" /></a>
        </div>
      </div>
      <div className="relative min-h-[420px] flex-1 overflow-auto bg-slate-100 p-3">
        {loading && !failed && <div className="absolute inset-0 flex items-center justify-center"><Spinner /></div>}
        {failed ? (
          <p className="p-6 text-center text-sm text-slate-500">The original PDF preview is not available.</p>
        ) : (
          <img
            key={`${page}-${zoom}`}
            src={api.pageUrl(invoiceId, page, zoom)}
            alt={`Invoice page ${page}`}
            className="mx-auto max-w-none rounded border border-slate-200 bg-white shadow-sm"
            style={{ width: `${(zoom / 1.5) * 100}%`, minWidth: 320 }}
            onLoad={() => setLoading(false)}
            onError={() => { setFailed(true); setLoading(false) }}
          />
        )}
      </div>
    </div>
  )
}
