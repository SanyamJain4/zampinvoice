import type {
  AppSettings, AuditEvent, InvoiceDetail, InvoiceRow, Metrics, Page, PODetail, PORow, Run, SampleItem, Trends, VendorDetail, VendorRow,
} from '@/types'

/**
 * Base URL of the backend. Empty (default) = same origin, e.g. the Vite dev proxy or the API serving the built UI.
 * For a split deployment (frontend on Vercel, API elsewhere) set VITE_API_URL at BUILD time, e.g. https://invoiceiq-api.onrender.com
 */
export const API_URL: string = ((import.meta.env.VITE_API_URL as string | undefined) ?? '').replace(/\/+$/, '')

export class ApiError extends Error {
  status: number
  blocking: { rule_id: string; rule_name: string; explanation: string }[]
  constructor(message: string, status: number, blocking: ApiError['blocking'] = []) {
    super(message)
    this.status = status
    this.blocking = blocking
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_URL}/api${path}`, init)
  } catch {
    throw new ApiError('Cannot reach the InvoiceIQ server. Is the backend running?', 0)
  }
  if (!res.ok) {
    let message = `Request failed (${res.status})`
    let blocking: ApiError['blocking'] = []
    try {
      const body = await res.json()
      message = body.message || body.detail?.message || message
      blocking = body.blocking_controls || body.detail?.blocking_controls || []
      if (body.fields?.length) message += ' ' + body.fields.map((f: { field: string; problem: string }) => `${f.field}: ${f.problem}`).join('; ')
    } catch { /* non-JSON error */ }
    throw new ApiError(message, res.status, blocking)
  }
  return res.json() as Promise<T>
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
})

const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const u = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') u.set(k, String(v)) })
  const s = u.toString()
  return s ? `?${s}` : ''
}

export const api = {
  health: () => request<{ status: string; ocr_available: boolean; extraction_provider: string; extraction_model: string }>('/health'),
  settings: () => request<AppSettings>('/settings'),
  metrics: () => request<Metrics>('/dashboard/metrics'),
  trends: (days = 14) => request<Trends>(`/dashboard/trends${qs({ days })}`),

  invoices: (p: { page?: number; page_size?: number; decision?: string; search?: string; include_history?: boolean; po_id?: number; vendor_id?: number } = {}) =>
    request<Page<InvoiceRow>>(`/invoices${qs(p)}`),
  invoice: (id: number | string) => request<InvoiceDetail>(`/invoices/${id}`),
  upload: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<InvoiceRow>('/invoices/upload', { method: 'POST', body: fd })
  },
  process: (id: number, force = false) =>
    request<{ run_id: string; already_processed?: boolean; already_running?: boolean; message?: string }>(`/invoices/${id}/process`, json('POST', { force })),
  correct: (id: number, corrections: Record<string, unknown>, reason: string, reviewer?: string) =>
    request<{ run_id: string }>(`/invoices/${id}/extraction`, json('PATCH', { corrections, reason, reviewer })),
  review: (id: number, action: 'APPROVE' | 'REJECT' | 'REQUEST_CLARIFICATION', justification: string, reviewer?: string) =>
    request<InvoiceDetail>(`/invoices/${id}/review`, json('POST', { action, justification, reviewer })),
  pageUrl: (id: number, page: number, zoom: number) => `${API_URL}/api/invoices/${id}/pages/${page}.png?zoom=${zoom}`,
  fileUrl: (id: number) => `${API_URL}/api/invoices/${id}/file`,

  runs: (p: { page?: number; page_size?: number; status?: string } = {}) => request<Page<Run>>(`/runs${qs(p)}`),
  run: (runId: string) => request<Run>(`/runs/${runId}`),
  eventsUrl: (runId: string) => `${API_URL}/api/runs/${runId}/events`,

  reviews: (include_resolved = false) => request<{ items: InvoiceRow[]; total: number }>(`/reviews${qs({ include_resolved })}`),
  purchaseOrders: (p: { search?: string; status?: string } = {}) => request<{ items: PORow[] }>(`/purchase-orders${qs(p)}`),
  purchaseOrder: (id: number) => request<PODetail>(`/purchase-orders/${id}`),
  vendors: (p: { search?: string; status?: string } = {}) => request<{ items: VendorRow[] }>(`/vendors${qs(p)}`),
  vendor: (id: number) => request<VendorDetail>(`/vendors/${id}`),
  audit: (p: { page?: number; page_size?: number; invoice_id?: number; event_type?: string } = {}) =>
    request<Page<AuditEvent> & { event_types: string[] }>(`/audit${qs(p)}`),

  samples: () => request<{ generated_on: string | null; items: SampleItem[] }>('/samples'),
  loadSample: (file: string) => request<InvoiceRow>(`/samples/${encodeURIComponent(file)}/load`, { method: 'POST' }),
  reset: () => request<{ message: string }>('/admin/reset', { method: 'POST' }),
}
