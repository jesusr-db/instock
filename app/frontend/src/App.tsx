import React, { useEffect, useState } from 'react'
import ScanPanel from './ScanPanel'
import ResultCard from './ResultCard'
import { analyzeImage, lookupSku, fetchModels } from './api'
import type { LookupResult } from './api'

type State = 'idle' | 'loading' | 'result' | 'error'

const FALLBACK_MODEL = 'instockcv-gateway'

export default function App() {
  const [state, setState] = useState<State>('idle')
  const [result, setResult] = useState<LookupResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [models, setModels] = useState<string[]>([FALLBACK_MODEL])
  const [selectedModel, setSelectedModel] = useState<string>(FALLBACK_MODEL)

  useEffect(() => {
    fetchModels()
      .then((cfg) => {
        setModels(cfg.models)
        setSelectedModel(cfg.default)
      })
      .catch(() => {
        // Network or server error — keep fallback model.
      })
  }, [])

  async function handleSubmit(file: File) {
    setState('loading')
    setError(null)
    try {
      const analyzed = await analyzeImage(file, selectedModel)
      const looked = await lookupSku(analyzed)
      setResult(looked)
      setState('result')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unexpected error')
      setState('error')
    }
  }

  function reset() {
    setResult(null)
    setError(null)
    setState('idle')
  }

  return (
    <div style={s.root}>
      <header style={s.header}>
        <span style={{ fontSize: 22 }}>📦</span>
        <h1 style={s.title}>inStockCV</h1>
      </header>
      <main style={s.main}>
        {(state === 'idle' || state === 'loading' || state === 'error') && (
          <ScanPanel
            onSubmit={handleSubmit}
            isLoading={state === 'loading'}
            models={models}
            selectedModel={selectedModel}
            onModelChange={setSelectedModel}
          />
        )}
        {state === 'error' && error && <div style={s.errorBanner}>{error}</div>}
        {state === 'result' && result && (
          <ResultCard result={result} onReset={reset} />
        )}
      </main>
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
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
}
