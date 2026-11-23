import { expect, test, type Page } from '@playwright/test'

/** Drives the real UI against the real backend. The database is reset first so outcomes are deterministic. */
async function processSample(page: Page, file: string) {
  await page.goto('/process')
  await page.getByTestId(`sample-${file}`).click()
  await expect(page.getByTestId('queue-item').last()).toContainText('Ready', { timeout: 20_000 })
  await page.getByTestId('start-processing').click()
  await expect(page.getByTestId('decision-banner')).toBeVisible({ timeout: 90_000 })
}

test.beforeAll(async ({ request }) => {
  const r = await request.post('/api/admin/reset')
  expect(r.ok()).toBeTruthy()
})

test('happy path: valid invoice is approved with every stage completed', async ({ page }) => {
  await processSample(page, '01_valid_apex.pdf')
  await expect(page.getByTestId('decision-banner')).toHaveAttribute('data-decision', 'APPROVED')
  for (const key of ['pdf_validation', 'text_extraction', 'ai_extraction', 'invoice_validation', 'vendor_verification', 'po_matching', 'duplicate_detection', 'financial_reconciliation', 'decision']) {
    await expect(page.getByTestId(`stage-${key}`)).toHaveAttribute('data-status', /COMPLETED|WARNING/)
  }
})

test('duplicate: the same invoice again is rejected and cites the original', async ({ page }) => {
  await processSample(page, '01_valid_apex.pdf')
  await expect(page.getByTestId('decision-banner')).toHaveAttribute('data-decision', 'REJECTED')
  await expect(page.getByTestId('decision-banner')).toContainText(/already processed|already submitted/i)
})

test('amount mismatch goes to the review queue and cannot be approved past the PO limit', async ({ page }) => {
  await processSample(page, '03_amount_mismatch_delta.pdf')
  await expect(page.getByTestId('decision-banner')).toHaveAttribute('data-decision', 'NEEDS_REVIEW')
  await page.goto('/reviews')
  await expect(page.getByTestId('review-row')).toHaveCount(1)
  await page.getByTestId('review-row').first().click()
  await expect(page.getByTestId('review-panel')).toBeVisible()
  await expect(page.getByTestId('approve-btn')).toBeDisabled() // R09 / R10: hard financial controls
})

test('partial billing consumes the PO balance and the next invoice is held', async ({ page }) => {
  await processSample(page, '04_partial_horizon_inv2.pdf')
  await expect(page.getByTestId('decision-banner')).toContainText('₹25,000.00') // remaining after
  await processSample(page, '04b_partial_horizon_inv3_exceeds.pdf')
  await expect(page.getByTestId('decision-banner')).toHaveAttribute('data-decision', 'NEEDS_REVIEW')
})

test('dashboard and audit trail reflect the runs', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('Invoices processed', { exact: true }).first()).toBeVisible()
  await expect(page.getByTestId('review-badge')).toBeVisible()
  await page.goto('/audit')
  await expect(page.locator('ol li').getByText('Decision generated').first()).toBeVisible()
})
