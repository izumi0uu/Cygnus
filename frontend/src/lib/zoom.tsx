import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react'

export type ZoomState = {
  zoom: number          // scale factor, 0.5 – 2.0
  panX: number          // pan offset in px
  panY: number
  zoomIn: () => void
  zoomOut: () => void
  zoomFit: () => void
  setZoom: (z: number) => void
  panBy: (dx: number, dy: number) => void
  resetView: () => void
}

const MIN_ZOOM = 0.5
const MAX_ZOOM = 2.0
const ZOOM_STEP = 0.15

const ZoomContext = createContext<ZoomState | null>(null)

export function ZoomProvider({ children }: { children: ReactNode }) {
  const [zoom, setZoomState] = useState(1)
  const [panX, setPanX] = useState(0)
  const [panY, setPanY] = useState(0)
  const resetRef = useRef(false)

  const clampZoom = (z: number) => Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Math.round(z * 100) / 100))

  const zoomIn = useCallback(() => setZoomState((z) => clampZoom(z + ZOOM_STEP)), [])
  const zoomOut = useCallback(() => setZoomState((z) => clampZoom(z - ZOOM_STEP)), [])
  const setZoom = useCallback((z: number) => setZoomState(clampZoom(z)), [])
  const panBy = useCallback((dx: number, dy: number) => {
    setPanX((x) => x + dx)
    setPanY((y) => y + dy)
  }, [])
  const resetView = useCallback(() => {
    setZoomState(1)
    setPanX(0)
    setPanY(0)
  }, [])
  const zoomFit = useCallback(() => {
    resetView()
    resetRef.current = true
  }, [resetView])

  return (
    <ZoomContext.Provider value={{ zoom, panX, panY, zoomIn, zoomOut, zoomFit, setZoom, panBy, resetView }}>
      {children}
    </ZoomContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useZoom() {
  const ctx = useContext(ZoomContext)
  if (!ctx) throw new Error('useZoom must be used within ZoomProvider')
  return ctx
}
