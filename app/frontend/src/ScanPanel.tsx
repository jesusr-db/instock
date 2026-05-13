import React, { useRef, useState } from 'react'

interface Props {
  onSubmit: (file: File) => void
  isLoading: boolean
  models: string[]
  selectedModel: string
  onModelChange: (model: string) => void
  inferenceMode: 'vlm' | 'clip'
  onInferenceModeChange: (mode: 'vlm' | 'clip') => void
}

export default function ScanPanel({
  onSubmit,
  isLoading,
  models,
  selectedModel,
  onModelChange,
  inferenceMode,
  onInferenceModeChange,
}: Props) {
  const [preview, setPreview] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [draggingOver, setDraggingOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  function setImageFile(f: File) {
    setFile(f)
    setPreview(URL.createObjectURL(f))
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (f) setImageFile(f)
  }

  function handleDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDraggingOver(true)
  }

  function handleDragLeave() {
    setDraggingOver(false)
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDraggingOver(false)
    const f = e.dataTransfer.files[0]
    if (f && f.type.startsWith('image/')) setImageFile(f)
  }

  return (
    <div style={s.panel}>
      <div
        style={{ ...s.uploadArea, ...(draggingOver ? s.uploadAreaDragging : {}) }}
        onClick={() => inputRef.current?.click()}
        onDragOver={handleDragOver}
        onDragEnter={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {preview ? (
          <img src={preview} alt="Preview" style={s.preview} />
        ) : (
          <div style={s.placeholder}>
            <div style={s.cameraIcon}>📷</div>
            <p style={s.hint}>{draggingOver ? 'Drop image here' : 'Tap / drag image here'}</p>
          </div>
        )}
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          capture="environment"
          style={{ display: 'none' }}
          onChange={handleFileChange}
        />
      </div>

      {models.length > 1 && (
        <div style={s.modelRow}>
          <label style={s.label}>Model</label>
          <select
            value={selectedModel}
            onChange={(e) => onModelChange(e.target.value)}
            style={s.select}
          >
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
      )}

      <div style={s.toggleRow}>
        <span style={{ fontSize: '0.8rem', color: '#888' }}>Mode</span>
        <button
          style={{ ...s.toggleBtn, ...(inferenceMode === 'vlm' ? s.toggleBtnActive : {}) }}
          onClick={() => onInferenceModeChange('vlm')}
        >VLM</button>
        <button
          style={{ ...s.toggleBtn, ...(inferenceMode === 'clip' ? s.toggleBtnActive : {}) }}
          onClick={() => onInferenceModeChange('clip')}
        >CLIP + VS</button>
      </div>

      <button
        onClick={() => file && onSubmit(file)}
        disabled={!file || isLoading}
        style={{ ...s.button, opacity: !file || isLoading ? 0.5 : 1 }}
      >
        {isLoading ? 'Checking...' : 'Check Inventory'}
      </button>
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
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
    transition: 'border-color 0.15s, background 0.15s',
  },
  uploadAreaDragging: {
    borderColor: '#1B3A6B',
    background: '#eff4ff',
  },
  preview: { width: '100%', objectFit: 'cover' },
  placeholder: { textAlign: 'center', padding: 32 },
  cameraIcon: { fontSize: 48 },
  hint: { marginTop: 8, color: '#888', fontSize: 14 },
  modelRow: { display: 'flex', alignItems: 'center', gap: 8 },
  toggleRow: { display: 'flex', alignItems: 'center', gap: '8px', marginTop: '8px' },
  toggleBtn: { padding: '4px 12px', borderRadius: '14px', border: '1px solid #555', background: '#2a2a2a', color: '#ccc', cursor: 'pointer', fontSize: '0.8rem' },
  toggleBtnActive: { background: '#e94e0f', borderColor: '#e94e0f', color: '#fff' },
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
}
