/**
 * Typed API client for inStockCV backend.
 *
 * Endpoints:
 *  - GET  /config/models           — list of available model routes
 *  - POST /detect  (multipart)     — image → YOLO bbox list (no VLM)
 *  - POST /analyze (multipart)     — image → structured product info
 *  - POST /lookup  (json)          — analyze result → SKU + quantity
 */

export interface SkuCandidate {
  candidate_name: string
  confidence_score: number
}

export interface Detection {
  crop_index: number
  bbox: [number, number, number, number]
  confidence: number
}

export interface AnalyzeResult {
  scan_id: string
  model_route: string
  image_volume_path: string | null
  detection_stage: 'yolo' | 'fallback' | 'disabled' | 'user-crop'
  detections?: Detection[]
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
  size: string | null
  quantity_on_hand: number | null
  match_score: number
  confidence_label: 'High' | 'Medium' | 'Low'
}

export interface ModelsConfig {
  models: string[]
  default: string
}

export type DetectCrop = Detection

export interface DetectResult {
  crops: DetectCrop[]
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

export async function detectCrops(file: File): Promise<DetectResult> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch('/detect', { method: 'POST', body: form })
  if (!res.ok) throw new Error(await readError(res, 'Detection failed'))
  return res.json()
}

export async function analyzeImage(
  file: File,
  modelRoute: string,
  cropCoords?: [number, number, number, number]
): Promise<AnalyzeResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('model_route', modelRoute)
  if (cropCoords) {
    form.append('crop_x1', String(cropCoords[0]))
    form.append('crop_y1', String(cropCoords[1]))
    form.append('crop_x2', String(cropCoords[2]))
    form.append('crop_y2', String(cropCoords[3]))
  }
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
