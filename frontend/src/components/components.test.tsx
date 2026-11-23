import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { DecisionBanner } from './DecisionBanner'
import { PipelineTimeline } from './PipelineTimeline'
import { DecisionBadge, RuleBadge } from './StatusBadge'
import type { Run } from '@/types'

const stage = (key: string, name: string, status: Run['stages'][number]['status'], extra: Partial<Run['stages'][number]> = {}) => ({
  key, name, order: 1, status, started_at: null, completed_at: null, duration_ms: null, warnings: [], error: null, ...extra,
})

describe('DecisionBanner', () => {
  it('shows the reason, allocation and next action for an approval', () => {
    render(
      <DecisionBanner
        decision={{
          status: 'APPROVED', main_reason: 'All 12 applicable checks passed.', recommended_next_action: 'Ready for the payment run.',
          allocation: { po_number: 'PO-500', currency: 'INR', invoice_total: '35000.00', remaining_before: '60000.00', remaining_after: '25000.00' },
        }}
      />,
    )
    expect(screen.getByText('Approved')).toBeInTheDocument()
    expect(screen.getByText(/All 12 applicable checks passed/)).toBeInTheDocument()
    expect(screen.getByText('₹25,000.00')).toBeInTheDocument()
    expect(screen.getByTestId('decision-banner')).toHaveAttribute('data-decision', 'APPROVED')
  })

  it('distinguishes a processing error from a rejection', () => {
    render(<DecisionBanner decision={{ status: 'PROCESSING_ERROR' }} error="The PDF appears to be corrupted." />)
    expect(screen.getByText('Processing error')).toBeInTheDocument()
    expect(screen.getByText('Not a business rejection')).toBeInTheDocument()
    expect(screen.getByText('The PDF appears to be corrupted.')).toBeInTheDocument()
  })
})

describe('badges', () => {
  it('maps decisions and rule statuses to labels', () => {
    render(<><DecisionBadge decision="NEEDS_REVIEW" /><DecisionBadge decision="REJECTED" /><RuleBadge status="PASS" /><RuleBadge status="NOT_APPLICABLE" /></>)
    expect(screen.getByText('Needs review')).toBeInTheDocument()
    expect(screen.getByText('Rejected')).toBeInTheDocument()
    expect(screen.getByText('Pass')).toBeInTheDocument()
    expect(screen.getByText('N/A')).toBeInTheDocument()
  })
})

describe('PipelineTimeline', () => {
  it('renders each stage with its real status and progress', () => {
    const run: Run = {
      run_id: 'r1', invoice_id: 1, filename: 'a.pdf', kind: 'FULL', status: 'RUNNING', current_stage: 'text_extraction',
      started_at: '2026-11-23T10:00:00Z', completed_at: null, duration_s: null, error_message: null, final_decision: null,
      stages: [
        stage('pdf_validation', 'PDF Validation', 'COMPLETED', { duration_ms: 12, data: { pages: 1, size_kb: 20, sha256: 'abcdef0123456789', encrypted: false } }),
        stage('text_extraction', 'Text Extraction', 'RUNNING'),
        stage('ai_extraction', 'AI Field Extraction', 'QUEUED'),
      ],
    }
    render(<MemoryRouter><PipelineTimeline run={run} /></MemoryRouter>)
    expect(screen.getByTestId('stage-pdf_validation')).toHaveAttribute('data-status', 'COMPLETED')
    expect(screen.getByTestId('stage-text_extraction')).toHaveAttribute('data-status', 'RUNNING')
    expect(screen.getByTestId('stage-ai_extraction')).toHaveAttribute('data-status', 'QUEUED')
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '33')
  })
})
