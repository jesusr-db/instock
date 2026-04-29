import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import ScanPanel from './ScanPanel';
import ResultCard from './ResultCard';
import { analyzeImage, lookupSku, fetchModels } from './api';
const FALLBACK_MODEL = 'instockcv-gateway';
export default function App() {
    const [state, setState] = useState('idle');
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);
    const [models, setModels] = useState([FALLBACK_MODEL]);
    const [selectedModel, setSelectedModel] = useState(FALLBACK_MODEL);
    useEffect(() => {
        fetchModels()
            .then((cfg) => {
            setModels(cfg.models);
            setSelectedModel(cfg.default);
        })
            .catch(() => {
            // Network or server error — keep fallback model.
        });
    }, []);
    async function handleSubmit(file) {
        setState('loading');
        setError(null);
        try {
            const analyzed = await analyzeImage(file, selectedModel);
            const looked = await lookupSku(analyzed);
            setResult(looked);
            setState('result');
        }
        catch (e) {
            setError(e instanceof Error ? e.message : 'Unexpected error');
            setState('error');
        }
    }
    function reset() {
        setResult(null);
        setError(null);
        setState('idle');
    }
    return (_jsxs("div", { style: s.root, children: [_jsxs("header", { style: s.header, children: [_jsx("span", { style: { fontSize: 22 }, children: "\uD83D\uDCE6" }), _jsx("h1", { style: s.title, children: "inStockCV" })] }), _jsxs("main", { style: s.main, children: [(state === 'idle' || state === 'loading' || state === 'error') && (_jsx(ScanPanel, { onSubmit: handleSubmit, isLoading: state === 'loading', models: models, selectedModel: selectedModel, onModelChange: setSelectedModel })), state === 'error' && error && _jsx("div", { style: s.errorBanner, children: error }), state === 'result' && result && (_jsx(ResultCard, { result: result, onReset: reset }))] })] }));
}
const s = {
    root: { minHeight: '100vh', background: '#f5f5f5' },
    header: {
        background: '#1B3A6B',
        color: '#fff',
        padding: '14px 20px',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
    },
    title: { fontSize: 20, fontWeight: 700, letterSpacing: -0.3 },
    main: { padding: 16, maxWidth: 480, margin: '0 auto' },
    errorBanner: {
        background: '#fef2f2',
        border: '1px solid #fecaca',
        color: '#dc2626',
        borderRadius: 10,
        padding: '12px 16px',
        marginTop: 12,
        fontSize: 14,
    },
};
