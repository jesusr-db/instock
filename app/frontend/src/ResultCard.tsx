import React from 'react'
import type { LookupResult, AnalyzeResult } from './api'

interface Props {
  result: LookupResult
  analyzeResult: AnalyzeResult
  imageUrl: string | null
  onReset: () => void
}

function qtyColor(qty: number | null): string {
  if (qty === null) return '#888'
  if (qty === 0) return '#dc2626'
  if (qty < 10) return '#d97706'
  return '#16a34a'
}

const BADGE_COLORS: Record<string, string> = {
  High: '#16a34a',
  Medium: '#d97706',
  Low: '#dc2626',
}

function PipelineSummary({ analyzeResult }: { analyzeResult: AnalyzeResult }) {
  const { detection_stage, detections, model_route } = analyzeResult
  const modelLabel = model_route.replace('databricks-', '')

  const steps: { icon: string; text: string; sub?: string }[] = []

  if (detection_stage === 'yolo') {
    const top = detections?.[0]
    const conf = top ? ` (${Math.round(top.confidence * 100)}% conf)` : ''
    steps.push({ icon: '🎯', text: `YOLO crop${conf}` })
  } else if (detection_stage === 'fallback') {
    steps.push({ icon: '🖼️', text: 'Full image', sub: 'YOLO: no products detected' })
  } else {
    steps.push({ icon: '🖼️', text: 'Full image' })
  }

  steps.push({ icon: '🤖', text: modelLabel })
  steps.push({ icon: '🗄️', text: 'Inventory lookup' })

  return (
    <div style={ps.wrap}>
      <span style={ps.title}>Pipeline</span>
      <div style={ps.row}>
        {steps.map((step, i) => (
          <React.Fragment key={i}>
            <div style={ps.step}>
              <span style={ps.icon}>{step.icon}</span>
              <span style={ps.stepLabel}>{step.text}</span>
              {step.sub && <span style={ps.sub}>{step.sub}</span>}
            </div>
            {i < steps.length - 1 && <span style={ps.arrow}>→</span>}
          </React.Fragment>
        ))}
      </div>
    </div>
  )
}

export default function ResultCard({ result, analyzeResult, imageUrl, onReset }: Props) {
  return (
    <div style={s.card}>
      {imageUrl && (
        <img src={imageUrl} alt="Scanned product" style={s.thumb} />
      )}
      {result.matched ? (
        <>
          <p style={s.productName}>{result.product_name ?? 'Unknown Product'}</p>
          <p style={s.brand}>{result.brand}{result.size ? ` · ${result.size}` : ''}</p>

          <div style={s.row}>
            <span style={s.rowLabel}>SKU</span>
            <span style={s.sku}>{result.sku_id}</span>
          </div>

          <div style={s.row}>
            <span style={s.rowLabel}>In Stock</span>
            <span style={{ ...s.qty, color: qtyColor(result.quantity_on_hand) }}>
              {result.quantity_on_hand ?? '—'}
            </span>
          </div>

          <div style={s.row}>
            <span style={s.rowLabel}>Match</span>
            <span style={{ ...s.badge, background: BADGE_COLORS[result.confidence_label] ?? '#888' }}>
              {result.confidence_label}
            </span>
          </div>
        </>
      ) : (
        <div style={s.noMatch}>
          <div style={{ fontSize: 40 }}>❌</div>
          <p style={{ marginTop: 8, color: '#555', fontSize: 16 }}>
            Product not found in inventory
          </p>
        </div>
      )}

      <PipelineSummary analyzeResult={analyzeResult} />

      <button onClick={onReset} style={s.resetBtn}>
        Scan Another
      </button>
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  card: {
    background: '#fff',
    borderRadius: 16,
    padding: 24,
    boxShadow: '0 2px 12px rgba(0,0,0,0.08)',
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
  },
  productName: { fontSize: 22, fontWeight: 700, color: '#111' },
  brand: { fontSize: 16, color: '#555' },
  row: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  rowLabel: { fontSize: 13, color: '#888', textTransform: 'uppercase', letterSpacing: 0.5 },
  sku: { fontFamily: 'monospace', fontSize: 14, color: '#333' },
  qty: { fontSize: 40, fontWeight: 800, lineHeight: 1 },
  badge: {
    display: 'inline-block',
    padding: '2px 10px',
    borderRadius: 99,
    fontSize: 12,
    fontWeight: 600,
    color: '#fff',
  },
  thumb: {
    width: '100%',
    maxHeight: 180,
    objectFit: 'cover',
    borderRadius: 10,
    border: '1px solid #eee',
  },
  noMatch: { textAlign: 'center', padding: '24px 0' },
  resetBtn: {
    padding: '12px 0',
    borderRadius: 12,
    border: '2px solid #1B3A6B',
    background: 'transparent',
    color: '#1B3A6B',
    fontSize: 15,
    fontWeight: 600,
    cursor: 'pointer',
    width: '100%',
  },
}

const ps: Record<string, React.CSSProperties> = {
  wrap: {
    background: '#f8fafc',
    border: '1px solid #e2e8f0',
    borderRadius: 10,
    padding: '10px 14px',
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  },
  title: { fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.8 },
  row: { display: 'flex', alignItems: 'flex-start', gap: 6, flexWrap: 'wrap' },
  step: { display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 },
  icon: { fontSize: 16 },
  stepLabel: { fontSize: 11, fontWeight: 600, color: '#334155', whiteSpace: 'nowrap' },
  sub: { fontSize: 10, color: '#94a3b8', whiteSpace: 'nowrap' },
  arrow: { fontSize: 12, color: '#cbd5e1', marginTop: 4, alignSelf: 'flex-start', paddingTop: 2 },
}
