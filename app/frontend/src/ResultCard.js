import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
function qtyColor(qty) {
    if (qty === null)
        return '#888';
    if (qty === 0)
        return '#dc2626';
    if (qty < 10)
        return '#d97706';
    return '#16a34a';
}
const BADGE_COLORS = {
    High: '#16a34a',
    Medium: '#d97706',
    Low: '#dc2626',
};
export default function ResultCard({ result, onReset }) {
    return (_jsxs("div", { style: s.card, children: [result.matched ? (_jsxs(_Fragment, { children: [_jsx("p", { style: s.productName, children: result.product_name ?? 'Unknown Product' }), _jsx("p", { style: s.brand, children: result.brand }), _jsxs("div", { style: s.row, children: [_jsx("span", { style: s.rowLabel, children: "SKU" }), _jsx("span", { style: s.sku, children: result.sku_id })] }), _jsxs("div", { style: s.row, children: [_jsx("span", { style: s.rowLabel, children: "In Stock" }), _jsx("span", { style: { ...s.qty, color: qtyColor(result.quantity_on_hand) }, children: result.quantity_on_hand ?? '—' })] }), _jsxs("div", { style: s.row, children: [_jsx("span", { style: s.rowLabel, children: "Match" }), _jsx("span", { style: {
                                    ...s.badge,
                                    background: BADGE_COLORS[result.confidence_label] ?? '#888',
                                }, children: result.confidence_label })] })] })) : (_jsxs("div", { style: s.noMatch, children: [_jsx("div", { style: { fontSize: 40 }, children: "\u274C" }), _jsx("p", { style: { marginTop: 8, color: '#555', fontSize: 16 }, children: "Product not found in inventory" })] })), _jsx("button", { onClick: onReset, style: s.resetBtn, children: "Scan Another" })] }));
}
const s = {
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
};
