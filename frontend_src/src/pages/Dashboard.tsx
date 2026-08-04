import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Camera, Users, Eye, AlertTriangle, Activity,
  TrendingUp, CheckCircle2, ArrowRight, Video, UserPlus,
  RefreshCw, Radio
} from 'lucide-react'

import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip
} from 'recharts'
import { TopBar } from '../components/TopBar'
import { useStore } from '../store/useStore'
import { getHealth, getCameras, getRecognitions, type RecognitionEvent, type CameraConfig } from '../lib/api'
import { Card, CardHeader, CardTitle, CardBody } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { StatCardSkeleton, CameraCardSkeleton, TableRowSkeleton } from '../components/ui/Skeleton'
import { EmptyState } from '../components/ui/EmptyState'
import { parseUtcTimestamp, formatRelativeAgo } from '../lib/datetime'
import clsx from 'clsx'

function buildHourlyData(events: RecognitionEvent[]) {
  const hours: Record<number, number> = {}
  for (let i = 0; i < 12; i++) hours[i] = 0

  events.forEach(e => {
    const dateObj = parseUtcTimestamp(e.recognized_at)
    if (dateObj) {
      const h = dateObj.getHours() % 12
      hours[h] = (hours[h] || 0) + 1
    }
  })

  return Object.entries(hours).map(([h, count]) => ({
    time: `${(parseInt(h) * 2).toString().padStart(2, '0')}:00`,
    recognitions: count,
    unknown: Math.floor(count * 0.25),
  }))
}

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

