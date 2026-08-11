import { useCallback, useEffect, useState } from 'react'
import {
  Search, Download, ChevronDown, ChevronUp, Clock,
  Camera as CameraIcon, User, List, Grid, Maximize2, X, RefreshCw,
  Calendar, Filter, UserCheck, UserPlus, HelpCircle, Users
} from 'lucide-react'

import { TopBar } from '../components/TopBar'
import { getRecognitions, getRecognitionSummaries, getRecognitionDates } from '../lib/api'
import type { RecognitionEvent, RecognitionPersonSummary, RecognitionDateItem } from '../lib/api'
import { Badge } from '../components/ui/Badge'
import { formatLocalDateTime, formatLocalTime } from '../lib/datetime'
import clsx from 'clsx'

function PersonAvatar({ personId, name, faceSnapshotUrl }: { personId: string; name: string; faceSnapshotUrl?: string }) {
  const isUnknown = personId === 'unknown'
  const isVisitor = personId.startsWith('VISITOR')

  const getInitialSrc = () => {
    if (isUnknown) return ''
    if (faceSnapshotUrl) return faceSnapshotUrl
    if (isVisitor) {
      if (personId.includes('_')) {
        return `/faces/visitors/2026-08-11/${personId}/primary_avatar.jpg`
      }
      const parts = personId.split('-')
      if (parts.length >= 2) {
        return `/faces/visitors/${parts[1]}/${personId}/primary_avatar.jpg`
      }
    }
    return `/faces/${personId}/sample_1_frontal.jpg`
  }

  const [imgSrc, setImgSrc] = useState<string>(getInitialSrc)
  const [imgError, setImgError] = useState(false)

  const handleImgError = () => {
    if (faceSnapshotUrl && imgSrc === faceSnapshotUrl) {
      if (isVisitor) {
        const parts = personId.split('-')
        if (parts.length >= 2) {
          setImgSrc(`/faces/visitors/${parts[1]}/${personId}/primary_avatar.jpg`)
          return
        }
      }
      setImgSrc(`/faces/${personId}/sample_1_frontal.jpg`)
    } else if (imgSrc.endsWith('primary_avatar.jpg')) {
      setImgSrc(`/faces/${personId}/sample_1_frontal.jpg`)
    } else if (imgSrc.endsWith('sample_1_frontal.jpg')) {
      setImgSrc(`/faces/${personId}/sample_1.jpg`)
    } else if (imgSrc.endsWith('sample_1.jpg')) {
      setImgSrc(`/faces/${personId}/uploaded_1.jpg`)
    } else if (imgSrc.endsWith('uploaded_1.jpg')) {
      setImgSrc(`/faces/${personId}/snapshot_1.jpg`)
    } else {
      setImgError(true)
    }
  }

  if (isUnknown || imgError || !imgSrc) {
    return (
      <div className="w-12 h-12 rounded-xl flex items-center justify-center font-bold text-sm bg-slate-100 dark:bg-slate-900 border border-slate-200 dark:border-white/5 text-slate-500 dark:text-slate-400">
        <User className="w-5 h-5" />
      </div>
    )
  }

  return (
    <img
      src={imgSrc}
      alt={name}
      onError={handleImgError}
      className="w-12 h-12 rounded-xl object-cover border border-slate-200 dark:border-white/10 bg-slate-950 shadow-md"
    />
  )
}


