export type Decision = 'APPROVED' | 'NEEDS_REVIEW' | 'REJECTED' | 'PROCESSING_ERROR'
export type StageStatus = 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'WARNING' | 'FAILED' | 'SKIPPED'
export type RunStatus = 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED'
export type RuleStatus = 'PASS' | 'FAIL' | 'REVIEW' | 'NOT_APPLICABLE'

export interface Page<T> { items: T[]; total: number; page: number; page_size: number }

export interface InvoiceRow {
  id: number
  invoice_number: string | null
  filename: string | null
  vendor_id: number | null
  vendor_name: string | null
  vendor_verified: boolean
  po_id: number | null
  po_number: string | null
  invoice_date: string | null
  currency: string | null
  total_amount: string | null
  processing_status: string
  final_decision: Decision | null
  decision_reason: string | null
  decision_source: 'AUTO' | 'MANUAL' | null
  review_state: string | null
  severity: string | null
  source: 'UPLOAD' | 'HISTORY'
  created_at: string
  decided_at: string | null
  duration_s: number | null
  run_id: string | null
  duplicate_of_id: number | null
  page_count: number | null
  // review queue extras
  reason?: string | null
  flagged_rules?: string[]
  recommended_next_action?: string | null
}

export interface Stage {
  key: string
  name: string
  order: number
  status: StageStatus
  started_at: string | null
  completed_at: string | null
  duration_ms: number | null
  warnings: string[]
  error: string | null
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data?: any
}

export interface Run {
  run_id: string
  invoice_id: number
  filename: string | null
  kind: 'FULL' | 'REVALIDATION'
  status: RunStatus
  current_stage: string | null
  started_at: string
  completed_at: string | null
  duration_s: number | null
  error_message: string | null
  final_decision: Decision | null
  stages: Stage[]
  invoice_number?: string | null
  vendor_name?: string | null
  total_amount?: string | null
  currency?: string | null
}

export interface Rule {
  rule_id: string
  rule_name: string
  status: RuleStatus
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
  expected: string
  observed: string
  explanation: string
  hard_block: boolean
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  details: Record<string, any>
}

export interface ExtractedLine {
  description: string | null
  sku: string | null
  quantity: string | null
  unit_price: string | null
  tax_rate: string | null
  line_total: string | null
}

export interface Extraction {
  vendor_name: string | null
  vendor_tax_id: string | null
  vendor_address: string | null
  invoice_number: string | null
  invoice_date: string | null
  due_date: string | null
  po_number: string | null
  currency: string | null
  subtotal: string | null
  discount: string | null
  shipping: string | null
  tax_amount: string | null
  grand_total: string | null
  line_items: ExtractedLine[]
  missing_fields: string[]
  warnings: string[]
  evidence: Record<string, { page: number | null; snippet: string | null }>
}

export interface DecisionDetail {
  status: Decision
  main_reason: string
  detailed_reasons: string[]
  explanation?: string
  requires_manual_intervention: boolean
  recommended_next_action: string
  severity?: string
  rules_summary?: Record<RuleStatus, number>
  hard_blocks?: string[]
  flagged_rules?: string[]
  allocation?: { po_number: string; currency: string; invoice_total: string; remaining_before: string; remaining_after: string } | null
  evidence?: { field: string; page: number | null; snippet: string | null }[]
  corrected_data?: boolean
  manual?: { by: string; action: string; justification: string; overridden_rules?: string[] }
}

export interface LineMatch {
  index: number
  description: string | null
  status: string
  po_description: string | null
  score: number
  invoice_qty: string | null
  invoice_unit_price: string | null
  invoice_line_total: string | null
  po_unit_price: string | null
  price_variance_pct: string | null
  po_qty_remaining: string | null
  note: string
}

export interface AuditEvent {
  id: number
  invoice_id: number | null
  invoice_number: string | null
  run_id: string | null
  event_type: string
  actor: string
  timestamp: string
  previous_value: unknown
  new_value: unknown
  reason: string | null
}

export interface POLine {
  id: number
  line_no: number
  item_description: string
  sku: string | null
  quantity: string
  unit_price: string
  tax_rate: string
  authorized_amount: string
  quantity_invoiced?: string
  quantity_remaining?: string
}

