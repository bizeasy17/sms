function toNullableNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const num = Number(value)
  return Number.isFinite(num) ? num : null
}

export function calculateDisplayReturnPct(
  targetPrice: number | null | undefined,
  latestClose: number | null | undefined,
  fallbackCurrentPrice: number | null | undefined,
  fallbackReturnPct: number | null | undefined
): number | null {
  const latest = toNullableNumber(latestClose)
  const current = latest !== null && latest > 0
    ? latest
    : toNullableNumber(fallbackCurrentPrice)
  const target = toNullableNumber(targetPrice)

  if (current !== null && current > 0 && target !== null) {
    return Number((((target / current) - 1.0) * 100.0).toFixed(2))
  }

  return toNullableNumber(fallbackReturnPct)
}
