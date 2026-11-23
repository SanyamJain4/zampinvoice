import { useQueryClient } from '@tanstack/react-query'
import { useQuery } from '@tanstack/react-query'
import { AlertCircle, CheckCircle2, Eye, FileText, FlaskConical, Loader2, Play, Radio, Trash2, UploadCloud } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { DecisionBanner } from '@/components/DecisionBanner'
import { PipelineTimeline } from '@/components/PipelineTimeline'
import { DecisionBadge } from '@/components/StatusBadge'
import { Badge, Button, Card, CardBody, CardHeader, EmptyState, PageHeader } from '@/components/ui'
import { useRunStream } from '@/hooks/useRunStream'
import { api } from '@/services/api'
import type { Run, SampleItem } from '@/types'
import { cn } from '@/utils/format'

const MAX_MB = 15

type Phase = 'ready' | 'uploading' | 'processing' | 'done' | 'error'
interface Item {
  key: string
  name: string
  size: number
  file?: File
  sample?: SampleItem
  blobUrl?: string
  invoiceId?: number
  runId?: string
  phase: Phase
  error?: string
}

let seq = 0

export default function ProcessInvoice() {
  const qc = useQueryClient()
  const [items, setItems] = useState<Item[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [runs, setRuns] = useState<Record<string, Run>>({})
  const [dragging, setDragging] = useState(false)
  const [view, setView] = useState<'preview' | 'live'>('preview')
  const inputRef = useRef<HTMLInputElement>(null)
  const samples = useQuery({ queryKey: ['samples'], queryFn: api.samples })

  const patch = useCallback((key: string, p: Partial<Item>) => setItems((cur) => cur.map((i) => (i.key === key ? { ...i, ...p } : i))), [])

  const addFiles = (files: FileList | File[]) => {
    const next: Item[] = []
    Array.from(files).forEach((f) => {
      const key = `f${++seq}`
      const isPdf = f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf')
      let error: string | undefined
      if (!isPdf) error = 'Only PDF files are supported.'
      else if (f.size > MAX_MB * 1024 * 1024) error = `File is larger than ${MAX_MB} MB.`
      else if (f.size === 0) error = 'File is empty.'
      next.push({ key, name: f.name, size: f.size, file: f, phase: error ? 'error' : 'ready', error, blobUrl: error ? undefined : URL.createObjectURL(f) })
    })
    setItems((cur) => [...cur, ...next])
    if (next.length) { setSelected((s) => s ?? next[0].key); setView('preview') }
  }

  const addSample = async (s: SampleItem) => {
    const key = `s${++seq}`
    setItems((cur) => [...cur, { key, name: s.file, size: 0, sample: s, phase: 'uploading' }])
    setSelected(key)
    setView('preview')
    try {
      const inv = await api.loadSample(s.file)
      patch(key, { invoiceId: inv.id, phase: 'ready', blobUrl: api.fileUrl(inv.id) })
    } catch (e) {
      patch(key, { phase: 'error', error: e instanceof Error ? e.message : 'Could not load the sample.' })
    }
  }

  const startOne = async (it: Item) => {
    try {
      let id = it.invoiceId
      if (!id && it.file) {
        patch(it.key, { phase: 'uploading', error: undefined })
        id = (await api.upload(it.file)).id
        patch(it.key, { invoiceId: id })
      }
      if (!id) return
      const r = await api.process(id)
      patch(it.key, { phase: 'processing', runId: r.run_id, invoiceId: id })
      qc.invalidateQueries({ queryKey: ['invoices'] })
    } catch (e) {
      patch(it.key, { phase: 'error', error: e instanceof Error ? e.message : 'Processing could not be started.' })
    }
  }

  const startAll = async () => {
    const ready = items.filter((i) => i.phase === 'ready')
    if (!ready.length) return
    setView('live')
    if (!selected || !ready.find((r) => r.key === selected)) setSelected(ready[0].key)
    await Promise.all(ready.map(startOne))
  }

  const remove = (key: string) => {
    setItems((cur) => cur.filter((i) => i.key !== key))
    setSelected((s) => (s === key ? null : s))
  }

  useEffect(() => () => items.forEach((i) => i.file && i.blobUrl && URL.revokeObjectURL(i.blobUrl)), []) // eslint-disable-line react-hooks/exhaustive-deps

  const current = items.find((i) => i.key === selected) ?? null
  const currentRun = current?.runId ? runs[current.runId] : undefined
  const readyCount = items.filter((i) => i.phase === 'ready').length
  const busy = items.some((i) => i.phase === 'uploading' || i.phase === 'processing')

  return (
    <>
      <PageHeader title="Process invoice" subtitle="Drop one or many invoice PDFs. Each stage you see below is real backend work, streamed as it happens." />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        {/* ---------------- left: input + queue ---------------- */}
        <div className="space-y-4">
          <Card>
            <CardBody>
              <div
                onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files) }}
                onClick={() => inputRef.current?.click()}
                role="button"
                tabIndex={0}
                aria-label="Upload invoice PDFs"
                onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
                className={cn('flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors', dragging ? 'border-navy-500 bg-navy-50' : 'border-slate-300 bg-slate-50/60 hover:border-navy-500 hover:bg-navy-50/50')}
                data-testid="dropzone"
              >
                <div className="mb-3 rounded-full bg-navy-50 p-3 text-navy-600"><UploadCloud className="h-7 w-7" /></div>
                <p className="text-sm font-medium text-slate-900">Drag & drop invoice PDFs here</p>
                <p className="mt-1 text-xs text-slate-500">or <span className="font-medium text-navy-700 underline">browse files</span> · PDF only · up to {MAX_MB} MB each · batch supported</p>
                <input ref={inputRef} type="file" accept="application/pdf,.pdf" multiple className="hidden" data-testid="file-input" onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = '' }} />
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title={`Queue ${items.length ? `(${items.length})` : ''}`}
              action={<Button onClick={startAll} disabled={!readyCount || busy} loading={busy && !readyCount} data-testid="start-processing"><Play className="h-4 w-4" /> Start processing{readyCount > 1 ? ` (${readyCount})` : ''}</Button>}
            />
            {items.length === 0 ? (
              <EmptyState icon={<FileText className="h-5 w-5" />} title="No files yet" hint="Add PDFs above, or pick a bundled sample on the right." />
            ) : (
              <ul className="divide-y divide-slate-100">
                {items.map((it) => (
                  <QueueRow key={it.key} item={it} active={selected === it.key} onSelect={() => { setSelected(it.key); setView(it.runId ? 'live' : 'preview') }} onRemove={() => remove(it.key)}
                    onRun={(r) => setRuns((cur) => ({ ...cur, [r.run_id]: r }))}
                    onDone={() => { patch(it.key, { phase: 'done' }); ['metrics', 'trends', 'invoices', 'reviews', 'runs', 'purchase-orders'].forEach((k) => qc.invalidateQueries({ queryKey: [k] })) }} />
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <CardHeader title="Bundled samples" subtitle="Synthetic invoices that exercise each scenario. They go through exactly the same pipeline as an upload." action={<FlaskConical className="h-4 w-4 text-slate-400" />} />
            <ul className="max-h-[420px] divide-y divide-slate-100 overflow-y-auto">
              {samples.data?.items.map((s) => (
                <li key={s.file} className="flex items-center gap-3 px-5 py-2.5">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-slate-800">{s.title}</p>
                    <p className="truncate text-[11px] text-slate-500">{s.vendor}{s.scanned ? ' · scanned' : ''}{s.depends_on ? ' · run after #04' : ''}</p>
                  </div>
                  <Button variant="secondary" size="sm" onClick={() => addSample(s)} data-testid={`sample-${s.file}`}>Add</Button>
                </li>
              ))}
              {samples.isLoading && <li className="px-5 py-4 text-xs text-slate-500">Loading samples…</li>}
              {samples.data?.items.length === 0 && <li className="px-5 py-4 text-xs text-slate-500">No sample PDFs found. Run scripts/generate_sample_data.py.</li>}
            </ul>
          </Card>
        </div>

        {/* ---------------- right: preview / live run ---------------- */}
        <div className="space-y-4">
          <Card className="min-h-[520px]">
            <CardHeader
              title={current ? current.name : 'Live execution'}
              subtitle={current ? (currentRun ? `Run ${currentRun.run_id.slice(0, 8)} · ${currentRun.kind.toLowerCase()}` : 'Not started') : 'Select a file to preview it or follow its run'}
              action={current && (
                <div className="flex rounded-lg border border-slate-200 p-0.5 text-xs">
                  <button className={cn('flex cursor-pointer items-center gap-1 rounded-md px-2.5 py-1', view === 'preview' ? 'bg-navy-50 font-medium text-navy-700' : 'text-slate-500')} onClick={() => setView('preview')}><Eye className="h-3 w-3" /> Preview</button>
                  <button className={cn('flex cursor-pointer items-center gap-1 rounded-md px-2.5 py-1', view === 'live' ? 'bg-navy-50 font-medium text-navy-700' : 'text-slate-500')} onClick={() => setView('live')}><Radio className="h-3 w-3" /> Live run</button>
                </div>
              )}
            />
            {!current ? (
              <EmptyState icon={<Radio className="h-6 w-6" />} title="Nothing running" hint="Add an invoice and press Start processing. You’ll see each stage execute: PDF validation, text extraction, AI extraction, rules, matching and the final decision." />
            ) : view === 'preview' || !currentRun ? (
              current.blobUrl ? (
                <iframe title="PDF preview" src={current.blobUrl} className="h-[640px] w-full rounded-b-xl" />
              ) : (
                <EmptyState title={current.error ?? 'Preparing preview…'} />
              )
            ) : (
              <CardBody>
                {currentRun.status === 'COMPLETED' && currentRun.final_decision && <LiveDecision invoiceId={current.invoiceId!} />}
                {currentRun.status === 'FAILED' && (
                  <div className="mb-4"><DecisionBanner decision={{ status: 'PROCESSING_ERROR' }} error={currentRun.error_message} /></div>
                )}
                <PipelineTimeline run={currentRun} defaultOpenKey="decision" />
              </CardBody>
            )}
          </Card>
        </div>
      </div>
    </>
  )
}

function LiveDecision({ invoiceId }: { invoiceId: number }) {
  const q = useQuery({ queryKey: ['invoice', invoiceId], queryFn: () => api.invoice(invoiceId) })
  if (!q.data) return null
  return (
    <div className="mb-5 space-y-2">
      <DecisionBanner decision={q.data.decision} source={q.data.decision_source} />
      <div className="flex justify-end"><Link to={`/invoices/${invoiceId}`}><Button variant="secondary" size="sm">Open full result</Button></Link></div>
    </div>
  )
}

function QueueRow({ item, active, onSelect, onRemove, onRun, onDone }: { item: Item; active: boolean; onSelect: () => void; onRemove: () => void; onRun: (r: Run) => void; onDone: () => void }) {
  const { run, mode } = useRunStream(item.runId, () => onDone())
  useEffect(() => { if (run) onRun(run) }, [run]) // eslint-disable-line react-hooks/exhaustive-deps
  const done = run?.stages.filter((s) => ['COMPLETED', 'WARNING', 'SKIPPED'].includes(s.status)).length ?? 0
  const total = run?.stages.length ?? 9
  const dec = run?.status === 'FAILED' ? 'PROCESSING_ERROR' : run?.final_decision
  return (
    <li className={cn('flex cursor-pointer items-center gap-3 px-5 py-3 hover:bg-slate-50', active && 'bg-navy-50/50')} onClick={onSelect} data-testid="queue-item">
      <div className="shrink-0">
        {item.phase === 'error' ? <AlertCircle className="h-5 w-5 text-bad-600" /> : item.phase === 'done' ? <CheckCircle2 className="h-5 w-5 text-ok-600" /> : item.phase === 'ready' ? <FileText className="h-5 w-5 text-slate-400" /> : <Loader2 className="h-5 w-5 animate-spin text-navy-600" />}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-slate-800">{item.name}</p>
        {item.phase === 'error' ? (
          <p className="truncate text-xs text-bad-600">{item.error}</p>
        ) : item.phase === 'processing' || item.phase === 'done' ? (
          <div className="mt-1 flex items-center gap-2">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100"><div className={cn('h-full rounded-full transition-all', run?.status === 'FAILED' ? 'bg-bad-600' : 'bg-navy-600')} style={{ width: `${(done / total) * 100}%` }} /></div>
            <span className="text-[11px] tabular-nums text-slate-500">{done}/{total}</span>
            {mode === 'polling' && <Badge tone="slate">polling</Badge>}
          </div>
        ) : (
          <p className="text-xs text-slate-500">{item.phase === 'uploading' ? 'Uploading…' : item.size ? `${(item.size / 1024).toFixed(0)} KB · ready` : 'Ready'}</p>
        )}
      </div>
      {item.phase === 'done' && <DecisionBadge decision={dec} />}
      {(item.phase === 'ready' || item.phase === 'error') && (
        <button className="cursor-pointer rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-bad-600" aria-label={`Remove ${item.name}`} onClick={(e) => { e.stopPropagation(); onRemove() }}><Trash2 className="h-4 w-4" /></button>
      )}
    </li>
  )
}