export interface PORow {
  id: number
  po_number: string
  vendor_id: number
  vendor_name: string
  currency: string
  issue_date: string
  subtotal: string
  tax_amount: string
  authorized_total: string
  invoiced_amount: string
  remaining_balance: string
  status: 'OPEN' | 'PARTIALLY_INVOICED' | 'FULLY_INVOICED' | 'CLOSED'
  description: string | null
  linked_invoices: number
}

export interface PODetail extends PORow {
  lines: POLine[]
  invoices: InvoiceRow[]
  balance: { authorized_total: string; approved_total: string; remaining: string; cached_remaining: string; reconciled: boolean }
}

export interface VendorRow {
  id: number
  vendor_id: string
  legal_name: string
  aliases: string[]
  tax_id: string | null
  country: string
  approval_status: 'APPROVED' | 'INACTIVE' | 'BLOCKED'
  created_at: string
  purchase_orders: number
  invoices: number
}

export interface VendorDetail extends VendorRow {
  purchase_order_list: PORow[]
  invoice_list: InvoiceRow[]
}

export interface InvoiceDetail extends InvoiceRow {
  extraction: Extraction | null
  extraction_method: string | null
  ocr_confidence: number | null
  extracted_text: string | null
  corrections: { field: string; original: unknown; corrected: unknown; by: string; at: string; reason: string }[]
  file_hash: string | null
  due_date: string | null
  subtotal: string | null
  tax_amount: string | null
  lines: { line_no: number; description: string | null; sku: string | null; quantity: string | null; unit_price: string | null; tax_rate: string | null; line_total: string | null; matched_po_line_id: number | null }[]
  decision: DecisionDetail
  validations: Rule[]
  approval_blockers: Rule[]
  can_approve_manually: boolean
  vendor_match: { status: string; method: string | null; message: string; candidates: { legal_name: string; score: number; basis: string }[]; vendor: { legal_name: string; vendor_id: string; approval_status: string } | null } | null
  po_match: { status: string; message: string; candidates: { po_number: string; score: number }[] } | null
  duplicate: { status: string; kind: string | null; message: string; matches: { invoice_id: number; invoice_number: string; decision: string; reason: string }[] } | null
  line_matching: { lines: LineMatch[]; all_mapped: boolean; expected_subtotal: string | null; expected_tax: string | null; expected_total: string | null } | null
  po: (PORow & { lines: POLine[]; approved_invoices: { id: number; invoice_number: string; total: string }[] }) | null
  runs: Run[]
  audit: AuditEvent[]
  has_file: boolean
}

export interface Metrics {
  total_processed: number
  approved: number
  needs_review: number
  rejected: number
  processing_errors: number
  in_progress: number
  auto_approval_rate: number | null
  avg_processing_seconds: number | null
  total_value_by_currency: Record<string, string>
  approved_value_by_currency: Record<string, string>
  open_reviews: number
  note: string
}

export interface Trends {
  daily: { date: string; APPROVED: number; NEEDS_REVIEW: number; REJECTED: number; PROCESSING_ERROR: number }[]
  monthly: { month: string; count: number; approved: number; value_inr: string }[]
  vendors: { vendor: string; count: number; approved: number; review: number; rejected: number }[]
  distribution: { name: string; value: number }[]
}

export interface SampleItem {
  file: string
  title: string
  run_order: number
  depends_on: string | null
  vendor: string
  invoice_number: string | null
  po_number: string | null
  total: string
  currency: string
  scanned: boolean
  expected: { decision: Decision; note?: string }
}

export interface AppSettings {
  extraction: { provider: string; model: string; configured_keys: Record<string, boolean>; error: string | null; max_retries: number; timeout_s: number }
  ocr: { engine: string; available: boolean; min_chars_per_page: number; low_confidence_threshold: number }
  policy: { tolerance_pct: string; tolerance_abs: string; rounding_tolerance: string; max_invoice_age_days: number }
  limits: { max_upload_mb: number; max_pages: number }
  buyer: { name: string; tax_id: string }
  demo_user: string
  auth_note: string
}
