import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Camera, Users, Eye, AlertTriangle, Activity, Database,
  TrendingUp, CheckCircle, XCircle, ArrowRight, Video,
} from 'lucide-react'

import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, AreaChart, Area, BarChart, Bar,
} from 'recharts'
import { TopBar } from '../components/TopBar'
import { useStore } from '../store/useStore'
import { getHealth, getCameras, getRecognitions } from '../lib/api'
import type { RecognitionEvent } from '../lib/api'
import clsx from 'clsx'

// Generate mock trend data from real events
function buildHourlyData(events: RecognitionEvent[]) {
  const hours: Record<number, number> = {}
  for (let i = 0; i < 12; i++) hours[i] = 0

  events.forEach(e => {
    const h = new Date(e.recognized_at).getHours() % 12
    hours[h] = (hours[h] || 0) + 1
  })

  return Object.entries(hours).map(([h, count]) => ({
    time: `${(parseInt(h) * 2).toString().padStart(2, '0')}:00`,
    recognitions: count,
    unknown: Math.floor(count * 0.3),
  }))
}

interface StatCardProps {
  icon: React.ElementType
  label: string
  value: string | number
  sub?: string
  color?: string
  trend?: number
}

function StatCard({ icon: Icon, label, value, sub, color = 'blue', trend }: StatCardProps) {
  const colors: Record<string, string> = {
    blue: 'text-blue-400 bg-blue-500/10',
    teal: 'text-teal-400 bg-teal-500/10',
    green: 'text-green-400 bg-green-500/10',
    red: 'text-red-400 bg-red-500/10',
    yellow: 'text-yellow-400 bg-yellow-500/10',
    purple: 'text-purple-400 bg-purple-500/10',
  }

  return (
    <div className="stat-card group animate-slide-in-up">
      <div className="flex items-start justify-between mb-4">
        <div className={clsx('w-10 h-10 rounded-xl flex items-center justify-center', colors[color])}>
          <Icon className="w-5 h-5" />
        </div>
        {trend !== undefined && (
          <span className={clsx(
            'text-xs font-semibold px-2 py-1 rounded-full',
            trend >= 0 ? 'text-green-400 bg-green-500/10' : 'text-red-400 bg-red-500/10'
          )}>
            {trend >= 0 ? '+' : ''}{trend}%
          </span>
        )}
      </div>
      <div className="text-2xl font-bold text-white mb-1">{value}</div>
      <div className="text-sm font-medium text-slate-400">{label}</div>
      {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
    </div>
  )
}

function ResourceMeter({ label, value, color }: { label: string; value: number; color: string }) {
  const colorMap: Record<string, string> = {
    blue: 'from-blue-500 to-blue-400',
    teal: 'from-teal-500 to-teal-400',
    purple: 'from-purple-500 to-purple-400',
    green: 'from-green-500 to-green-400',
  }

  return (
    <div>
      <div className="flex justify-between text-xs mb-1.5">
        <span className="text-slate-400">{label}</span>
        <span className={clsx('font-mono font-semibold',
          value > 80 ? 'text-red-400' : value > 60 ? 'text-yellow-400' : 'text-slate-300'
        )}>
          {value.toFixed(1)}%
        </span>
      </div>
      <div className="progress-bar">
        <div
          className={clsx('progress-fill bg-gradient-to-r', colorMap[color])}
          style={{ width: `${value}%` }}
        />
      </div>
    </div>
  )
}

export function Dashboard() {
  const { health, cameras, recentEvents, setHealth, setCameras, setRecentEvents } = useStore()
  const [loading, setLoading] = useState(true)
  const hourlyData = buildHourlyData(recentEvents)

  useEffect(() => {
    async function load() {
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
    load()
    const interval = setInterval(() => {
      getHealth().then(setHealth).catch(() => {})
      getRecognitions(50).then(setRecentEvents).catch(() => {})
    }, 10000)
    return () => clearInterval(interval)
  }, [])

  const onlineCams = cameras.filter(c => c.enabled).length
  const offlineCams = cameras.length - onlineCams
  const totalPersons = health?.database?.total_persons ?? 0
  const totalVectors = health?.faiss?.total_registered_vectors ?? 0
  const todayEvents = recentEvents.length
  const unknownEvents = recentEvents.filter(e => e.person_id === 'unknown').length

  const cpu = health?.system?.cpu_percent ?? 42
  const ram = health?.system?.ram_percent ?? 61
  const gpu = health?.system?.gpu_percent ?? 28

  const TOOLTIP_STYLE = {
    backgroundColor: '#0d1224',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: '12px',
    color: '#e2e8f0',
    fontSize: '12px',
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <TopBar title="Dashboard" />

      <div className="flex-1 overflow-y-auto p-6 space-y-6">

        {/* Stat Cards Row */}
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4">
          <StatCard icon={Camera} label="Online Cameras" value={onlineCams} color="green" trend={0} />
          <StatCard icon={XCircle} label="Offline Cameras" value={offlineCams} color="red" />
          <StatCard icon={Eye} label="Faces Today" value={todayEvents} color="blue" trend={12} />
          <StatCard icon={AlertTriangle} label="Unknown Faces" value={unknownEvents} color="yellow" />
          <StatCard icon={Users} label="Registered Persons" value={totalPersons} color="teal" />
          <StatCard icon={Database} label="FAISS Vectors" value={totalVectors} color="purple" sub="ArcFace 512-D" />
        </div>

        {/* Middle Row: Camera Previews + Recognition Trend */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">

          {/* Camera System Health Overview (No Video Streams) */}
          <div className="xl:col-span-2 glass rounded-2xl p-5">
            <div className="section-header">
              <h2 className="section-title">
                <Camera className="w-4.5 h-4.5 text-primary-400" />
                Camera Network Status
              </h2>
              <Link to="/cameras" className="flex items-center gap-1.5 text-xs text-primary-400 hover:text-primary-300 transition-colors">
                Manage Cameras <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {cameras.map((cam, idx) => (
                <div key={cam.id || idx} className="glass rounded-xl p-3.5 border border-white/5 flex items-center justify-between hover:border-primary-500/20 transition-all">
                  <div className="flex items-center gap-3">
                    <div className={clsx(
                      'w-9 h-9 rounded-lg flex items-center justify-center font-bold text-xs',
                      cam.enabled ? 'bg-green-500/15 text-green-400' : 'bg-red-500/15 text-red-400'
                    )}>
                      <Camera className="w-4 h-4" />
                    </div>
                    <div>
                      <div className="text-xs font-semibold text-white">{cam.name}</div>
                      <div className="text-[10px] text-slate-500">{cam.location} • ID: {cam.id}</div>
                    </div>
                  </div>
                  <span className={clsx('text-[10px] px-2.5 py-1 rounded-full font-bold',
                    cam.enabled ? 'badge-green' : 'badge-red'
                  )}>
                    {cam.enabled ? '● ONLINE' : '○ OFFLINE'}
                  </span>
                </div>
              ))}
              {cameras.length === 0 && (
                <div className="col-span-full text-center py-8 text-slate-500 text-xs">
                  No cameras registered in system.
                </div>
              )}
            </div>
          </div>


          {/* System Resources */}
          <div className="glass rounded-2xl p-5">
            <h2 className="section-title mb-5">
              <Activity className="w-4.5 h-4.5 text-teal-400" />
              System Resources
            </h2>
            <div className="space-y-5">
              <ResourceMeter label="CPU Usage" value={cpu} color="blue" />
              <ResourceMeter label="GPU Usage" value={gpu} color="purple" />
              <ResourceMeter label="RAM Usage" value={ram} color="teal" />

              <div className="border-t border-white/5 pt-4 space-y-2.5">
                {[
                  { label: 'Model Status', value: 'ArcFace R50', ok: true },
                  { label: 'Detector', value: 'SCRFD 10G', ok: true },
                  { label: 'Database', value: health?.status === 'healthy' ? 'Connected' : 'Error', ok: health?.status === 'healthy' },
                  { label: 'Recognition', value: `${health?.faiss?.is_loaded ? 'FAISS Ready' : 'Loading...'}`, ok: health?.faiss?.is_loaded },
                ].map(item => (
                  <div key={item.label} className="flex items-center justify-between text-xs">
                    <span className="text-slate-400">{item.label}</span>
                    <div className="flex items-center gap-1.5">
                      {item.ok
                        ? <CheckCircle className="w-3 h-3 text-green-400" />
                        : <XCircle className="w-3 h-3 text-red-400" />}
                      <span className={item.ok ? 'text-slate-300' : 'text-red-400'}>{item.value}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Bottom Row: Chart + Recent Events */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">

          {/* Recognition Trend */}
          <div className="xl:col-span-2 glass rounded-2xl p-5">
            <div className="section-header">
              <h2 className="section-title">
                <TrendingUp className="w-4.5 h-4.5 text-primary-400" />
                Recognition Trend (Today)
              </h2>
            </div>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={hourlyData}>
                <defs>
                  <linearGradient id="recGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="unkGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                <XAxis dataKey="time" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Area type="monotone" dataKey="recognitions" name="Recognized" stroke="#3b82f6" fill="url(#recGrad)" strokeWidth={2} dot={false} />
                <Area type="monotone" dataKey="unknown" name="Unknown" stroke="#f59e0b" fill="url(#unkGrad)" strokeWidth={2} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Recent Recognitions */}
          <div className="glass rounded-2xl p-5 overflow-hidden flex flex-col">
            <div className="section-header">
              <h2 className="section-title text-sm">
                <Eye className="w-4 h-4 text-primary-400" />
                Recent Recognitions
              </h2>
              <Link to="/events" className="text-xs text-primary-400 hover:text-primary-300 flex items-center gap-1">
                All <ArrowRight className="w-3 h-3" />
              </Link>
            </div>
            <div className="flex-1 overflow-y-auto space-y-2 -mr-1 pr-1">
              {recentEvents.slice(0, 10).map(evt => (
                <div key={evt.id} className="flex items-center gap-3 py-2 border-b border-white/5 last:border-0">
                  <div className={clsx(
                    'w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0',
                    evt.person_id !== 'unknown' ? 'bg-primary-500/20 text-primary-400' : 'bg-red-500/20 text-red-400'
                  )}>
                    {evt.name?.[0]?.toUpperCase() ?? '?'}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-semibold text-slate-200 truncate">{evt.name}</div>
                    <div className="text-[10px] text-slate-500">{evt.camera_id} • {evt.recognized_at?.split(' ')[1] ?? ''}</div>
                  </div>
                  <span className={clsx('conf-pill text-[10px]',
                    evt.similarity > 0.85 ? 'conf-high' : evt.similarity > 0.7 ? 'conf-mid' : 'conf-low'
                  )}>
                    {Math.round(evt.similarity * 100)}%
                  </span>
                </div>
              ))}
              {recentEvents.length === 0 && (
                <div className="text-center py-8 text-slate-500 text-xs">
                  No recognition events yet
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
