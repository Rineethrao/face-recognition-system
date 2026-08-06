import { useEffect, useState, useRef, useCallback } from 'react'
import {
  Search, Maximize2, RefreshCw, User,
  Camera as CameraIcon, Clock, AlertCircle,
  Grid2x2, LayoutGrid, Sparkles, Grid3x3, Radio, Eye
} from 'lucide-react'

import { TopBar } from '../components/TopBar'
import { BrowserWebcam } from '../components/BrowserWebcam'
import { useStore } from '../store/useStore'
import { getCameras, getRecognitions, getDetectedFaces } from '../lib/api'
import { updateCamera } from '../lib/cameraApi'
import type { RecognitionEvent, DetectedFace } from '../lib/api'
import { Card, CardHeader, CardTitle, CardBody } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { parseUtcTimestamp, formatRelativeAgo } from '../lib/datetime'
import clsx from 'clsx'

type GridLayout = 'auto' | '1x1' | '2x2' | '3x3'

/** One latest recognition event per person_id, newest first. */
function latestEventsByPerson(events: RecognitionEvent[]): RecognitionEvent[] {
  const byPerson = new Map<string, RecognitionEvent>()

  for (const event of events) {
    const key = event.person_id || 'unknown'
    const existing = byPerson.get(key)
    if (!existing) {
      byPerson.set(key, event)
      continue
    }
    const nextTs = parseUtcTimestamp(event.recognized_at)?.getTime() ?? 0
    const prevTs = parseUtcTimestamp(existing.recognized_at)?.getTime() ?? 0
    if (nextTs >= prevTs) byPerson.set(key, event)
  }

  return Array.from(byPerson.values()).sort((a, b) => {
    const aTs = parseUtcTimestamp(a.recognized_at)?.getTime() ?? 0
    const bTs = parseUtcTimestamp(b.recognized_at)?.getTime() ?? 0
    return bTs - aTs
  })
}

