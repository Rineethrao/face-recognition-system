import { useEffect, useState, useRef, useCallback } from 'react'
import {
  Search, Maximize2, RefreshCw, User,
  Camera as CameraIcon, Clock, AlertCircle,
  Grid2x2, LayoutGrid, Sparkles, Grid3x3,
} from 'lucide-react'

import { TopBar } from '../components/TopBar'
import { useStore } from '../store/useStore'
import {
  getCameras, getRecognitions, getDetectedFaces,
} from '../lib/api'
import type { RecognitionEvent, DetectedFace } from '../lib/api'
import clsx from 'clsx'

type GridLayout = 'auto' | '1x1' | '2x2' | '3x3'

function ConfPill({ sim }: { sim: number }) {
  const pct = Math.round(sim * 100)
  return (
    <span className={clsx('conf-pill text-[10px]',
      pct >= 85 ? 'conf-high' : pct >= 70 ? 'conf-mid' : 'conf-low'
    )}>
      {pct}%
    </span>
  )
}

function RecognitionCard({ event }: { event: RecognitionEvent }) {
  const isUnknown = event.person_id === 'unknown'
  const [imgSrc, setImgSrc] = useState<string>(() =>
    isUnknown ? '' : `/faces/${event.person_id}/sample_1.jpg`
  )
  const [imgError, setImgError] = useState(false)

  const handleImgError = () => {
    if (imgSrc.endsWith('sample_1.jpg')) {
      setImgSrc(`/faces/${event.person_id}/uploaded_1.jpg`)
    } else if (imgSrc.endsWith('uploaded_1.jpg')) {
      setImgSrc(`/faces/${event.person_id}/snapshot_1.jpg`)
    } else {
      setImgError(true)
    }
  }

  const pct = Math.round(event.similarity * 100)

  return (
    <div className="rec-card flex items-center gap-3 p-2.5 rounded-xl glass border border-white/5 hover:border-primary-500/30 transition-all">
      {/* Registered Face Photo Crop / Frame */}
      <div className={clsx(
        'w-12 h-12 rounded-xl flex items-center justify-center font-bold text-sm flex-shrink-0 overflow-hidden border relative shadow-md bg-slate-900',
        isUnknown
          ? 'border-white/10 text-slate-400'
          : pct >= 45
          ? 'border-green-500/50 shadow-green-500/10'
          : 'border-amber-500/50 shadow-amber-500/10'
      )}>
        {!isUnknown && !imgError && imgSrc ? (
          <img
            src={imgSrc}
            alt={event.name}
            onError={handleImgError}
            className="w-full h-full object-cover"
          />
        ) : (
          <span className={clsx(isUnknown ? 'text-slate-400' : 'text-primary-400')}>
            {isUnknown ? '?' : (event.name?.[0]?.toUpperCase() || 'U')}
          </span>
        )}

        {!isUnknown && (
          <div className={clsx(
            'absolute bottom-0 left-0 right-0 text-[7px] font-mono text-center font-bold text-black py-0.2',
            pct >= 45 ? 'bg-green-400' : 'bg-amber-400'
          )}>
            {pct >= 45 ? 'MATCH' : 'POSSIBLE'}
          </div>
        )}
      </div>

      {/* Recognized Person Details */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-1 mb-0.5">
          <span className={clsx(
            'text-xs font-bold truncate',
            isUnknown ? 'text-slate-400' : 'text-white'
          )}>
            {isUnknown ? 'Unknown Person' : event.name}
          </span>
          <span className={clsx(
            'px-1.5 py-0.5 rounded text-[9px] font-bold font-mono flex-shrink-0',
            isUnknown
              ? 'bg-slate-800 text-slate-400'
              : pct >= 45
              ? 'bg-green-500/20 text-green-400 border border-green-500/30'
              : 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
          )}>
            {pct}%
          </span>
        </div>

        <div className="text-[10px] text-slate-400 flex items-center justify-between">
          <span className="flex items-center gap-1 truncate text-slate-400">
            <CameraIcon className="w-3 h-3 text-slate-500 flex-shrink-0" />
            {event.camera_id || 'cam_02'}
          </span>
          <span className="flex items-center gap-1 font-mono text-[9px] text-slate-500 flex-shrink-0">
            <Clock className="w-3 h-3 text-slate-500 flex-shrink-0" />
            {event.recognized_at?.split(' ')[1] || event.recognized_at || ''}
          </span>
        </div>
      </div>
    </div>
  )
}

interface CameraCardProps {
  name: string
  location: string
  isOnline: boolean
  camId: string
  onExpand?: () => void
  isSingle?: boolean
}

function CameraCard({ name, location, isOnline, camId, onExpand, isSingle }: CameraCardProps) {
  const imgRef = useRef<HTMLImageElement>(null)
  // Stable stream URL — never put Date.now() in JSX src or every parent
  // re-render reconnects the MJPEG stream and can crash the capture pipeline.
  const [streamUrl, setStreamUrl] = useState(() => `/video_feed/${camId}`)

  useEffect(() => {
    setStreamUrl(`/video_feed/${camId}`)
  }, [camId])

  const refreshStream = useCallback(() => {
    setStreamUrl(`/video_feed/${camId}?t=${Date.now()}`)
  }, [camId])

  // Auto-recover if the <img> MJPEG connection dies
  useEffect(() => {
    const img = imgRef.current
    if (!img || !isOnline) return

    let timer: number | undefined
    const onError = () => {
      if (timer) window.clearTimeout(timer)
      timer = window.setTimeout(() => {
        setStreamUrl(`/video_feed/${camId}?t=${Date.now()}`)
      }, 2000)
    }

    img.addEventListener('error', onError)
    return () => {
      img.removeEventListener('error', onError)
      if (timer) window.clearTimeout(timer)
    }
  }, [camId, isOnline])

  return (
    <div className="glass rounded-2xl overflow-hidden border border-white/5 dark:border-white/5 hover:border-primary-500/30 transition-all duration-300 flex flex-col h-full group relative">
      {/* Video Viewport */}
      <div className="relative flex-1 bg-navy-950 dark:bg-navy-950 overflow-hidden flex items-center justify-center">
        {isOnline ? (
          <img
            ref={imgRef}
            src={streamUrl}
            alt={`${name} live stream`}
            className="w-full h-full object-contain bg-black"
          />
        ) : (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-slate-600">
            <CameraIcon className="w-10 h-10" />
            <span className="text-xs font-semibold">Camera Stream Offline</span>
          </div>
        )}

        {/* Gradient Overlay */}
        <div className="cam-overlay" />

        {/* Top Badges */}
        <div className="absolute top-3 left-3 flex items-center gap-2">
          {isOnline && (
            <div className="flex items-center gap-1.5 bg-black/60 backdrop-blur-md rounded-full px-2.5 py-1 border border-white/10">
              <span className="live-dot w-1.5 h-1.5" />
              <span className="text-[10px] font-bold text-red-400 tracking-wider">LIVE</span>
            </div>
          )}
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-black/40 text-slate-300 border border-white/10 backdrop-blur-md">
            {name}
          </span>
        </div>

        {/* Actions */}
        <div className="absolute top-3 right-3 flex gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={refreshStream}
            className="w-7 h-7 rounded-xl bg-black/60 backdrop-blur-md flex items-center justify-center text-white hover:bg-primary-500 transition-colors border border-white/10"
            title="Refresh Stream"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
          {onExpand && (
            <button
              onClick={onExpand}
              className="w-7 h-7 rounded-xl bg-black/60 backdrop-blur-md flex items-center justify-center text-white hover:bg-primary-500 transition-colors border border-white/10"
              title="Full View"
            >
              <Maximize2 className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Card Info Bar */}
      <div className="px-3.5 py-2.5 flex items-center justify-between border-t border-white/5 bg-navy-950/60 backdrop-blur-md flex-shrink-0">
        <div className="min-w-0">
          <div className="text-xs font-bold text-slate-200 truncate">{name}</div>
          <div className="text-[10px] text-slate-400 truncate">{location} • ID: {camId}</div>
        </div>
        <span className={clsx('text-[10px] px-2.5 py-0.5 rounded-full font-bold flex-shrink-0',
          isOnline ? 'badge-green' : 'badge-red'
        )}>
          {isOnline ? '● Online' : '○ Offline'}
        </span>
      </div>
    </div>
  )
}

export function LiveRecognition() {
  const { cameras, setCameras } = useStore()
  const [events, setEvents] = useState<RecognitionEvent[]>([])
  const [faces, setFaces] = useState<DetectedFace[]>([])
  const [layout, setLayout] = useState<GridLayout>('auto')
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<'online' | 'all' | 'offline'>('online')

  useEffect(() => {
    getCameras().then(setCameras).catch(() => {})
    getRecognitions(30).then(setEvents).catch(() => {})

    const evtInterval = setInterval(() => {
      getRecognitions(30).then(setEvents).catch(() => {})
    }, 2000)

    const faceInterval = setInterval(() => {
      getDetectedFaces().then(setFaces).catch(() => {})
    }, 1500)

    return () => {
      clearInterval(evtInterval)
      clearInterval(faceInterval)
    }
  }, [])

  const filteredCams = cameras.filter(c => {
    const matchSearch = c.name.toLowerCase().includes(search.toLowerCase()) ||
      c.location.toLowerCase().includes(search.toLowerCase()) ||
      c.id.toLowerCase().includes(search.toLowerCase())
    const isLive = !!(c as any).is_active || c.enabled
    const matchStatus = statusFilter === 'all' ||
      (statusFilter === 'online' && isLive) ||
      (statusFilter === 'offline' && !isLive)
    return matchSearch && matchStatus
  })

  const getAutoGridClass = () => {
    if (layout === '1x1') return 'grid-cols-1 grid-rows-1 h-full'
    if (layout === '2x2') return 'grid-cols-2 grid-rows-2 h-full'
    if (layout === '3x3') return 'grid-cols-3 grid-rows-3 h-full'
    const count = filteredCams.length
    if (count <= 1) return 'grid-cols-1 grid-rows-1 h-full'
    if (count === 2) return 'grid-cols-2 grid-rows-1 h-full'
    if (count <= 4) return 'grid-cols-2 grid-rows-2 h-full'
    if (count <= 6) return 'grid-cols-3 grid-rows-2 h-full'
    return 'grid-cols-3 grid-rows-3 h-full'
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <TopBar title="Live Recognition" />

      {/* Filter & Control Toolbar */}
      <div className="px-6 py-2.5 border-b border-white/5 flex items-center gap-3 flex-wrap glass flex-shrink-0">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
          <input
            className="input-field pl-9 w-48 py-1.5 text-xs"
            placeholder="Search cameras..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-1 glass p-1 rounded-xl border border-white/5">
          {(['online', 'all', 'offline'] as const).map(f => (
            <button
              key={f}
              onClick={() => setStatusFilter(f)}
              className={clsx(
                'px-3 py-1 rounded-lg text-xs font-semibold capitalize transition-all',
                statusFilter === f
                  ? 'bg-primary-500 text-white shadow-md'
                  : 'text-slate-400 hover:text-white'
              )}
            >
              {f === 'online' ? `Online (${cameras.filter(c => !!(c as any).is_active || c.enabled).length})` : f}
            </button>
          ))}
        </div>

        {/* Grid Controls */}
        <div className="ml-auto flex items-center gap-2">
          <div className="flex items-center gap-1 glass p-1 rounded-xl border border-white/5">
            <button
              onClick={() => setLayout('auto')}
              className={clsx(
                'px-3 py-1 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all',
                layout === 'auto'
                  ? 'bg-gradient-to-r from-primary-500 to-teal-500 text-white shadow-md'
                  : 'text-slate-400 hover:text-white'
              )}
              title="Auto-Fit Grid to Online Cameras"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>Auto Fit</span>
            </button>

            {[
              ['1x1', LayoutGrid],
              ['2x2', Grid2x2],
              ['3x3', Grid3x3]
            ].map(([l, Icon]: any) => (
              <button
                key={l}
                onClick={() => setLayout(l as any)}
                className={clsx(
                  'w-7 h-7 rounded-lg flex items-center justify-center transition-all',
                  layout === l ? 'bg-primary-500 text-white' : 'text-slate-400 hover:text-white'
                )}
                title={`Fixed ${l} Layout`}
              >
                <Icon className="w-3.5 h-3.5" />
              </button>
            ))}
          </div>

          {/* Active Detected Faces Chip */}
          <div className="badge-blue px-3 py-1 text-xs">
            <User className="w-3.5 h-3.5" />
            {faces.length} Active Faces
          </div>
        </div>
      </div>

      {/* Main Content Area: Camera Grid (70%) + Recognition Feed (30%) */}
      <div className="flex-1 flex overflow-hidden">

        {/* Left Side — Live Camera Viewport Panel (70%) */}
        <div className="flex-1 p-3 flex flex-col min-w-0 overflow-hidden">
          <div className={clsx('grid gap-2.5 flex-1 min-h-0', getAutoGridClass())}>
            {filteredCams.map((cam) => (
              <CameraCard
                key={cam.id}
                camId={cam.id}
                name={cam.name}
                location={cam.location}
                isOnline={!!(cam as any).is_active || cam.enabled}
                onExpand={() => setLayout('1x1')}
                isSingle={filteredCams.length === 1}
              />
            ))}

            {filteredCams.length === 0 && (
              <div className="col-span-full h-full flex flex-col items-center justify-center glass rounded-2xl p-8 text-slate-500">
                <CameraIcon className="w-12 h-12 mb-3 opacity-30" />
                <h4 className="text-sm font-semibold text-slate-300 mb-1">No Cameras Matching View Filter</h4>
                <p className="text-xs text-slate-500">Try switching filter to 'All' or enable cameras in Camera Management.</p>
              </div>
            )}
          </div>


        </div>

        {/* Right Side — Real-Time Recognition Feed (30%) */}
        <div className="w-80 flex-shrink-0 border-l border-white/5 flex flex-col overflow-hidden glass">
          <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between flex-shrink-0">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-primary-400" />
              Recognition Feed
            </h3>
            <span className="badge-blue text-[10px] font-mono">{events.length}</span>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {events.map(evt => (
              <RecognitionCard key={`${evt.id}-${evt.track_id}`} event={evt} />
            ))}
            {events.length === 0 && (
              <div className="text-center py-16 text-slate-500 text-xs">
                <AlertCircle className="w-8 h-8 mx-auto mb-2 opacity-30" />
                <p>Waiting for recognition events...</p>
              </div>
            )}
          </div>
        </div>

      </div>

      {/* Bottom Status Bar */}
      <div className="px-6 py-1.5 border-t border-white/5 glass flex items-center gap-6 text-[11px] text-slate-500 flex-shrink-0">
        <span className="flex items-center gap-1.5">
          <span className="online-dot w-1.5 h-1.5" />
          SCRFD 10G Detection
        </span>
        <span>ByteTrack Multi-Object Tracking</span>
        <span>ArcFace 512-D Embedding Extraction</span>
        <span className="ml-auto text-slate-400 font-mono">FAISS Vector Search Engine Active</span>
      </div>
    </div>
  )
}
