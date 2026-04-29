import React, { useRef, useState } from 'react'

interface Props {
  onSubmit: (file: File) => void
  isLoading: boolean
  models: string[]
  selectedModel: string
  onModelChange: (model: string) => void
}

export default function ScanPanel({
  onSubmit,
  isLoading,
  models,
  selectedModel,
  onModelChange,
}: Props) {
  const [preview, setPreview] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (!f) return
    setFile(f)
    setPreview(URL.createObjectURL(f))
  }

  return (
    <div style={s.panel}>
      <div style={s.uploadArea} onClick={() => inputRef.current?.click()}>
        {preview ? (
          <img src={preview} alt="Preview" style={s.preview} />
        ) : (
          <div style={s.placeholder}>
            <div style={s.cameraIcon}>📷</div>
            <p style={s.hint}>Tap to take a photo or select image</p>
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
}
