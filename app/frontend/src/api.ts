/**
 * Typed API client for inStockCV backend.
 *
 * Endpoints:
 *  - GET  /config/models           — list of available model routes
 *  - POST /analyze (multipart)     — image → structured product info
 *  - POST /lookup  (json)          — analyze result → SKU + quantity
 */

export interface SkuCandidate {
  candidate_name: string
  confidence_score: number
}

export interface AnalyzeResult {
  scan_id: string
  model_route: string
  image_volume_path: string | null
  brand: string | null
  category: string | null
  product_name: string | null
  size: string | null
  flavor: string | null
  top_3_sku_candidates: SkuCandidate[]
}

export interface LookupResult {
  scan_id: string
  matched: boolean
  sku_id: string | null
  product_name: string | null
  brand: string | null
  quantity_on_hand: number | null
  match_score: number
  confidence_label: 'High' | 'Medium' | 'Low'
}

export interface ModelsConfig {
  models: string[]
  default: string
}

async function readError(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body?.detail === 'string') return body.detail
    return JSON.stringify(body)
  } catch {
    return fallback
  }
}

export async function fetchModels(): Promise<ModelsConfig> {
  const res = await fetch('/config/models')
  if (!res.ok) throw new Error(await readError(res, 'Failed to load model list'))
  return res.json()
}

export async function analyzeImage(
  file: File,
  modelRoute: string
): Promise<AnalyzeResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('model_route', modelRoute)
  const res = await fetch('/analyze', { method: 'POST', body: form })
  if (!res.ok) throw new Error(await readError(res, 'Analyze failed'))
  return res.json()
}

export async function lookupSku(analyzeResult: AnalyzeResult): Promise<LookupResult> {
  const res = await fetch('/lookup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(analyzeResult),
  })
  if (!res.ok) throw new Error(await readError(res, 'Lookup failed'))
  return res.json()
}
