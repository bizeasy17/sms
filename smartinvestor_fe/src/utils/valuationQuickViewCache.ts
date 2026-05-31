import axios from 'axios'

const valuationMethodsCache = new Map<string, any>()
const valuationMethodsPending = new Map<string, Promise<any>>()

function buildValuationCacheKey(tsCode: string, band: string, reportType: string, preferredVariant = '') {
  const schemaVersion = 'v3-market-overall-valuation-history'
  return `${schemaVersion}|${String(tsCode || '').trim().toUpperCase()}|${String(band || '').trim()}|${String(reportType || '').trim().toUpperCase()}|${String(preferredVariant || '').trim().toLowerCase()}`
}

export async function fetchValuationMethodsWithSharedCache(
  baseURL: string,
  tsCode: string,
  band: string,
  reportType: string,
  preferredVariant = '',
) {
  const normalizedBaseURL = String(baseURL || '').trim()
  const normalizedTsCode = String(tsCode || '').trim().toUpperCase()
  if (!normalizedBaseURL || !normalizedTsCode) {
    return null
  }

  const key = buildValuationCacheKey(normalizedTsCode, band, reportType, preferredVariant)
  if (valuationMethodsCache.has(key)) {
    return valuationMethodsCache.get(key)
  }
  const pending = valuationMethodsPending.get(key)
  if (pending) {
    return pending
  }

  const reportTypeQuery = reportType
    ? `&earnings_report_type=${encodeURIComponent(reportType)}`
    : ''
  const variantQuery = String(preferredVariant || '').trim()
    ? `&valuation_variant=${encodeURIComponent(String(preferredVariant || '').trim())}`
    : ''
  const url = `${normalizedBaseURL}/stocks/${encodeURIComponent(normalizedTsCode)}/valuation/methods/?freq=D&valuation_band_pct=${band}${reportTypeQuery}${variantQuery}`
  const task = axios.get(url)
    .then((res) => {
      const payload = res?.data
      if (payload && typeof payload === 'object') {
        valuationMethodsCache.set(key, payload)
      }
      return payload
    })
    .finally(() => {
      valuationMethodsPending.delete(key)
    })

  valuationMethodsPending.set(key, task)
  return task
}

export function prefetchValuationMethodsWithSharedCache(
  baseURL: string,
  tsCode: string,
  band = '0.1',
  reportType = '',
  preferredVariant = '',
) {
  void fetchValuationMethodsWithSharedCache(baseURL, tsCode, band, reportType, preferredVariant).catch(() => null)
}