export function Events() {
  const [summaries, setSummaries] = useState<RecognitionPersonSummary[]>([])
  const [events, setEvents] = useState<RecognitionEvent[]>([])
  const [personEvents, setPersonEvents] = useState<Record<string, RecognitionEvent[]>>({})
  const [loadingPersonEvents, setLoadingPersonEvents] = useState<Record<string, boolean>>({})
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [viewMode, setViewMode] = useState<'grouped' | 'flat'>('grouped')
  const [category, setCategory] = useState<'all' | 'registered' | 'visitor' | 'unknown'>('all')
  const [selectedDate, setSelectedDate] = useState<string>('all')
  const [datesList, setDatesList] = useState<RecognitionDateItem[]>([])
  const [expandedPersons, setExpandedPersons] = useState<Record<string, boolean>>({})
  const [lightboxImage, setLightboxImage] = useState<string | null>(null)

  // Fetch available operational dates on mount
  useEffect(() => {
    getRecognitionDates().then(data => {
      setDatesList(data || [])
    }).catch(console.error)
  }, [])

  const loadData = useCallback(async () => {
    try {
      if (viewMode === 'grouped') {
        const data = await getRecognitionSummaries(search || undefined, selectedDate, category)
        setSummaries(data || [])
      } else {
        const data = await getRecognitions(500, undefined, selectedDate, category)
        setEvents(data || [])
      }
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [viewMode, search, selectedDate, category])

  useEffect(() => {
    setLoading(true)
    loadData()
    const interval = setInterval(loadData, 8000)
    return () => clearInterval(interval)
  }, [loadData])

  const loadPersonHistory = async (personId: string) => {
    if (personEvents[personId]?.length) return
    setLoadingPersonEvents(prev => ({ ...prev, [personId]: true }))
    try {
      const data = await getRecognitions(100, personId, selectedDate, category)
      setPersonEvents(prev => ({ ...prev, [personId]: data || [] }))
    } catch (e) {
      console.error(e)
      setPersonEvents(prev => ({ ...prev, [personId]: [] }))
    } finally {
      setLoadingPersonEvents(prev => ({ ...prev, [personId]: false }))
    }
  }

  const toggleExpand = async (personId: string) => {
    const willExpand = !expandedPersons[personId]
    setExpandedPersons(prev => ({
      ...prev,
      [personId]: willExpand
    }))
    if (willExpand) {
      await loadPersonHistory(personId)
    }
  }

  const filteredFlat = events.filter(e =>
    e.name.toLowerCase().includes(search.toLowerCase()) ||
    e.person_id.toLowerCase().includes(search.toLowerCase()) ||
    e.camera_id.toLowerCase().includes(search.toLowerCase())
  )

  const exportCSV = () => {
    const headers = ['ID', 'Person ID', 'Name', 'Similarity', 'Track ID', 'Camera ID', 'Timestamp']
    const source = viewMode === 'flat'
      ? filteredFlat
      : Object.values(personEvents).flat()
    const rows = (source.length ? source : filteredFlat).map(e => [
      e.id, e.person_id, `"${e.name}"`, e.similarity, e.track_id, e.camera_id, `"${formatLocalDateTime(e.recognized_at)}"`
    ])
    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(r => r.join(','))].join('\n')
    const encodedUri = encodeURI(csvContent)
    const link = document.createElement('a')
    link.setAttribute('href', encodedUri)
    link.setAttribute('download', `recognition_events_${Date.now()}.csv`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <TopBar title="Recognition Events" />

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Category Filter Pills & Toolbar */}
        <div className="flex flex-col lg:flex-row items-stretch lg:items-center justify-between gap-4 bg-white/40 dark:bg-slate-900/40 p-3 rounded-2xl border border-slate-200 dark:border-white/5">
          {/* Category Filter Pills */}
          <div className="flex items-center gap-1.5 overflow-x-auto pb-1 lg:pb-0">
            <button
              onClick={() => setCategory('all')}
              className={clsx(
                'px-4 py-2 rounded-xl text-xs font-bold flex items-center gap-2 transition-all whitespace-nowrap',
                category === 'all'
                  ? 'bg-blue-600 text-white shadow-lg shadow-blue-600/20'
                  : 'text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-white/5'
              )}
            >
              <Users className="w-3.5 h-3.5" /> All Recognitions
            </button>

            <button
              onClick={() => setCategory('registered')}
              className={clsx(
                'px-4 py-2 rounded-xl text-xs font-bold flex items-center gap-2 transition-all whitespace-nowrap',
                category === 'registered'
                  ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-600/20'
                  : 'text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-white/5'
              )}
            >
              <UserCheck className="w-3.5 h-3.5" /> Registered Persons
            </button>

            <button
              onClick={() => setCategory('visitor')}
              className={clsx(
                'px-4 py-2 rounded-xl text-xs font-bold flex items-center gap-2 transition-all whitespace-nowrap',
                category === 'visitor'
                  ? 'bg-amber-600 text-white shadow-lg shadow-amber-600/20'
                  : 'text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-white/5'
              )}
            >
              <UserPlus className="w-3.5 h-3.5" /> Visitors (Unregistered)
            </button>

            <button
              onClick={() => setCategory('unknown')}
              className={clsx(
                'px-4 py-2 rounded-xl text-xs font-bold flex items-center gap-2 transition-all whitespace-nowrap',
                category === 'unknown'
                  ? 'bg-slate-700 text-white shadow-lg shadow-slate-700/20'
                  : 'text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-white/5'
              )}
            >
              <HelpCircle className="w-3.5 h-3.5" /> Unknown
            </button>
          </div>

          {/* Date Selector & View Controls */}
          <div className="flex items-center gap-3">
            {/* Date-wise Selector */}
            <div className="relative flex items-center">
              <Calendar className="absolute left-3 w-4 h-4 text-blue-500 pointer-events-none" />
              <select
                value={selectedDate}
                onChange={e => setSelectedDate(e.target.value)}
                className="input-field pl-9 pr-8 text-xs font-semibold bg-white dark:bg-slate-900 border-slate-200 dark:border-white/10 text-slate-800 dark:text-white appearance-none cursor-pointer"
              >
                <option value="all">All Dates History</option>
                {datesList.map(d => (
                  <option key={d.date_key} value={d.date_key}>
                    {d.date_formatted} {d.is_today ? '(Today)' : ''} ({d.count} events)
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
            </div>

            {/* View Mode Switch */}
            <div className="flex items-center gap-1 bg-white/60 dark:bg-slate-900/60 p-1 rounded-xl border border-slate-200 dark:border-white/5">
              <button
                onClick={() => setViewMode('grouped')}
                className={clsx(
                  'px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all',
                  viewMode === 'grouped'
                    ? 'bg-blue-600 text-white shadow'
                    : 'text-slate-500 dark:text-slate-400 hover:text-white'
                )}
                title="Group by Person"
              >
                <Grid className="w-3.5 h-3.5" /> Grouped
              </button>
              <button
                onClick={() => setViewMode('flat')}
                className={clsx(
                  'px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all',
                  viewMode === 'flat'
                    ? 'bg-blue-600 text-white shadow'
                    : 'text-slate-500 dark:text-slate-400 hover:text-white'
                )}
                title="Flat chronological list"
              >
                <List className="w-3.5 h-3.5" /> List
              </button>
            </div>
          </div>
        </div>

        {/* Search Bar & Export Controls */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              className="input-field pl-9"
              placeholder="Search by name, ID, or camera..."
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>

          <div className="flex items-center gap-3">
            <button onClick={() => { setLoading(true); loadData() }} className="btn-secondary whitespace-nowrap">
              <RefreshCw className="w-4 h-4" /> Refresh
            </button>

            <button onClick={exportCSV} className="btn-secondary whitespace-nowrap">
              <Download className="w-4 h-4" /> Export CSV
            </button>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center p-12 text-slate-400 text-sm font-medium">
            Loading recognition events...
          </div>
        ) : viewMode === 'grouped' ? (

          <div className="space-y-4">
            {summaries.map(group => {
              const isExpanded = expandedPersons[group.person_id]
              const isUnknown = group.person_id === 'unknown'
              const avgPct = Math.round(group.avg_confidence * 100)
              const detailEvents = personEvents[group.person_id] || []
              const detailLoading = loadingPersonEvents[group.person_id]

              return (
                <div
                  key={group.person_id}
                  className={clsx(
                    'glass rounded-2xl overflow-hidden border transition-all duration-200 shadow-sm',
                    isExpanded ? 'border-slate-300 dark:border-white/10' : 'border-slate-200 dark:border-white/5 hover:border-slate-300 dark:hover:border-white/10 hover:shadow-md'
                  )}
                >
                  <div
                    onClick={() => toggleExpand(group.person_id)}
                    className="flex items-center justify-between p-4 cursor-pointer select-none hover:bg-slate-50 dark:hover:bg-white/5 transition-colors gap-4"
                  >
                    <div className="flex items-center gap-4 min-w-0">
                      <PersonAvatar personId={group.person_id} name={group.name} faceSnapshotUrl={(group as any).face_snapshot_url} />
                      <div className="min-w-0">
                        <h4 className={clsx('font-bold leading-snug truncate', isUnknown ? 'text-amber-400' : 'text-slate-900 dark:text-white')}>
                          {group.name}
                        </h4>
                        <p className="text-[10px] text-slate-400 font-mono mt-0.5 truncate">
                          ID: {group.person_id}
                        </p>
                      </div>
                    </div>

                    <div className="hidden md:flex items-center gap-5 text-slate-500 dark:text-slate-400 text-xs">
                      <div>
                        <div className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-0.5">Duration</div>
                        <div className="font-bold text-emerald-400 font-mono">
                          {group.total_duration || '0m'}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-0.5">Visits</div>
                        <div className="font-bold text-slate-200 font-mono text-center">
                          {group.visit_count ?? 1}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-0.5">Status</div>
                        <span className={clsx(
                          'px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider inline-flex items-center gap-1.5',
                          group.is_currently_present || group.status === 'Live'
                            ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                            : 'bg-slate-800/80 text-slate-400 border border-slate-700'
                        )}>
                          {(group.is_currently_present || group.status === 'Live') && (
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                          )}
                          {group.status || (group.is_currently_present ? 'Live' : 'Offline')}
                        </span>
                      </div>
                      <div>
                        <div className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-0.5">Last Camera</div>
                        <div className="font-mono text-slate-700 dark:text-slate-300">{group.last_seen_camera}</div>
                      </div>
                      <div>
                        <div className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-0.5">Avg Conf</div>
                        <span className={`conf-pill text-[10px] ${
                          group.avg_confidence >= 0.85 ? 'conf-high' : group.avg_confidence >= 0.7 ? 'conf-mid' : 'conf-low'
                        }`}>
                          {avgPct}%
                        </span>
                      </div>
                      <div>
                        <div className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-0.5">First Seen</div>
                        <div className="text-slate-700 dark:text-slate-300 flex items-center gap-1" title={group.first_seen_camera ? `Camera: ${group.first_seen_camera}` : undefined}>
                          <Clock className="w-3.5 h-3.5 text-slate-400 dark:text-slate-500" />
                          {group.first_seen_time ? formatLocalDateTime(group.first_seen_time) : '—'}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-0.5">Last Active</div>
                        <div className="text-slate-700 dark:text-slate-300 flex items-center gap-1">
                          <Clock className="w-3.5 h-3.5 text-slate-400 dark:text-slate-500" />
                          {formatLocalTime(group.last_seen_time)}
                        </div>
                      </div>
                    </div>


                    <div className="md:hidden flex flex-col items-end gap-1.5">
                      <Badge variant={group.avg_confidence >= 0.85 ? 'success' : group.avg_confidence >= 0.7 ? 'warning' : 'danger'} size="sm">
                        {avgPct}%
                      </Badge>
                      {group.first_seen_time && (
                        <span className="text-[10px] text-slate-500 font-mono">
                          First: {formatLocalDateTime(group.first_seen_time)}
                        </span>
                      )}
                    </div>

                    <div className="text-slate-400 hover:text-white p-1 rounded-lg">
                      {isExpanded ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="border-t border-slate-200 dark:border-white/5 bg-slate-50/40 dark:bg-navy-950/40 px-4 py-3 animate-fade-in">
                      {(group.first_seen_time || group.last_seen_time) && (
                        <div className="mb-3 text-[11px] text-slate-500 dark:text-slate-400 flex flex-wrap items-center gap-x-3 gap-y-1">
                          {group.first_seen_time && (
                            <span>
                              First seen:{' '}
                              <span className="font-mono text-slate-700 dark:text-slate-300">
                                {formatLocalDateTime(group.first_seen_time)}
                              </span>
                              {group.first_seen_camera ? ` · ${group.first_seen_camera}` : ''}
                            </span>
                          )}
                          {group.last_seen_time && (
                            <span>
                              Last seen:{' '}
                              <span className="font-mono text-slate-700 dark:text-slate-300">
                                {formatLocalDateTime(group.last_seen_time)}
                              </span>
                              {group.last_seen_camera ? ` · ${group.last_seen_camera}` : ''}
                            </span>
                          )}
                        </div>
                      )}
                      {detailLoading ? (
                        <div className="py-6 text-center text-xs text-slate-500">Loading detection history…</div>
                      ) : detailEvents.length === 0 ? (
                        <div className="py-6 text-center text-xs text-slate-500">No detailed events found for this person.</div>
                      ) : (
                        <div className="overflow-x-auto">
                          <table className="w-full text-left text-xs text-slate-700 dark:text-slate-300">
                            <thead className="text-[10px] font-bold text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-white/5 uppercase tracking-wider">
                              <tr>
                                <th className="p-3 w-16 text-center">Face Crop</th>
                                <th className="p-3">Time</th>
                                <th className="p-3">Camera ID</th>
                                <th className="p-3">Track ID</th>
                                <th className="p-3 text-right">Confidence</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-200 dark:divide-white/5">
                              {detailEvents.map(e => {
                                const ePct = Math.round(e.similarity * 100)
                                return (
                                  <tr key={e.id} className="hover:bg-white/5 transition-colors">
                                    <td className="p-2 flex items-center justify-center">
                                      {e.face_snapshot_url ? (
                                        <div
                                          onClick={() => setLightboxImage(e.face_snapshot_url || null)}
                                          className="relative w-9 h-9 rounded-lg overflow-hidden border border-white/10 bg-slate-900 cursor-zoom-in group/snap hover:border-blue-500/50 shadow-sm"
                                          title="Click to zoom face crop"
                                        >
                                          <img
                                            src={e.face_snapshot_url}
                                            alt="face snap"
                                            className="w-full h-full object-cover transition-transform group-hover/snap:scale-110"
                                          />
                                          <div className="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover/snap:opacity-100 transition-opacity">
                                            <Maximize2 className="w-3.5 h-3.5 text-white" />
                                          </div>
                                        </div>
                                      ) : (
                                        <div className="w-9 h-9 rounded-lg bg-slate-900 border border-white/5 flex items-center justify-center text-slate-600">
                                          <CameraIcon className="w-4 h-4" />
                                        </div>
                                      )}
                                    </td>
                                    <td className="p-3 font-mono text-slate-500 dark:text-slate-400">{formatLocalDateTime(e.recognized_at)}</td>
                                    <td className="p-3 font-mono text-slate-300">{e.camera_id}</td>
                                    <td className="p-3 font-mono text-slate-400">#{e.track_id}</td>
                                    <td className="p-3 text-right">
                                      <span className={`conf-pill text-[10px] ${
                                        e.similarity >= 0.85 ? 'conf-high' : e.similarity >= 0.7 ? 'conf-mid' : 'conf-low'
                                      }`}>
                                        {ePct}%
                                      </span>
                                    </td>
                                  </tr>
                                )
                              })}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}

            {summaries.length === 0 && (
              <div className="p-12 text-center text-slate-500 glass rounded-2xl border border-white/5">
                No recognition events found matching your search.
              </div>
            )}
          </div>
        ) : (
          <div className="glass rounded-2xl overflow-hidden border border-slate-200 dark:border-white/5">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-slate-700 dark:text-slate-300">
                <thead className="bg-slate-100/80 dark:bg-navy-950/80 text-slate-500 dark:text-slate-400 font-semibold border-b border-slate-200 dark:border-white/5 uppercase tracking-wider">
                  <tr>
                    <th className="p-4 w-16 text-center font-bold">Crop</th>
                    <th className="p-4">Time</th>
                    <th className="p-4">Person</th>
                    <th className="p-4">Camera</th>
                    <th className="p-4">Track ID</th>
                    <th className="p-4 text-right">Confidence</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-white/5">
                  {filteredFlat.map(e => {
                    const ePct = Math.round(e.similarity * 100)
                    const isUnknown = e.person_id === 'unknown'
                    return (
                      <tr key={e.id} className="hover:bg-white/5 transition-colors">
                        <td className="p-3 flex items-center justify-center">
                          {e.face_snapshot_url ? (
                            <div
                              onClick={() => setLightboxImage(e.face_snapshot_url || null)}
                              className="relative w-9 h-9 rounded-lg overflow-hidden border border-white/10 bg-slate-900 cursor-zoom-in group/snap hover:border-blue-500/50 shadow-sm"
                              title="Click to zoom face crop"
                            >
                              <img
                                src={e.face_snapshot_url}
                                alt="face snap"
                                className="w-full h-full object-cover transition-transform group-hover/snap:scale-110"
                              />
                              <div className="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover/snap:opacity-100 transition-opacity">
                                <Maximize2 className="w-3.5 h-3.5 text-white" />
                              </div>
                            </div>
                          ) : (
                            <div className="w-9 h-9 rounded-lg bg-slate-900 border border-white/5 flex items-center justify-center text-slate-600">
                              <CameraIcon className="w-4 h-4" />
                            </div>
                          )}
                        </td>
                        <td className="p-4 font-mono text-slate-500 dark:text-slate-400">{formatLocalDateTime(e.recognized_at)}</td>
                        <td className="p-4">
                          <div className={clsx('font-semibold', isUnknown ? 'text-amber-500 dark:text-amber-400' : 'text-slate-900 dark:text-white')}>{isUnknown ? 'Unknown Person' : e.name}</div>
                          <div className="text-[10px] text-blue-600 dark:text-primary-400 font-mono">ID: {e.person_id}</div>
                        </td>
                        <td className="p-4 font-mono text-slate-400">{e.camera_id}</td>
                        <td className="p-4 font-mono text-slate-400">#{e.track_id}</td>
                        <td className="p-4 text-right">
                          <span className={`conf-pill text-[10px] ${
                            e.similarity >= 0.85 ? 'conf-high' : e.similarity >= 0.7 ? 'conf-mid' : 'conf-low'
                          }`}>
                            {ePct}%
                          </span>
                        </td>
                      </tr>
                    )
                  })}
                  {filteredFlat.length === 0 && (
                    <tr>
                      <td colSpan={6} className="p-8 text-center text-slate-500">
                        No recognition events found matching your search.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {lightboxImage && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-sm animate-fade-in p-4"
          onClick={() => setLightboxImage(null)}
        >
          <div className="relative glass p-2 rounded-2xl max-w-sm w-full border border-white/10 shadow-2xl flex flex-col items-center animate-scale-up" onClick={e => e.stopPropagation()}>
            <button
              onClick={() => setLightboxImage(null)}
              className="absolute top-4 right-4 bg-black/60 hover:bg-black/95 text-white p-2 rounded-full transition-all border border-white/10 z-10"
            >
              <X className="w-4 h-4" />
            </button>
            <img
              src={lightboxImage}
              alt="Enlarged snapshot"
              className="w-full h-auto aspect-square object-contain rounded-xl bg-slate-950"
            />
            <div className="text-[11px] text-slate-400 mt-2 font-mono py-1">Event Face Crop Snapshot</div>
          </div>
        </div>
      )}
    </div>
  )
}
