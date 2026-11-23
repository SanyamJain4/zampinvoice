import { useEffect, useRef, useState } from 'react'
import { api } from '@/services/api'
import type { Run } from '@/types'

const finished = (r: Run) => r.status === 'COMPLETED' || r.status === 'FAILED'

/**
 * Live view of a processing run. Primary transport: Server-Sent Events (real stage transitions pushed by the backend).
 * If the stream cannot be established or drops, it silently falls back to polling GET /api/runs/{id}.
 */
export function useRunStream(runId: string | null | undefined, onDone?: (run: Run) => void) {
  const [run, setRun] = useState<Run | null>(null)
  const [mode, setMode] = useState<'sse' | 'polling' | 'idle'>('idle')
  const doneRef = useRef(onDone)
  doneRef.current = onDone

  useEffect(() => {
    if (!runId) {
      setRun(null)
      setMode('idle')
      return
    }
    let closed = false
    let done = false
    let es: EventSource | null = null
    let timer: ReturnType<typeof setTimeout> | undefined

    const apply = (r: Run) => {
      setRun(r)
      if (finished(r) && !done) {
        done = true
        doneRef.current?.(r)
      }
    }
    const poll = () => {
      setMode('polling')
      const tick = async () => {
        if (closed || done) return
        try {
          apply(await api.run(runId))
        } catch { /* transient: keep polling */ }
        if (!closed && !done) timer = setTimeout(tick, 900)
      }
      tick()
    }

    if (typeof EventSource === 'undefined') {
      poll()
    } else {
      setMode('sse')
      es = new EventSource(api.eventsUrl(runId))
      es.onmessage = (e) => { try { apply(JSON.parse(e.data)) } catch { /* ignore malformed frame */ } }
      es.addEventListener('done', () => { es?.close() })
      es.onerror = () => {
        es?.close()
        if (!closed && !done) poll()
      }
    }
    return () => {
      closed = true
      es?.close()
      if (timer) clearTimeout(timer)
    }
  }, [runId])

  return { run, mode }
}
