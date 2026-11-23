import { describe, expect, it } from 'vitest'
import { compactMoney, decisionLabel, duration, humanize, money } from './format'

describe('format utils', () => {
  it('formats money in Indian grouping with currency symbol', () => {
    expect(money('59000.00', 'INR')).toBe('₹59,000.00')
    expect(money('118000', 'INR')).toBe('₹1,18,000.00')
    expect(money('300.00', 'USD')).toBe('$300.00')
    expect(money(null)).toBe('—')
  })
  it('compacts large INR values', () => {
    expect(compactMoney(250000)).toBe('₹2.50 L')
    expect(compactMoney(12500000)).toBe('₹1.25 Cr')
  })
  it('formats durations', () => {
    expect(duration(420)).toBe('420 ms')
    expect(duration(2450)).toBe('2.45 s')
    expect(duration(null)).toBe('—')
  })
  it('humanizes enums', () => {
    expect(humanize('PARTIALLY_INVOICED')).toBe('Partially invoiced')
    expect(decisionLabel('NEEDS_REVIEW')).toBe('Needs review')
    expect(decisionLabel('PROCESSING_ERROR')).toBe('Processing error')
  })
})
