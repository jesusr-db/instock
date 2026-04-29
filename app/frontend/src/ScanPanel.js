import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useRef, useState } from 'react';
export default function ScanPanel({ onSubmit, isLoading, models, selectedModel, onModelChange, }) {
    const [preview, setPreview] = useState(null);
    const [file, setFile] = useState(null);
    const inputRef = useRef(null);
    function handleFileChange(e) {
        const f = e.target.files?.[0];
        if (!f)
            return;
        setFile(f);
        setPreview(URL.createObjectURL(f));
    }
    return (_jsxs("div", { style: s.panel, children: [_jsxs("div", { style: s.uploadArea, onClick: () => inputRef.current?.click(), children: [preview ? (_jsx("img", { src: preview, alt: "Preview", style: s.preview })) : (_jsxs("div", { style: s.placeholder, children: [_jsx("div", { style: s.cameraIcon, children: "\uD83D\uDCF7" }), _jsx("p", { style: s.hint, children: "Tap to take a photo or select image" })] })), _jsx("input", { ref: inputRef, type: "file", accept: "image/*", capture: "environment", style: { display: 'none' }, onChange: handleFileChange })] }), models.length > 1 && (_jsxs("div", { style: s.modelRow, children: [_jsx("label", { style: s.label, children: "Model" }), _jsx("select", { value: selectedModel, onChange: (e) => onModelChange(e.target.value), style: s.select, children: models.map((m) => (_jsx("option", { value: m, children: m }, m))) })] })), _jsx("button", { onClick: () => file && onSubmit(file), disabled: !file || isLoading, style: { ...s.button, opacity: !file || isLoading ? 0.5 : 1 }, children: isLoading ? 'Checking...' : 'Check Inventory' })] }));
}
const s = {
    panel: { display: 'flex', flexDirection: 'column', gap: 16, padding: 16 },
    uploadArea: {
        border: '2px dashed #ccc',
        borderRadius: 12,
        minHeight: 220,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'pointer',
        overflow: 'hidden',
        background: '#fff',
    },
    preview: { width: '100%', objectFit: 'cover' },
    placeholder: { textAlign: 'center', padding: 32 },
    cameraIcon: { fontSize: 48 },
    hint: { marginTop: 8, color: '#888', fontSize: 14 },
    modelRow: { display: 'flex', alignItems: 'center', gap: 8 },
    label: { fontSize: 14, color: '#555', minWidth: 50 },
    select: {
        flex: 1,
        padding: '8px 12px',
        borderRadius: 8,
        border: '1px solid #ddd',
        fontSize: 14,
    },
    button: {
        padding: '14px 0',
        borderRadius: 12,
        border: 'none',
        background: '#1B3A6B',
        color: '#fff',
        fontSize: 16,
        fontWeight: 600,
        cursor: 'pointer',
        width: '100%',
    },
};