function DashboardEventItem({ event, nowMs }: { event: RecognitionEvent; nowMs: number }) {
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

  return (
    <div
      className={clsx(
        'p-2.5 rounded-xl border flex items-center gap-3 transition-all duration-150',
        isUnknown
          ? 'bg-amber-500/5 dark:bg-amber-950/20 border-amber-500/20 hover:border-amber-500/40'
          : 'bg-white/80 dark:bg-slate-900/80 border-slate-200 dark:border-slate-800 hover:border-blue-500/40'
      )}
    >
      {/* Profile Image / Initial */}
      <div className={clsx(
        'w-10 h-10 rounded-xl flex items-center justify-center font-bold text-xs flex-shrink-0 overflow-hidden border bg-slate-950',
        isUnknown
          ? 'border-amber-500/30 text-amber-400'
          : 'border-emerald-500/30 text-emerald-400'
      )}>
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
      </div>

      {/* Event Details */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-1 mb-0.5">
          <span className={clsx('text-xs font-bold truncate', isUnknown ? 'text-amber-600 dark:text-amber-300' : 'text-slate-900 dark:text-white')}>
            {isUnknown ? 'Unknown Person' : event.name}
          </span>
        </div>

        <div className="text-[10px] text-slate-500 dark:text-slate-400 flex items-center justify-between">
          <span className="truncate">{event.camera_id || 'CCTV Stream'}</span>
          <span className="font-mono text-[9px] text-slate-500 flex-shrink-0">
            {formatRelativeAgo(event.recognized_at, nowMs)}
          </span>
        </div>
      </div>
    </div>
  )
}

export function Dashboard() {
  const { health, cameras, recentEvents, setHealth, setCameras, setRecentEvents } = useStore()
  const [loading, setLoading] = useState(true)
  const [nowMs, setNowMs] = useState(() => Date.now())

  const loadData = async () => {
    try {
      const [h, c, events] = await Promise.all([getHealth(), getCameras(), getRecognitions(50)])
      setHealth(h)
      setCameras(c)
      setRecentEvents(events)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
    const interval = setInterval(loadData, 10000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    const tick = setInterval(() => setNowMs(Date.now()), 1000)
    return () => clearInterval(tick)
  }, [])

  // Sort cameras: Enabled/Online first
  const sortedCameras = [...cameras].sort((a, b) => {
    const aOnline = a.enabled && a.status !== 'OFFLINE' ? 1 : 0
    const bOnline = b.enabled && b.status !== 'OFFLINE' ? 1 : 0
    return bOnline - aOnline
  })

  const onlineCams = cameras.filter(c => c.enabled && c.status !== 'OFFLINE').length
  const totalCams = cameras.length
  const totalPersons = health?.database?.total_persons ?? 0
  const todayDetections = recentEvents.length
  const unknownAlerts = recentEvents.filter(e => e.person_id === 'unknown').length

  const hourlyData = buildHourlyData(recentEvents)

  return (
    <div className="flex flex-col h-full overflow-hidden bg-transparent text-slate-900 dark:text-slate-100">
      <TopBar title="Security Operations Center" />

      <div className="flex-1 p-4 md:p-6 space-y-6 overflow-y-auto">
        {/* Quick Action Banner */}
        <div className="bg-white/80 dark:bg-slate-900/80 border border-slate-200 dark:border-slate-800 rounded-3xl p-5 md:p-6 backdrop-blur-xl shadow-2xl flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-xs font-bold text-blue-500 dark:text-blue-400 uppercase tracking-wider mb-1">
              <Radio className="w-3.5 h-3.5 animate-pulse" /> Live Surveillance Feed
            </div>
            <h2 className="text-xl font-bold text-slate-900 dark:text-white tracking-tight">Enterprise CCTV Control Room</h2>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Real-time facial detection, identity verification, and multi-camera stream analytics.</p>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            <Link to="/register">
              <Button variant="primary" icon={<UserPlus className="w-4 h-4" />}>
                Register Person
              </Button>
            </Link>
            <Link to="/live">
              <Button variant="secondary" icon={<Video className="w-4 h-4" />}>
                Live Monitor
              </Button>
            </Link>
            <Button
              variant="ghost"
              size="sm"
              icon={<RefreshCw className="w-3.5 h-3.5" />}
              onClick={loadData}
              title="Refresh Dashboard"
            />
          </div>
        </div>

        {/* Operator Priority KPI Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {loading ? (
            <>
              <StatCardSkeleton />
              <StatCardSkeleton />
              <StatCardSkeleton />
              <StatCardSkeleton />
            </>
          ) : (
            <>
              {/* Card 1: Camera Network */}
              <Card className="hover:border-blue-500/40 transition-all group">
                <CardBody className="p-5">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Camera Network</span>
                    <div className="w-9 h-9 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
                      <Camera className="w-4.5 h-4.5" />
                    </div>
                  </div>
                  <div className="text-2xl font-bold text-slate-900 dark:text-slate-100 mb-1">
                    {onlineCams} <span className="text-sm font-normal text-slate-500 dark:text-slate-400">/ {totalCams}</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-emerald-400 font-medium">
                    <CheckCircle2 className="w-3.5 h-3.5" /> {onlineCams} Cameras Online & Ingesting
                  </div>
                </CardBody>
              </Card>

              {/* Card 2: Registered Profiles */}
              <Card className="hover:border-teal-500/40 transition-all group">
                <CardBody className="p-5">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Registered Persons</span>
                    <div className="w-9 h-9 rounded-xl bg-teal-500/10 border border-teal-500/20 flex items-center justify-center text-teal-400">
                      <Users className="w-4.5 h-4.5" />
                    </div>
                  </div>
                  <div className="text-2xl font-bold text-slate-900 dark:text-slate-100 mb-1">{totalPersons}</div>
                  <div className="text-xs text-slate-400 font-medium">
                    Enrolled Identity Profiles
                  </div>
                </CardBody>
              </Card>

              {/* Card 3: Today's Detections */}
              <Card className="hover:border-purple-500/40 transition-all group">
                <CardBody className="p-5">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Detections Today</span>
                    <div className="w-9 h-9 rounded-xl bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400">
                      <Activity className="w-4.5 h-4.5" />
                    </div>
                  </div>
                  <div className="text-2xl font-bold text-slate-900 dark:text-slate-100 mb-1">{todayDetections}</div>
                  <div className="flex items-center gap-1 text-xs text-blue-400 font-medium">
                    <TrendingUp className="w-3.5 h-3.5" /> Active Face Recognition Logs
                  </div>
                </CardBody>
              </Card>

              {/* Card 4: Attention Alerts */}
              <Card className="hover:border-amber-500/40 transition-all group">
                <CardBody className="p-5">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Attention Events</span>
                    <div className="w-9 h-9 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
                      <AlertTriangle className="w-4.5 h-4.5" />
                    </div>
                  </div>
                  <div className="text-2xl font-bold text-slate-900 dark:text-slate-100 mb-1">{unknownAlerts}</div>
                  <div className="text-xs text-amber-400 font-medium">
                    Unregistered / Unknown Faces Logged
                  </div>
                </CardBody>
              </Card>
            </>
          )}
        </div>

        {/* Live Camera Network Grid & Recent Activity */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Camera Network Section (2 cols) */}
          <div className="lg:col-span-2 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider flex items-center gap-2">
                <Camera className="w-4 h-4 text-blue-500 dark:text-blue-400" /> Active Surveillance Cameras ({onlineCams}/{totalCams})
              </h3>
              <Link to="/cameras" className="text-xs font-semibold text-blue-500 hover:text-blue-400 dark:text-blue-400 dark:hover:text-blue-300 flex items-center gap-1">
                Manage Cameras <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>

            {loading ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <CameraCardSkeleton />
                <CameraCardSkeleton />
              </div>
            ) : sortedCameras.length === 0 ? (
              <EmptyState
                icon={<Camera className="w-8 h-8" />}
                title="No Cameras Configured"
                description="Add your first CCTV RTSP stream or webcam to begin live facial recognition monitoring."
                action={
                  <Link to="/cameras">
                    <Button variant="primary" size="sm">+ Add Camera</Button>
                  </Link>
                }
              />
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {sortedCameras.slice(0, 4).map((cam) => {
                  const isOnline = cam.enabled && cam.status !== 'OFFLINE'
                  const camId = cam.id || cam.camera_id
                  return (
                    <div
                      key={camId}
                      className="group relative bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl overflow-hidden hover:border-blue-500/40 transition-all shadow-md flex flex-col justify-between"
                    >
                      <div className="relative aspect-video bg-black flex items-center justify-center overflow-hidden">
                        {isOnline ? (
                          <img
                            src={`/video_feed/${camId}`}
                            alt={cam.name}
                            className="w-full h-full object-contain"
                            onError={(e) => {
                              // Fallback on stream error
                              (e.target as HTMLElement).style.display = 'none'
                            }}
                          />
                        ) : (
                          <div className="flex flex-col items-center justify-center text-slate-500 space-y-1">
                            <Camera className="w-8 h-8 opacity-40" />
                            <span className="text-[11px] font-semibold">Stream Offline</span>
                          </div>
                        )}

                        {/* Top Badges */}
                        <div className="absolute top-2.5 left-2.5 flex items-center gap-1.5">
                          <Badge variant={isOnline ? 'success' : 'danger'} dot size="sm">
                            {isOnline ? 'LIVE' : 'OFFLINE'}
                          </Badge>
                          <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-black/60 text-slate-200 backdrop-blur-md border border-white/10">
                            {cam.name}
                          </span>
                        </div>
                      </div>

                      <div className="p-3 bg-slate-50/90 dark:bg-slate-900/90 flex items-center justify-between text-xs">
                        <div className="truncate">
                          <div className="font-bold text-slate-900 dark:text-white truncate">{cam.name}</div>
                          <div className="text-[10px] text-slate-500 dark:text-slate-400 truncate">{cam.location || 'Default Location'}</div>
                        </div>
                        <Link to={`/live?cam=${camId}`}>
                          <Button variant="ghost" size="sm" icon={<Eye className="w-3.5 h-3.5" />}>
                            View
                          </Button>
                        </Link>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}

            {/* Recognition Trend Chart */}
            <Card>
              <CardHeader>
                <CardTitle icon={<Activity className="w-4 h-4 text-blue-400" />}>
                  Recognition Activity Trend
                </CardTitle>
                <Badge variant="neutral">24h History</Badge>
              </CardHeader>
              <CardBody className="p-4 h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={hourlyData}>
                    <defs>
                      <linearGradient id="colorRec" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4} />
                        <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                    <XAxis dataKey="time" stroke="#64748b" fontSize={10} />
                    <YAxis stroke="#64748b" fontSize={10} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: '#0f172a',
                        borderColor: '#334155',
                        borderRadius: '12px',
                        fontSize: '11px',
                        color: '#f8fafc'
                      }}
                    />
                    <Area type="monotone" dataKey="recognitions" stroke="#3b82f6" strokeWidth={2} fillOpacity={1} fill="url(#colorRec)" />
                  </AreaChart>
                </ResponsiveContainer>
              </CardBody>
            </Card>
          </div>

          {/* Right Column: Live Recognition Feed */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider flex items-center gap-2">
                <Radio className="w-4 h-4 text-emerald-500 dark:text-emerald-400 animate-pulse" /> Live Detection Stream
              </h3>
              <Link to="/events" className="text-xs font-semibold text-blue-500 hover:text-blue-400 dark:text-blue-400 dark:hover:text-blue-300">
                View All Logs
              </Link>
            </div>

            <Card className="h-[580px] flex flex-col">
              <CardBody className="p-3 flex-1 overflow-y-auto space-y-2.5">
                {loading ? (
                  <>
                    <TableRowSkeleton />
                    <TableRowSkeleton />
                    <TableRowSkeleton />
                  </>
                ) : recentEvents.length === 0 ? (
                  <EmptyState
                    icon={<Eye className="w-7 h-7" />}
                    title="No Detections Yet"
                    description="Live face recognition matches will appear here automatically."
                  />
                ) : (
                  latestEventsByPerson(recentEvents).slice(0, 15).map((event) => (
                    <DashboardEventItem key={event.person_id} event={event} nowMs={nowMs} />
                  ))
                )}
              </CardBody>
            </Card>
          </div>
        </div>
      </div>
    </div>
  )
}
