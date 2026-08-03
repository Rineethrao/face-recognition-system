import { useEffect, useRef, useState, useCallback } from 'react'
import { Camera as CameraIcon, Video, VideoOff, Loader2 } from 'lucide-react'
import clsx from 'clsx'
import { analyzeFrame } from '../lib/api'
import type { AnalyzedFace } from '../lib/api'

const CAPTURE_INTERVAL_MS = 750

interface BrowserWebcamProps {
  onRecognized?: (face: AnalyzedFace) => void
}

/**
 * Uses the visitor's own device camera (laptop/phone webcam) via getUserMedia
 * as a live recognition source — no RTSP/CCTV camera configuration required.
 * Captures a JPEG frame on an interval, sends it to the backend for
 * SCRFD + ArcFace + FAISS recognition, and draws the result as an overlay.
 */
export function BrowserWebcam({ onRecognized }: BrowserWebcamProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const captureCanvasRef = useRef<HTMLCanvasElement>(document.createElement('canvas'))
  const streamRef = useRef<MediaStream | null>(null)
  const intervalRef = useRef<number | null>(null)
  const inFlightRef = useRef(false)

  const [active, setActive] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [analyzeError, setAnalyzeError] = useState<string | null>(null)
  const [faceCount, setFaceCount] = useState(0)
  const [lastFaces, setLastFaces] = useState<AnalyzedFace[]>([])

  const drawOverlay = useCallback((faces: AnalyzedFace[], srcW: number, srcH: number) => {
    const canvas = canvasRef.current
    const video = videoRef.current
    if (!canvas || !video) return
    const dispW = video.clientWidth
    const dispH = video.clientHeight
    canvas.width = dispW
    canvas.height = dispH
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.clearRect(0, 0, dispW, dispH)
    if (!srcW || !srcH) return

    const scaleX = dispW / srcW
    const scaleY = dispH / srcH

    faces.forEach(f => {
      const [x1, y1, x2, y2] = f.bbox
      const rx = x1 * scaleX, ry = y1 * scaleY
      const rw = (x2 - x1) * scaleX, rh = (y2 - y1) * scaleY
      const isRecognized = f.status === 'recognized'
      const color = isRecognized ? '#22c55e' : f.status === 'low_confidence' ? '#f59e0b' : '#64748b'

      ctx.lineWidth = 2
      ctx.strokeStyle = color
      ctx.strokeRect(rx, ry, rw, rh)

      const label = isRecognized
        ? `${f.name} • ${Math.round(f.similarity * 100)}%`
        : 'Unknown'
      ctx.font = '600 12px Inter, sans-serif'
      const textW = ctx.measureText(label).width
      ctx.fillStyle = color
      ctx.fillRect(rx, Math.max(0, ry - 20), textW + 12, 20)
      ctx.fillStyle = '#0a0f1e'
      ctx.fillText(label, rx + 6, Math.max(14, ry - 6))
    })
  }, [])

  const captureAndAnalyze = useCallback(async () => {
    if (inFlightRef.current) return
    const video = videoRef.current
    if (!video || video.readyState < 2) return

    const capCanvas = captureCanvasRef.current
    const w = video.videoWidth
    const h = video.videoHeight
    if (!w || !h) return
    capCanvas.width = w
    capCanvas.height = h
    const ctx = capCanvas.getContext('2d')
    if (!ctx) return
    ctx.drawImage(video, 0, 0, w, h)
    const dataUrl = capCanvas.toDataURL('image/jpeg', 0.75)

    inFlightRef.current = true
    try {
      const result = await analyzeFrame(dataUrl, 'browser_cam')
      setAnalyzeError(null)
      setLastFaces(result.faces)
      setFaceCount(result.faces.length)
      drawOverlay(result.faces, result.frame_width, result.frame_height)
      result.faces.forEach(f => {
        if (f.status === 'recognized' && onRecognized) onRecognized(f)
      })
    } catch (e: any) {
      const msg = e?.response?.status
        ? `Backend error ${e.response.status}: ${e.response?.data?.message || 'analyze_frame failed'}`
        : e?.message || 'Network error — cannot reach backend'
      console.error('[BrowserWebcam] captureAndAnalyze failed:', msg, e)
      setAnalyzeError(msg)
    } finally {
      inFlightRef.current = false
    }
  }, [drawOverlay, onRecognized])

  const stop = useCallback(() => {
    if (intervalRef.current) {
      window.clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop())
      streamRef.current = null
    }
    setActive(false)
    setFaceCount(0)
    setLastFaces([])
    const canvas = canvasRef.current
    if (canvas) {
      const ctx = canvas.getContext('2d')
      ctx?.clearRect(0, 0, canvas.width, canvas.height)
    }
  }, [])

  const start = useCallback(async () => {
    setError(null)
    setConnecting(true)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' },
        audio: false,
      })
      streamRef.current = stream
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        await videoRef.current.play()
      }
      setActive(true)
      intervalRef.current = window.setInterval(captureAndAnalyze, CAPTURE_INTERVAL_MS)
    } catch (e: any) {
      setError(e?.message?.includes('Permission') || e?.name === 'NotAllowedError'
        ? 'Camera permission denied. Please allow camera access in your browser.'
        : 'Could not access your device camera.')
    } finally {
      setConnecting(false)
    }
  }, [captureAndAnalyze])

  useEffect(() => {
    return () => stop()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="glass rounded-2xl overflow-hidden border border-white/5 hover:border-primary-500/30 transition-all duration-300 flex flex-col h-full relative group">
      <div className="relative flex-1 bg-navy-950 overflow-hidden flex items-center justify-center min-h-[200px]">
        <video
          ref={videoRef}
          muted
          playsInline
          className={clsx("w-full h-full object-contain bg-black", !active && "hidden")}
        />
        <canvas
          ref={canvasRef}
          className={clsx("absolute inset-0 w-full h-full pointer-events-none", !active && "hidden")}
        />

        {!active && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-slate-500 p-6 text-center">
            {connecting ? (
              <Loader2 className="w-8 h-8 animate-spin text-primary-400" />
            ) : (
              <CameraIcon className="w-10 h-10 opacity-40" />
            )}
            <span className="text-xs font-semibold text-slate-400">
              {connecting ? 'Requesting camera access…' : 'Your Device Camera'}
            </span>
            {error && <span className="text-[11px] text-red-400 max-w-[220px]">{error}</span>}
          </div>
        )}

        <div className="cam-overlay" />

        {active && (
          <div className="absolute top-3 left-3 flex items-center gap-2">
            <div className="flex items-center gap-1.5 bg-black/60 backdrop-blur-md rounded-full px-2.5 py-1 border border-white/10">
              <span className="live-dot w-1.5 h-1.5" />
              <span className="text-[10px] font-bold text-red-400 tracking-wider">LIVE</span>
            </div>
            <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-black/40 text-slate-300 border border-white/10 backdrop-blur-md">
              My Camera
            </span>
          </div>
        )}

        <div className="absolute top-3 right-3">
          <button
            onClick={active ? stop : start}
            disabled={connecting}
            className={clsx(
              'flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-[11px] font-semibold backdrop-blur-md border transition-colors',
              active
                ? 'bg-red-500/80 hover:bg-red-500 text-white border-red-400/30'
                : 'bg-primary-500/80 hover:bg-primary-500 text-white border-primary-400/30'
            )}
          >
            {active ? <VideoOff className="w-3.5 h-3.5" /> : <Video className="w-3.5 h-3.5" />}
            {active ? 'Stop' : 'Start My Camera'}
          </button>
        </div>
      </div>

      <div className="px-3 py-2 border-t border-white/5 flex items-center justify-between bg-black/20">
        <span className="text-[10px] font-semibold text-slate-400 truncate">
          {analyzeError
            ? <span className="text-red-400 text-[10px] truncate max-w-[200px]" title={analyzeError}>⚠ {analyzeError}</span>
            : 'Browser Webcam (getUserMedia)'}
        </span>
        <span className={clsx('text-[10px] px-2 py-0.5 rounded-full font-bold',
          active ? (faceCount > 0 ? 'badge-green' : 'badge-blue') : 'badge-red'
        )}>
          {active ? `${faceCount} face(s)` : '○ Off'}
        </span>
      </div>
    </div>
  )
}
