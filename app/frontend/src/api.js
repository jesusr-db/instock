/**
 * Typed API client for inStockCV backend.
 *
 * Endpoints:
 *  - GET  /config/models           — list of available model routes
 *  - POST /analyze (multipart)     — image → structured product info
 *  - POST /lookup  (json)          — analyze result → SKU + quantity
 */
async function readError(res, fallback) {
    try {
        const body = await res.json();
        if (typeof body?.detail === 'string')
            return body.detail;
        return JSON.stringify(body);
    }
    catch {
        return fallback;
    }
}
export async function fetchModels() {
    const res = await fetch('/config/models');
    if (!res.ok)
        throw new Error(await readError(res, 'Failed to load model list'));
    return res.json();
}
export async function analyzeImage(file, modelRoute) {
    const form = new FormData();
    form.append('file', file);
    form.append('model_route', modelRoute);
    const res = await fetch('/analyze', { method: 'POST', body: form });
    if (!res.ok)
        throw new Error(await readError(res, 'Analyze failed'));
    return res.json();
}
export async function lookupSku(analyzeResult) {
    const res = await fetch('/lookup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(analyzeResult),
    });
    if (!res.ok)
        throw new Error(await readError(res, 'Lookup failed'));
    return res.json();
}
