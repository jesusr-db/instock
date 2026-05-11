import React, { useCallback, useRef, useState } from 'react'
import type { DetectCrop } from './api'

interface CropSelectorProps {
  imageFile: File
  crops: DetectCrop[]
  onConfirm: (coords: [number, number, number, number] | null) => void
}

export default function CropSelector({ imageFile, crops, onConfirm }: CropSelectorProps) {
  const imgRef = useRef<HTMLImageElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [imageLoaded, setImageLoaded] = useState(false)
  const [selectedYolo, setSelectedYolo] = useState<number | null>(null)
  const [drawnBox, setDrawnBox] = useState<[number, number, number, number] | null>(null)
  const [drawMode, setDrawMode] = useState(false)
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null)
  const [dragCurrent, setDragCurrent] = useState<{ x: number; y: number } | null>(null)

  const imageUrl = React.useMemo(() => URL.createObjectURL(imageFile), [imageFile])
  React.useEffect(() => () => URL.revokeObjectURL(imageUrl), [imageUrl])

  function getScale(): { scaleX: number; scaleY: number } {
    const img = imgRef.current
    if (!img || img.clientWidth === 0) return { scaleX: 1, scaleY: 1 }
    return {
      scaleX: img.naturalWidth / img.clientWidth,
      scaleY: img.naturalHeight / img.clientHeight,
    }
  }

  const getRelativePos = useCallback(
    (e: React.MouseEvent<HTMLDivElement> | React.TouchEvent<HTMLDivElement>): { x: number; y: number } => {
      const rect = containerRef.current!.getBoundingClientRect()
      let clientX: number
      let clientY: number
      if ('touches' in e) {
        const touch = e.touches[0] ?? e.changedTouches[0]
        clientX = touch.clientX
        clientY = touch.clientY
      } else {
        clientX = e.clientX
        clientY = e.clientY
      }
      return {
        x: Math.max(0, Math.min(clientX - rect.left, rect.width)),
        y: Math.max(0, Math.min(clientY - rect.top, rect.height)),
      }
    },
    []
  )

  function handlePointerDown(e: React.MouseEvent<HTMLDivElement> | React.TouchEvent<HTMLDivElement>) {
    if (!drawMode) return
    e.preventDefault()
    const pos = getRelativePos(e)
    setDragStart(pos)
    setDragCurrent(pos)
    setSelectedYolo(null)
    setDrawnBox(null)
  }

  function handlePointerMove(e: React.MouseEvent<HTMLDivElement> | React.TouchEvent<HTMLDivElement>) {
    if (!drawMode || !dragStart) return
    e.preventDefault()
    setDragCurrent(getRelativePos(e))
  }

  function handlePointerUp(e: React.MouseEvent<HTMLDivElement> | React.TouchEvent<HTMLDivElement>) {
    if (!drawMode || !dragStart || !dragCurrent) return
    e.preventDefault()
    const { scaleX, scaleY } = getScale()
    const x1 = Math.round(Math.min(dragStart.x, dragCurrent.x) * scaleX)
    const y1 = Math.round(Math.min(dragStart.y, dragCurrent.y) * scaleY)
    const x2 = Math.round(Math.max(dragStart.x, dragCurrent.x) * scaleX)
    const y2 = Math.round(Math.max(dragStart.y, dragCurrent.y) * scaleY)
    if (x2 - x1 > 5 && y2 - y1 > 5) {
      setDrawnBox([x1, y1, x2, y2])
    }
    setDragStart(null)
    setDragCurrent(null)
    setDrawMode(false)
  }

  function handleConfirm() {
    if (drawnBox) {
      onConfirm(drawnBox)
    } else if (selectedYolo !== null) {
      const crop = crops[selectedYolo]
      onConfirm([crop.bbox[0], crop.bbox[1], crop.bbox[2], crop.bbox[3]])
    }
  }

  const hasSelection = selectedYolo !== null || drawnBox !== null
  const isDragging = dragStart !== null && dragCurrent !== null

  const { scaleX, scaleY } = imageLoaded ? getScale() : { scaleX: 1, scaleY: 1 }

  const dragRect = isDragging ? dragRectStyle() : null
  const drawnRect = !isDragging && drawnBox ? drawnRectStyle() : null

  function bboxStyle(bbox: [number, number, number, number], selected: boolean): React.CSSProperties {
    return {
      position: 'absolute',
      left: bbox[0] / scaleX,
      top: bbox[1] / scaleY,
      width: (bbox[2] - bbox[0]) / scaleX,
      height: (bbox[3] - bbox[1]) / scaleY,
      border: selected ? '2px solid #2563eb' : '2px solid #f59e0b',
      background: selected ? 'rgba(37,99,235,0.15)' : 'rgba(245,158,11,0.1)',
      cursor: 'pointer',
      boxSizing: 'border-box',
    }
  }

  function dragRectStyle(): React.CSSProperties | null {
    if (!dragStart || !dragCurrent) return null
    return {
      position: 'absolute',
      left: Math.min(dragStart.x, dragCurrent.x),
      top: Math.min(dragStart.y, dragCurrent.y),
      width: Math.abs(dragCurrent.x - dragStart.x),
      height: Math.abs(dragCurrent.y - dragStart.y),
      border: '2px dashed #2563eb',
      background: 'rgba(37,99,235,0.1)',
      boxSizing: 'border-box',
      pointerEvents: 'none',
    }
  }

  function drawnRectStyle(): React.CSSProperties | null {
    if (!drawnBox) return null
    return {
      position: 'absolute',
      left: drawnBox[0] / scaleX,
      top: drawnBox[1] / scaleY,
      width: (drawnBox[2] - drawnBox[0]) / scaleX,
      height: (drawnBox[3] - drawnBox[1]) / scaleY,
      border: '2px solid #16a34a',
      background: 'rgba(22,163,74,0.12)',
      boxSizing: 'border-box',
      pointerEvents: 'none',
    }
  }

  return (
    <div style={{ padding: 16, maxWidth: 480, margin: '0 auto' }}>
      {crops.length === 0 && (
        <div style={cs.warningBanner}>
          No regions detected — draw around the product or analyze the full image
        </div>
      )}

      <div
        ref={containerRef}
        style={{
          position: 'relative',
          cursor: drawMode ? 'crosshair' : 'default',
          userSelect: 'none',
          touchAction: drawMode ? 'none' : 'auto',
        }}
        onMouseDown={handlePointerDown}
        onMouseMove={handlePointerMove}
        onMouseUp={handlePointerUp}
        onTouchStart={handlePointerDown}
        onTouchMove={handlePointerMove}
        onTouchEnd={handlePointerUp}
      >
        <img
          ref={imgRef}
          src={imageUrl}
          onLoad={() => setImageLoaded(true)}
          style={{ width: '100%', display: 'block', borderRadius: 8 }}
          draggable={false}
          alt="Product image for crop selection"
        />

        {imageLoaded && crops.map((crop, i) => (
          <div
            key={i}
            style={bboxStyle(crop.bbox, selectedYolo === i)}
            onClick={(e) => {
              e.stopPropagation()
              if (!drawMode) {
                setSelectedYolo(i)
                setDrawnBox(null)
              }
            }}
          >
            <span style={cs.badge}>{Math.round(crop.confidence * 100)}%</span>
          </div>
        ))}

        {dragRect && (
          <div style={dragRect} />
        )}

        {drawnRect && (
          <div style={drawnRect} />
        )}
      </div>

      <div style={cs.controls}>
        <button
          style={{ ...cs.btn, ...(drawMode ? cs.btnActive : cs.btnSecondary) }}
          onClick={() => {
            setDrawMode(!drawMode)
            setDragStart(null)
            setDragCurrent(null)
          }}
        >
          {drawMode ? 'Drawing… tap to cancel' : '✏ Draw my own'}
        </button>
        <button
          style={{ ...cs.btn, ...cs.btnPrimary, opacity: hasSelection ? 1 : 0.4 }}
          disabled={!hasSelection}
          onClick={handleConfirm}
        >
          Analyze →
        </button>
      </div>

      <div style={{ textAlign: 'center', marginTop: 8 }}>
        <button style={cs.link} onClick={() => onConfirm(null)}>
          Use full image
        </button>
      </div>
    </div>
  )
}

const cs: Record<string, React.CSSProperties> = {
  warningBanner: {
    background: '#fffbeb',
    border: '1px solid #f59e0b',
    color: '#92400e',
    borderRadius: 8,
    padding: '10px 14px',
    marginBottom: 12,
    fontSize: 13,
  },
  badge: {
    position: 'absolute',
    top: 2,
    left: 2,
    background: 'rgba(0,0,0,0.6)',
    color: '#fff',
    fontSize: 11,
    padding: '1px 4px',
    borderRadius: 4,
  },
  controls: {
    display: 'flex',
    gap: 10,
    marginTop: 12,
  },
  btn: {
    flex: 1,
    padding: '12px 16px',
    borderRadius: 8,
    border: 'none',
    cursor: 'pointer',
    fontSize: 14,
    fontWeight: 600,
  },
  btnPrimary: { background: '#1B3A6B', color: '#fff' },
  btnSecondary: { background: '#f3f4f6', color: '#374151' },
  btnActive: { background: '#dbeafe', color: '#1d4ed8', border: '2px solid #2563eb' },
  link: {
    background: 'none',
    border: 'none',
    color: '#6b7280',
    fontSize: 13,
    cursor: 'pointer',
    textDecoration: 'underline',
  },
}
