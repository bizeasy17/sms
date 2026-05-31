import { describe, expect, it } from 'vitest'
import { calculateDisplayReturnPct } from './valuationDisplay'

describe('calculateDisplayReturnPct', () => {
  it('uses latest close as primary basis', () => {
    const result = calculateDisplayReturnPct(120, 100, 80, 5)
    expect(result).toBe(20)
  })

  it('falls back to current price when latest close is unavailable', () => {
    const result = calculateDisplayReturnPct(120, null, 80, 5)
    expect(result).toBe(50)
  })

  it('falls back to backend return when price basis is unavailable', () => {
    const result = calculateDisplayReturnPct(120, null, null, 7.25)
    expect(result).toBe(7.25)
  })
})