function RecognitionCard({ event, nowMs }: { event: RecognitionEvent; nowMs: number }) {
  const isUnknown = event.person_id === 'unknown'
  const [imgSrc, setImgSrc] = useState<string>(() =>
    isUnknown ? '' : `/faces/${event.person_id}/sample_1_frontal.jpg`
  )
  const [imgError, setImgError] = useState(false)

  const handleImgError = () => {
    if (imgSrc.endsWith('sample_1_frontal.jpg')) {
      setImgSrc(`/faces/${event.person_id}/sample_1.jpg`)
    } else if (imgSrc.endsWith('sample_1.jpg')) {
      setImgSrc(`/faces/${event.person_id}/uploaded_1.jpg`)
    } else if (imgSrc.endsWith('uploaded_1.jpg')) {
      setImgSrc(`/faces/${event.person_id}/snapshot_1.jpg`)
    } else {
      setImgError(true)
    }
  }

  const pct = Math.round((event.similarity || 0) * 100)

  return (
    <div
      className={clsx(
        'p-3 rounded-2xl border transition-all duration-150 flex items-center gap-3',
        isUnknown
          ? 'bg-amber-500/5 border-amber-500/25 hover:border-amber-500/40'
          : 'bg-white/85 dark:bg-slate-900/80 border-slate-200 dark:border-slate-800 hover:border-blue-500/40 shadow-sm'
      )}
    >
      {/* Face Crop Preview */}
      <div
        className={clsx(
          'w-12 h-12 rounded-xl flex items-center justify-center font-bold text-sm flex-shrink-0 overflow-hidden border relative bg-slate-950 shadow-md',
          isUnknown ? 'border-amber-500/40 text-amber-400' : 'border-emerald-500/40 text-emerald-400'
        )}
      >
        {!isUnknown && !imgError && imgSrc ? (
          <img
            src={imgSrc}
            alt={event.name}
            onError={handleImgError}
            className="w-full h-full object-cover"
          />
        ) : (
          <span>{isUnknown ? '?' : (event.name?.[0]?.toUpperCase() || 'U')}</span>
        )}

        {!isUnknown && (
          <div
            className={clsx(
              'absolute bottom-0 left-0 right-0 text-[8px] font-bold text-center py-0.2 uppercase text-black',
              pct >= 70 ? 'bg-emerald-400' : 'bg-amber-400'
            )}
          >
            Match
          </div>
        )}
      </div>

      {/* Details */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-1 mb-0.5">
          <span className={clsx('text-xs font-bold truncate', isUnknown ? 'text-amber-600 dark:text-amber-300' : 'text-slate-900 dark:text-white')}>
            {isUnknown ? 'Unknown Person' : event.name}
          </span>
        </div>

        <div className="text-[10px] text-slate-500 dark:text-slate-400 flex items-center justify-between">
          <span className="flex items-center gap-1 truncate text-slate-500 dark:text-slate-400">
            <CameraIcon className="w-3 h-3 text-slate-400 dark:text-slate-500 flex-shrink-0" />
            {event.camera_id || 'CCTV Feed'}
          </span>
          <span className="flex items-center gap-1 font-mono text-[9px] text-slate-500 flex-shrink-0">
            <Clock className="w-3 h-3 text-slate-400 dark:text-slate-500 flex-shrink-0" />
            {formatRelativeAgo(event.recognized_at, nowMs)}
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
  enabled: boolean
  onExpand?: () => void
  onToggle?: () => void
  isSingle?: boolean
  isToggling?: boolean
}

function CameraCard({ name, location, isOnline, camId, enabled, onExpand, onToggle, isToggling }: CameraCardProps & { enabled: boolean; onToggle?: () => void; isToggling?: boolean }) {
  const imgRef = useRef<HTMLImageElement>(null)
  const [streamUrl, setStreamUrl] = useState(() => `/video_feed/${camId}`)
  const [hasError, setHasError] = useState(false)

  useEffect(() => {
    setStreamUrl(`/video_feed/${camId}`)
    setHasError(false)
  }, [camId])

  const refreshStream = useCallback(() => {
    setHasError(false)
    setStreamUrl(`/video_feed/${camId}?t=${Date.now()}`)
  }, [camId])

  return (
    <div className="bg-slate-900 rounded-2xl overflow-hidden border border-slate-800 hover:border-blue-500/40 transition-all flex flex-col h-full group relative shadow-md">
      {/* Video Viewport */}
      <div className="relative flex-1 bg-black overflow-hidden flex items-center justify-center min-h-[160px]">
        {isOnline && !hasError ? (
          <img
            ref={imgRef}
            src={streamUrl}
            alt={`${name} live feed`}
            className="w-full h-full object-contain bg-black"
            onError={() => setHasError(true)}
          />
        ) : (
          <div className="flex flex-col items-center justify-center h-full p-4 text-center space-y-2 text-slate-500">
            <CameraIcon className="w-8 h-8 opacity-40" />
            <span className="text-xs font-semibold">Camera Stream Offline</span>
            <button
              onClick={refreshStream}
              className="text-[11px] font-semibold text-blue-400 hover:text-blue-300 flex items-center gap-1 mt-1"
            >
              <RefreshCw className="w-3 h-3" /> Retry Stream
            </button>
          </div>
        )}

        {/* Gradient Overlay */}
        <div className="cam-overlay" />

        {/* Top Overlay Badges */}
        <div className="absolute top-2.5 left-2.5 flex items-center gap-2">
          {isOnline && !hasError && (
            <div className="flex items-center gap-1.5 bg-black/70 backdrop-blur-md rounded-full px-2.5 py-0.5 border border-white/10">
              <span className="live-dot w-1.5 h-1.5" />
              <span className="text-[10px] font-bold text-red-400 tracking-wider">LIVE</span>
            </div>
          )}
          <span className="text-[10px] font-bold px-2.5 py-0.5 rounded-full bg-black/60 text-slate-200 backdrop-blur-md border border-white/10">
            {name}
          </span>
        </div>

        {/* Actions */}
        <div className="absolute top-2.5 right-2.5 flex items-center gap-2 opacity-100 z-10">
          <button
            onClick={onToggle}
            disabled={isToggling}
            className={clsx(
              'flex items-center gap-2 rounded-full px-3 py-1 text-[11px] font-semibold transition-all border',
              enabled
                ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30 hover:bg-emerald-500/25'
                : 'bg-slate-800/90 text-slate-300 border-slate-700 hover:bg-slate-700'
            )}
            title="Toggle recognition on/off"
          >
            <span className={clsx(
              'w-2.5 h-2.5 rounded-full',
              enabled ? 'bg-emerald-400' : 'bg-slate-500'
            )} />
            {enabled ? 'ON' : 'OFF'}
          </button>
          <button
            onClick={refreshStream}
            className="w-7 h-7 rounded-xl bg-black/70 backdrop-blur-md flex items-center justify-center text-white hover:bg-blue-600 transition-colors border border-white/10"
            title="Refresh Stream"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
          {onExpand && (
            <button
              onClick={onExpand}
              className="w-7 h-7 rounded-xl bg-black/70 backdrop-blur-md flex items-center justify-center text-white hover:bg-blue-600 transition-colors border border-white/10"
              title="Focus Camera"
            >
              <Maximize2 className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Footer Info */}
      <div className="px-3.5 py-2.5 flex items-center justify-between border-t border-slate-800/80 bg-slate-900/90 backdrop-blur-md flex-shrink-0">
        <div className="min-w-0">
          <div className="text-xs font-bold text-white truncate">{name}</div>
          <div className="text-[10px] text-slate-400 truncate">{location} • ID: {camId}</div>
        </div>
        <div className="flex flex-col items-end gap-2">
          <Badge variant={isOnline && !hasError ? 'success' : 'danger'} dot size="sm">
            {isOnline && !hasError ? 'Online' : 'Offline'}
          </Badge>
          {onToggle ? (
            <button
              onClick={onToggle}
              disabled={isToggling}
              className={clsx(
                'text-[11px] font-semibold px-3 py-1 rounded-full transition-colors border',
                enabled
                  ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25 hover:bg-emerald-500/25'
                  : 'bg-slate-800 text-slate-300 border-slate-700 hover:bg-slate-700'
              )}
            >
              {enabled ? 'Recognition ON' : 'Recognition OFF'}
            </button>
          ) : null}
        </div>
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
  const [showBrowserCam, setShowBrowserCam] = useState(false)
  const [nowMs, setNowMs] = useState(() => Date.now())

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

  useEffect(() => {
    const tick = setInterval(() => setNowMs(Date.now()), 1000)
    return () => clearInterval(tick)
  }, [])

  const uniqueEvents = latestEventsByPerson(events)

  const filteredCams = cameras.filter(c => {
    const matchSearch =
      c.name.toLowerCase().includes(search.toLowerCase()) ||
      c.location.toLowerCase().includes(search.toLowerCase()) ||
      c.id.toLowerCase().includes(search.toLowerCase())
    const isLive = !!(c as any).is_active || (c.enabled && c.status !== 'OFFLINE')
    const matchStatus =
      statusFilter === 'all' ||
      (statusFilter === 'online' && isLive) ||
      (statusFilter === 'offline' && !isLive)
    return matchSearch && matchStatus
  })

  const getAutoGridClass = () => {
    if (layout === '1x1') return 'grid-cols-1 grid-rows-1 h-full'
    if (layout === '2x2') return 'grid-cols-2 grid-rows-2 h-full'
    if (layout === '3x3') return 'grid-cols-3 grid-rows-3 h-full'
    const count = filteredCams.length + (showBrowserCam ? 1 : 0)
    if (count <= 1) return 'grid-cols-1 grid-rows-1 h-full'
    if (count === 2) return 'grid-cols-2 grid-rows-1 h-full'
    if (count <= 4) return 'grid-cols-2 grid-rows-2 h-full'
    if (count <= 6) return 'grid-cols-3 grid-rows-2 h-full'
    return 'grid-cols-3 grid-rows-3 h-full'
  }

  const [togglingCameraId, setTogglingCameraId] = useState<string | null>(null)

  const toggleCameraRecognition = async (cam: any) => {
    const camId = cam.id || cam.camera_id
    if (!camId) return
    setTogglingCameraId(camId)
    try {
      await updateCamera(camId, {
        id: camId,
        camera_id: camId,
        name: cam.name,
        location: cam.location,
        description: cam.description || '',
        brand: cam.brand || 'Custom',
        ip_address: cam.ip_address || '',
        port: cam.port || 554,
        username: cam.username || '',
        password: cam.password || '',
        channel: cam.channel || 1,
        stream_type: cam.stream_type || 'sub',
        enabled: !cam.enabled,
        rotation: cam.rotation || 0,
        source: cam.source || '',
      })
      await getCameras().then(setCameras)
    } catch (err) {
      console.error('Failed to toggle camera recognition:', err)
    } finally {
      setTogglingCameraId(null)
    }
  }

  return (
    <div className="flex flex-col h-full overflow-hidden bg-transparent text-slate-900 dark:text-slate-100">
      <TopBar title="Live Recognition Operations" />

      {/* Control Toolbar */}
      <div className="px-6 py-3 border-b border-slate-200 dark:border-slate-800/80 flex items-center justify-between gap-3 flex-wrap bg-white/60 dark:bg-slate-900/60 backdrop-blur-xl flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
            <input
              className="input-field pl-9 w-44 py-1.5 text-xs"
              placeholder="Search cameras..."
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>

          {/* Filter Pills */}
          <div className="flex items-center gap-1 bg-slate-100 dark:bg-slate-900 p-1 rounded-xl border border-slate-200 dark:border-slate-700">
            {(['online', 'all', 'offline'] as const).map(f => (
              <button
                key={f}
                onClick={() => setStatusFilter(f)}
                className={clsx(
                  'px-3 py-1 rounded-lg text-xs font-semibold capitalize transition-all cursor-pointer',
                  statusFilter === f
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100'
                )}
              >
                {f === 'online' ? `Online (${cameras.filter(c => c.enabled && c.status !== 'OFFLINE').length})` : f}
              </button>
            ))}
          </div>
        </div>

        {/* Layout & Webcam Options */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1 bg-slate-100 dark:bg-slate-900 p-1 rounded-xl border border-slate-200 dark:border-slate-700">
            <button
              onClick={() => setLayout('auto')}
              className={clsx(
                'px-3 py-1 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer',
                layout === 'auto'
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100'
              )}
              title="Auto-Fit Grid"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>Auto Grid</span>
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
                  'w-7 h-7 rounded-lg flex items-center justify-center transition-all cursor-pointer',
                  layout === l
                    ? 'bg-blue-600 text-white'
                    : 'text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100'
                )}
                title={`${l} Grid Layout`}
              >
                <Icon className="w-3.5 h-3.5" />
              </button>
            ))}
          </div>

          <button
            onClick={() => setShowBrowserCam(v => !v)}
            className={clsx(
              'px-3 py-1.5 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all border cursor-pointer',
              showBrowserCam
                ? 'bg-emerald-600 text-white border-emerald-500 shadow-md'
                : 'bg-white text-slate-600 border-slate-200 hover:border-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700 dark:hover:border-slate-600'
            )}
          >
            <CameraIcon className="w-3.5 h-3.5" />
            {showBrowserCam ? 'USB Cam: Active' : 'Use USB Webcam'}
          </button>
        </div>
      </div>

      {/* Operational Workspace Layout */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Side: Camera Video Grid (75%) */}
        <div className="flex-1 p-4 flex flex-col min-w-0 overflow-hidden">
          <div className={clsx('grid gap-3 flex-1 min-h-0', getAutoGridClass())}>
            {showBrowserCam && (
              <BrowserWebcam onRecognized={() => getRecognitions(30).then(setEvents).catch(() => {})} />
            )}
            {filteredCams.map((cam) => {
              const camId = cam.id || cam.camera_id
              return (
                <CameraCard
                  key={camId}
                  camId={camId}
                  name={cam.name}
                  location={cam.location}
                  enabled={cam.enabled}
                  isOnline={cam.enabled && cam.status !== 'OFFLINE'}
                  onExpand={() => setLayout('1x1')}
                  onToggle={() => toggleCameraRecognition(cam)}
                  isToggling={togglingCameraId === camId}
                  isSingle={filteredCams.length === 1}
                />
              )
            })}

            {filteredCams.length === 0 && !showBrowserCam && (
              <EmptyState
                icon={<CameraIcon className="w-10 h-10" />}
                title="No Active Camera Feeds"
                description="Adjust view filter or enable cameras in Camera Management to view live feeds."
                className="col-span-full h-full"
              />
            )}
          </div>
        </div>

        {/* Right Side: Live Recognition Feed (25%) */}
        <div className="w-84 flex-shrink-0 border-l border-slate-200 dark:border-slate-800/80 flex flex-col overflow-hidden bg-white/60 dark:bg-slate-900/60 backdrop-blur-xl">
          <div className="px-4 py-3.5 border-b border-slate-200 dark:border-slate-800/80 flex items-center justify-between flex-shrink-0">
            <h3 className="text-xs font-bold text-slate-900 dark:text-white uppercase tracking-wider flex items-center gap-2">
              <Radio className="w-4 h-4 text-emerald-505 dark:text-emerald-400 animate-pulse" /> Live Detection Stream
            </h3>
            <Badge variant="info" size="sm">{uniqueEvents.length} People</Badge>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
            {uniqueEvents.map(evt => (
              <RecognitionCard key={evt.person_id} event={evt} nowMs={nowMs} />
            ))}
            {uniqueEvents.length === 0 && (
              <EmptyState
                icon={<Eye className="w-7 h-7" />}
                title="Awaiting Detections"
                description="Live facial recognition events will stream here automatically."
              />
            )}
          </div>
        </div>
      </div>

      {/* Operator Footer Status */}
      <div className="px-6 py-2 border-t border-slate-200 dark:border-slate-700/80 bg-slate-50 dark:bg-slate-900 flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400 flex-shrink-0">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400 font-semibold">
            <span className="online-dot w-1.5 h-1.5" /> Live Facial Ingestion Active
          </span>
          <span>•</span>
          <span>Active Camera Streams: {filteredCams.filter(c => c.enabled).length}</span>
        </div>
        <span className="font-mono text-slate-500">Security Control Room Workstation</span>
      </div>
    </div>
  )
}
