import React, { useEffect, useRef, useState } from 'react'
import ScanPanel from './ScanPanel'
import ResultCard from './ResultCard'
import { analyzeImage, lookupSku, fetchModels } from './api'
import type { AnalyzeResult, LookupResult } from './api'

type AppState = 'idle' | 'loading' | 'result' | 'error'
type LoadingStep = 'uploading' | 'detecting' | 'analyzing' | 'lookup'

const STEPS: { key: LoadingStep; label: string }[] = [
  { key: 'uploading',  label: 'Sending image' },
  { key: 'detecting',  label: 'Detecting products (YOLO)' },
  { key: 'analyzing',  label: 'AI vision analysis' },
  { key: 'lookup',     label: 'Inventory lookup' },
]

const STEP_ORDER: LoadingStep[] = ['uploading', 'detecting', 'analyzing', 'lookup']

const FALLBACK_MODEL = 'instockcv-gateway'

export default function App() {
  const [appState, setAppState]       = useState<AppState>('idle')
  const [loadingStep, setLoadingStep] = useState<LoadingStep>('uploading')
  const [result, setResult]           = useState<LookupResult | null>(null)
  const [analyzed, setAnalyzed]       = useState<AnalyzeResult | null>(null)
  const [imageUrl, setImageUrl]       = useState<string | null>(null)
  const [error, setError]             = useState<string | null>(null)
  const [models, setModels]           = useState<string[]>([FALLBACK_MODEL])
  const [selectedModel, setSelectedModel] = useState<string>(FALLBACK_MODEL)
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])

  useEffect(() => {
    fetchModels()
      .then((cfg) => { setModels(cfg.models); setSelectedModel(cfg.default) })
      .catch(() => {})
  }, [])

  function clearTimers() {
    timers.current.forEach(clearTimeout)
    timers.current = []
  }

  async function handleSubmit(file: File) {
    setAppState('loading')
    setLoadingStep('uploading')
    setError(null)
    setImageUrl(URL.createObjectURL(file))
    clearTimers()

    // Advance steps on a rough timeline matching backend processing time
    timers.current.push(setTimeout(() => setLoadingStep('detecting'), 1500))
    timers.current.push(setTimeout(() => setLoadingStep('analyzing'), 5000))

    try {
      const analyzeResult = await analyzeImage(file, selectedModel)
      clearTimers()
      setAnalyzed(analyzeResult)
      setLoadingStep('lookup')
      const lookupResult = await lookupSku(analyzeResult)
      setResult(lookupResult)
      setAppState('result')
    } catch (e) {
      clearTimers()
      setError(e instanceof Error ? e.message : 'Unexpected error')
      setAppState('error')
    }
  }

  function reset() {
    clearTimers()
    if (imageUrl) URL.revokeObjectURL(imageUrl)
    setResult(null)
    setAnalyzed(null)
    setImageUrl(null)
    setError(null)
    setAppState('idle')
  }

  return (
    <div style={s.root}>
      <header style={s.header}>
        <span style={{ fontSize: 22 }}>📦</span>
        <h1 style={s.title}>inStockCV</h1>
      </header>
      <main style={s.main}>
        {(appState === 'idle' || appState === 'loading' || appState === 'error') && (
          <ScanPanel
            onSubmit={handleSubmit}
            isLoading={appState === 'loading'}
            models={models}
            selectedModel={selectedModel}
            onModelChange={setSelectedModel}
          />
        )}
        {appState === 'loading' && <LoadingSteps current={loadingStep} />}
        {appState === 'error' && error && <div style={s.errorBanner}>{error}</div>}
        {appState === 'result' && result && analyzed && (
          <ResultCard result={result} analyzeResult={analyzed} imageUrl={imageUrl} onReset={reset} />
        )}
      </main>
    </div>
  )
}

function LoadingSteps({ current }: { current: LoadingStep }) {
  const currentIdx = STEP_ORDER.indexOf(current)
  return (
    <div style={ls.wrap}>
      {STEPS.map(({ key, label }, i) => {
        const done   = i < currentIdx
        const active = i === currentIdx
        return (
          <div key={key} style={ls.row}>
            <span style={{ ...ls.dot, ...(done ? ls.dotDone : active ? ls.dotActive : ls.dotPending) }}>
              {done ? '✓' : active ? '◉' : '○'}
            </span>
            <span style={{ ...ls.label, color: done ? '#6b7280' : active ? '#111' : '#9ca3af' }}>
              {label}
              {active && <span style={ls.pulse}>…</span>}
            </span>
          </div>
        )
      })}
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

const ls: Record<string, React.CSSProperties> = {
  wrap: {
    background: '#fff',
    border: '1px solid #e5e7eb',
    borderRadius: 12,
    padding: '16px 20px',
    marginTop: 16,
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  },
  row: { display: 'flex', alignItems: 'center', gap: 10 },
  dot: { fontSize: 15, width: 20, textAlign: 'center', flexShrink: 0 },
  dotDone:    { color: '#16a34a' },
  dotActive:  { color: '#1B3A6B' },
  dotPending: { color: '#d1d5db' },
  label: { fontSize: 14, fontWeight: 500 },
  pulse: { opacity: 0.5 },
}
