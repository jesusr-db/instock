import React from 'react'
import type { LookupResult } from './api'

interface Props {
  result: LookupResult
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

export default function ResultCard({ result, onReset }: Props) {
  return (
    <div style={s.card}>
      {result.matched ? (
        <>
          <p style={s.productName}>{result.product_name ?? 'Unknown Product'}</p>
          <p style={s.brand}>{result.brand}</p>

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
            <span
              style={{
                ...s.badge,
                background: BADGE_COLORS[result.confidence_label] ?? '#888',
              }}
            >
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
  rowLabel: {
    fontSize: 13,
    color: '#888',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
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
