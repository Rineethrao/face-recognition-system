import { useEffect, useState, useCallback } from 'react'

import {
  Users,
  Eye,
  Camera,
  MapPin,
  Clock,
  Search,
  UserCheck,
  RefreshCw,
  Calendar,
  Layers,
  ChevronRight,
  ShieldCheck,
  Sparkles,
  Trash2,
  RotateCcw,
  FileSpreadsheet,
  FileDown,
  Loader2,
  CheckSquare,
  Square,
  GitMerge
} from 'lucide-react'

import { TopBar } from '../components/TopBar'
import {
  getVisitors,
  getVisitorStats,
  getVisitorDates,
  getVisitorTimeline,
  getVisitorSnapshots,
  getCameras,
  deleteVisitor,
  purgeAllVisitors,
  downloadVisitorReportCsv,
  downloadVisitorReportPdf
} from '../lib/api'
import type { VisitorItem, VisitorStats, VisitorDateItem, VisitorTimelineResponse, VisitorSampleSnapshot, CameraConfig } from '../lib/api'
import { VisitorPromotionModal } from '../components/visitors/VisitorPromotionModal'
import { VisitorMergeModal } from '../components/visitors/VisitorMergeModal'
import { toast } from '../components/ui/Toast'
import clsx from 'clsx'

function VisitorAvatar({ url, code, dateKey, className, fallbackSize = "w-6 h-6" }: { url?: string; code: string; dateKey: string; className: string; fallbackSize?: string }) {
  const [imgSrc, setImgSrc] = useState<string>(() => {
    if (url) return url
    return `/faces/visitors/${dateKey}/${code}/primary_avatar.jpg`
  })
  const [hasError, setHasError] = useState(false)

  useEffect(() => {
    if (url) {
      setImgSrc(url)
      setHasError(false)
    } else {
      setImgSrc(`/faces/visitors/${dateKey}/${code}/primary_avatar.jpg`)
      setHasError(false)
    }
  }, [url, code, dateKey])

  const handleError = () => {
    if (imgSrc.endsWith('primary_avatar.jpg') && url && imgSrc !== url) {
      setHasError(true)
    } else if (url && imgSrc === url) {
      setImgSrc(`/faces/visitors/${dateKey}/${code}/primary_avatar.jpg`)
    } else {
      setHasError(true)
    }
  }

  if (hasError || !imgSrc) {
    return (
      <div className={clsx("bg-slate-800 flex items-center justify-center text-slate-400 shrink-0 border border-slate-700 font-bold", className)}>
        <Users className={fallbackSize} />
      </div>
    )
  }

  return (
    <img
      src={imgSrc}
      alt={code}
      onError={handleError}
      className={clsx("object-cover shrink-0", className)}
    />
  )
}


function dateKeyToDisplayDate(dateKey: string): string {
  if (!dateKey || dateKey === 'all') return 'All Dates'
  if (dateKey.length === 8 && /^\d{8}$/.test(dateKey)) {
    return `${dateKey.slice(6, 8)}-${dateKey.slice(4, 6)}-${dateKey.slice(0, 4)}`
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(dateKey)) {
    const parts = dateKey.split('-')
    return `${parts[2]}-${parts[1]}-${parts[0]}`
  }
  return dateKey
}

function dateKeyToIso(dateKey: string): string {
  if (!dateKey || dateKey === 'all') return ''
  if (dateKey.length === 8) {
    return `${dateKey.slice(0, 4)}-${dateKey.slice(4, 6)}-${dateKey.slice(6, 8)}`
  }
  if (/^\d{2}-\d{2}-\d{4}$/.test(dateKey)) {
    const parts = dateKey.split('-')
    return `${parts[2]}-${parts[1]}-${parts[0]}`
  }
  return dateKey
}

function isoToDateKey(isoStr: string): string {
  if (!isoStr) return 'all'
  return isoStr.replace(/-/g, '')
}


export function VisitorTracking() {
  const [stats, setStats] = useState<VisitorStats | null>(null)
  const [visitors, setVisitors] = useState<VisitorItem[]>([])
  const [cameras, setCameras] = useState<CameraConfig[]>([])
  const [dates, setDates] = useState<VisitorDateItem[]>([])
  const [selectedDateKey, setSelectedDateKey] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [selectedVisitorId, setSelectedVisitorId] = useState<number | null>(null)
  const [timeline, setTimeline] = useState<VisitorTimelineResponse | null>(null)
  const [snapshots, setSnapshots] = useState<VisitorSampleSnapshot[]>([])
  const [loadingTimeline, setLoadingTimeline] = useState(false)
  const [loadingSnapshots, setLoadingSnapshots] = useState(false)

  // Filters
  const [search, setSearch] = useState('')
  const [cameraFilter, setCameraFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')

  // Modal & Actions
  const [promoteModalOpen, setPromoteModalOpen] = useState(false)
  const [mergeModalOpen, setMergeModalOpen] = useState(false)
  const [promoteVisitorIds, setPromoteVisitorIds] = useState<number[]>([])
  const [checkedVisitorIds, setCheckedVisitorIds] = useState<number[]>([])
  const [deleting, setDeleting] = useState(false)
  const [purging, setPurging] = useState(false)
  const [exporting, setExporting] = useState<'csv' | 'pdf' | null>(null)

  const handleExportReport = async (type: 'csv' | 'pdf') => {
    setExporting(type)
    try {
      if (type === 'csv') {
        await downloadVisitorReportCsv({ date_key: selectedDateKey || undefined, status: statusFilter, camera_id: cameraFilter })
      } else {
        await downloadVisitorReportPdf({ date_key: selectedDateKey || undefined, status: statusFilter, camera_id: cameraFilter })
      }
      toast.success('Report Exported', `Visitor ${type.toUpperCase()} report downloaded successfully.`)
    } catch (err) {
      console.error(err)
      toast.error('Export Failed', `Failed to export visitor ${type.toUpperCase()} report.`)
    } finally {
      setExporting(null)
    }
  }

  const handlePurgeAllVisitors = async () => {
    if (!window.confirm('Are you sure you want to PURGE ALL previous visitor IDs and start fresh from ID 1? This will permanently delete all visitor profiles, face samples, and sightings.')) {
      return
    }

    setPurging(true)
    try {
      await purgeAllVisitors()
      toast.success('Visitor Subsystem Reset', 'All previous visitor profiles, snapshots, and sightings deleted. New IDs will start from 1.')
      setSelectedVisitorId(null)
      setVisitors([])
      await loadData()
    } catch (err) {
      console.error(err)
      toast.error('Purge Failed', 'Failed to purge visitor profiles.')
    } finally {
      setPurging(false)
    }
  }

  const handleDeleteVisitor = async () => {
    if (!selectedVisitorId) return
    const vis = visitors.find(v => v.id === selectedVisitorId)
    const code = vis ? vis.visitor_code : `ID ${selectedVisitorId}`

    if (!window.confirm(`Are you sure you want to delete visitor ${code}? This action will remove all snapshots and sightings.`)) {
      return
    }

    setDeleting(true)
    try {
      await deleteVisitor(selectedVisitorId)
      toast.success('Visitor Deleted', `Successfully deleted visitor ${code}.`)
      setSelectedVisitorId(null)
      await loadData()
    } catch (err) {
      console.error(err)
      toast.error('Delete Failed', 'Failed to delete visitor profile.')
    } finally {
      setDeleting(false)
    }
  }

  const loadData = useCallback(async (showSpinner = false) => {
    if (showSpinner) {
      setLoading(true)
    }
    try {
      const [datesData, statsData, visitorsData, camsData] = await Promise.all([
        getVisitorDates(),
        getVisitorStats(selectedDateKey || undefined),
        getVisitors({ date_key: selectedDateKey || undefined, search, camera_id: cameraFilter, status: statusFilter }),
        getCameras()
      ])

      setDates(datesData || [])
      setStats(statsData || null)
      setVisitors(visitorsData?.visitors || [])
      setCameras(camsData || [])

      const fetchedVisitors = visitorsData?.visitors || []

      if (!selectedDateKey && datesData && datesData.length > 0) {
        const todayItem = datesData.find(d => d.is_today) || datesData[0]
        if (todayItem) setSelectedDateKey(todayItem.date_key)
      }

      if (fetchedVisitors.length > 0) {
        setSelectedVisitorId(prev => {
          if (!prev || !fetchedVisitors.some(v => v.id === prev)) {
            return fetchedVisitors[0].id
          }
          return prev
        })
      } else {
        setSelectedVisitorId(null)
      }
    } catch (err) {
      console.error('[VisitorTracking loadData Error]:', err)
    } finally {
      setLoading(false)
    }
  }, [selectedDateKey, search, cameraFilter, statusFilter])

  useEffect(() => {
    loadData(true)
    const interval = setInterval(() => loadData(false), 8000)
    return () => clearInterval(interval)
  }, [loadData])



  useEffect(() => {
    if (!selectedVisitorId) {
      setTimeline(null)
      setSnapshots([])
      return
    }
    const loadDetails = async () => {
      setLoadingTimeline(true)
      setLoadingSnapshots(true)
      try {
        const [timelineData, snapshotsData] = await Promise.all([
          getVisitorTimeline(selectedVisitorId, selectedDateKey || undefined),
          getVisitorSnapshots(selectedVisitorId, selectedDateKey || undefined)
        ])
        setTimeline(timelineData)
        setSnapshots(snapshotsData)
      } catch (err) {
        console.error(err)
      } finally {
        setLoadingTimeline(false)
        setLoadingSnapshots(false)
      }
    }
    loadDetails()
  }, [selectedVisitorId, selectedDateKey])


  const selectedVisitor = visitors.find(v => v.id === selectedVisitorId)

  const toggleVisitorCheck = (visitorId: number, e?: React.MouseEvent) => {
    e?.stopPropagation()
    setCheckedVisitorIds(prev =>
      prev.includes(visitorId)
        ? prev.filter(id => id !== visitorId)
        : [...prev, visitorId]
    )
  }

  const openMergeModal = (ids: number[]) => {
    const eligible = ids.filter(id => {
      const v = visitors.find(x => x.id === id)
      return v && v.status === 'active'
    })
    if (eligible.length < 2) {
      toast.error('Cannot Merge', 'Select at least two active (unregistered) visitors.')
      return
    }
    setPromoteVisitorIds(eligible)
    setMergeModalOpen(true)
  }

  const openPromoteModal = (ids: number[]) => {
    const eligible = ids.filter(id => {
      const v = visitors.find(x => x.id === id)
      return v && v.status !== 'promoted'
    })
    if (eligible.length === 0) {
      toast.error('Cannot Register', 'Selected visitors are already registered or invalid.')
      return
    }
    setPromoteVisitorIds(eligible)
    setPromoteModalOpen(true)
  }

  const promoteModalVisitors = promoteVisitorIds
    .map(id => visitors.find(v => v.id === id))
    .filter(Boolean) as VisitorItem[]

  const checkedActiveCount = checkedVisitorIds.filter(id => {
    const v = visitors.find(x => x.id === id)
    return v && v.status !== 'promoted'
  }).length
  const selectedDateLabel = selectedDateKey === 'all'
    ? 'All Dates'
    : (dates.find(d => d.date_key === selectedDateKey)?.is_today
      ? `Visitors Today (${dateKeyToDisplayDate(selectedDateKey)})`
      : `Visitors (${dateKeyToDisplayDate(selectedDateKey)})`)

  return (
    <div className="flex flex-col h-full overflow-y-auto bg-slate-950 text-slate-100 custom-scrollbar">
      <TopBar title="Visitor Tracking & Re-Identification" />

      <main className="flex-1 p-6 space-y-6 max-w-[1600px] w-full mx-auto pb-12">
        {/* Header Summary Cards */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-4 flex items-center gap-4">
            <div className="p-3 bg-blue-500/10 text-blue-400 border border-blue-500/20 rounded-xl">
              <Users className="w-6 h-6" />
            </div>
            <div>
              <p className="text-xs font-medium text-slate-400">{selectedDateLabel}</p>
              <h3 className="text-2xl font-bold text-white">{stats?.total_visitors_today ?? 0}</h3>
            </div>
          </div>

          <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-4 flex items-center gap-4">
            <div className="p-3 bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 rounded-xl">
              <Eye className="w-6 h-6" />
            </div>
            <div>
              <p className="text-xs font-medium text-slate-400">Active Visitors</p>
              <h3 className="text-2xl font-bold text-cyan-400">{stats?.active_visitors ?? 0}</h3>
            </div>
          </div>

          <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-4 flex items-center gap-4">
            <div className="p-3 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-xl">
              <Camera className="w-6 h-6" />
            </div>
            <div>
              <p className="text-xs font-medium text-slate-400">Online Cameras</p>
              <h3 className="text-2xl font-bold text-emerald-400">{stats?.online_cameras ?? 0}</h3>
            </div>
          </div>

          <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-4 flex items-center gap-4">
            <div className="p-3 bg-purple-500/10 text-purple-400 border border-purple-500/20 rounded-xl">
              <Layers className="w-6 h-6" />
            </div>
            <div>
              <p className="text-xs font-medium text-slate-400">Total Sightings</p>
              <h3 className="text-2xl font-bold text-white">{stats?.total_sightings ?? 0}</h3>
            </div>
          </div>
        </div>

        {/* Filter Controls Bar */}
        <div className="flex flex-wrap items-center justify-between gap-4 bg-slate-900/50 border border-slate-800/80 rounded-2xl p-4">
          <div className="flex items-center gap-3 flex-1 min-w-[280px]">
            <div className="relative flex-1">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="Search visitor code (e.g. VISITOR-20260806)..."
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="w-full pl-9 pr-4 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500"
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {/* Date Selector Dropdown & Picker */}
            <div className="flex items-center gap-2 bg-slate-950 border border-slate-800 rounded-xl px-2.5 py-1">
              <Calendar className="w-4 h-4 text-cyan-400 shrink-0" />
              <select
                value={selectedDateKey}
                onChange={e => setSelectedDateKey(e.target.value)}
                className="bg-transparent border-none text-sm text-slate-200 focus:outline-none cursor-pointer font-medium py-1"
              >
                <option value="all" className="bg-slate-900 text-slate-200">All Dates</option>
                {dates.map(d => (
                  <option key={d.date_key} value={d.date_key} className="bg-slate-900 text-slate-200">
                    {d.date_formatted || dateKeyToDisplayDate(d.date_key)} {d.is_today ? '(Today)' : ''} ({d.count} visitors)
                  </option>
                ))}
              </select>
              <input
                type="date"
                value={dateKeyToIso(selectedDateKey)}
                onChange={e => setSelectedDateKey(isoToDateKey(e.target.value))}
                className="bg-slate-900 border border-slate-800 rounded-lg text-xs text-slate-300 px-2 py-1 focus:outline-none focus:border-cyan-500 cursor-pointer"
                title="Pick specific date"
              />
            </div>

            <select
              value={cameraFilter}
              onChange={e => setCameraFilter(e.target.value)}
              className="px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-cyan-500"
            >
              <option value="">All Cameras</option>
              {cameras.map(c => (
                <option key={c.camera_id} value={c.camera_id}>{c.name}</option>
              ))}
            </select>

            <select
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
              className="px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-slate-200 focus:outline-none focus:border-cyan-500"
            >
              <option value="">All Statuses</option>
              <option value="active">Active</option>
              <option value="promoted">Promoted</option>
            </select>

            <button
              onClick={() => loadData(true)}
              className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl transition-colors cursor-pointer"
              title="Refresh Data"
            >

              <RefreshCw className={clsx("w-4 h-4", loading && "animate-spin")} />
            </button>

            {/* Export Reports Buttons */}
            <div className="flex items-center gap-2 border-l border-slate-800 pl-3">
              <button
                onClick={() => handleExportReport('csv')}
                disabled={exporting !== null}
                className="flex items-center gap-1.5 px-3 py-2 bg-slate-900 border border-slate-800 hover:border-cyan-500/40 text-slate-200 rounded-xl text-sm transition-all cursor-pointer disabled:opacity-50"
                title="Export Visitors CSV Report"
              >
                {exporting === 'csv' ? <Loader2 className="w-4 h-4 animate-spin text-cyan-400" /> : <FileSpreadsheet className="w-4 h-4 text-emerald-400" />}
                <span className="hidden sm:inline font-medium">Export CSV</span>
              </button>

              <button
                onClick={() => handleExportReport('pdf')}
                disabled={exporting !== null}
                className="flex items-center gap-1.5 px-3 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white rounded-xl text-sm font-medium transition-all shadow-md cursor-pointer disabled:opacity-50"
                title="Export Visitors PDF Report"
              >
                {exporting === 'pdf' ? <Loader2 className="w-4 h-4 animate-spin text-white" /> : <FileDown className="w-4 h-4" />}
                <span className="hidden sm:inline">Export PDF</span>
              </button>
            </div>

            <button
              onClick={handlePurgeAllVisitors}
              disabled={purging}
              className="flex items-center gap-2 px-3 py-2 bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/30 hover:border-rose-500/50 rounded-xl text-sm font-medium transition-all cursor-pointer"
              title="Purge All Previous Visitors & Reset Visitor ID Values"
            >
              <RotateCcw className={clsx("w-4 h-4", purging && "animate-spin")} />
              <span>Purge All</span>
            </button>
          </div>
        </div>


        {/* Split View Content Area */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* Left Column: Unregistered Visitor List (5 cols) */}
          <div className="lg:col-span-5 bg-slate-900/60 border border-slate-800/80 rounded-2xl p-4 flex flex-col h-[calc(100vh-220px)] min-h-[480px] sticky top-4">
            <div className="flex items-center justify-between mb-4 pb-3 border-b border-slate-800">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">Visitors ({visitors.length})</h2>
              <span className="text-xs text-cyan-400 font-mono">Select duplicates to merge</span>
            </div>

            {checkedActiveCount >= 2 && (
              <div className="mb-3 p-3 rounded-xl bg-violet-500/10 border border-violet-500/30 space-y-2">
                <span className="text-xs text-violet-200 block">
                  {checkedActiveCount} visitors selected — same person?
                </span>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => openMergeModal(checkedVisitorIds)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-500 text-white text-xs font-semibold transition-colors"
                  >
                    <GitMerge className="w-3.5 h-3.5" />
                    Merge for Tracking
                  </button>
                  <button
                    onClick={() => openPromoteModal(checkedVisitorIds)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold transition-colors"
                  >
                    <UserCheck className="w-3.5 h-3.5" />
                    Register as One Person
                  </button>
                </div>
              </div>
            )}

            <div className="flex-1 overflow-y-auto space-y-3 pr-1 custom-scrollbar">
              {loading ? (
                <div className="flex items-center justify-center h-48 text-slate-500 text-sm">
                  Loading visitors...
                </div>
              ) : visitors.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-48 text-slate-500 text-sm gap-2">
                  <Users className="w-8 h-8 opacity-40" />
                  <span>No visitors detected today yet.</span>
                </div>
              ) : (
                visitors.map(v => {
                  const isSelected = v.id === selectedVisitorId
                  const isChecked = checkedVisitorIds.includes(v.id)
                  const canCheck = v.status !== 'promoted'
                  return (
                    <div
                      key={v.id}
                      onClick={() => setSelectedVisitorId(v.id)}
                      className={clsx(
                        "p-3 rounded-xl border transition-all cursor-pointer flex items-center justify-between gap-3",
                        isSelected
                          ? "bg-cyan-950/30 border-cyan-500/50 shadow-lg shadow-cyan-950/20"
                          : isChecked
                            ? "bg-violet-950/20 border-violet-500/40"
                            : "bg-slate-950/50 border-slate-800/80 hover:bg-slate-800/40 hover:border-slate-700"
                      )}
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        {canCheck ? (
                          <button
                            type="button"
                            onClick={(e) => toggleVisitorCheck(v.id, e)}
                            className={clsx(
                              "shrink-0 p-0.5 rounded transition-colors",
                              isChecked ? "text-violet-400" : "text-slate-500 hover:text-slate-300"
                            )}
                            title={isChecked ? 'Deselect for merge' : 'Select to merge duplicates'}
                          >
                            {isChecked ? <CheckSquare className="w-4 h-4" /> : <Square className="w-4 h-4" />}
                          </button>
                        ) : (
                          <div className="w-5" />
                        )}
                        <VisitorAvatar
                          url={v.primary_snapshot_url}
                          code={v.visitor_code}
                          dateKey={v.date_key}
                          className="w-12 h-12 rounded-xl"
                        />

                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <h4 className="font-bold text-sm text-white truncate">{v.visitor_code}</h4>
                            {v.status === 'promoted' && (
                              <span className="px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-400 text-[10px] font-semibold border border-emerald-500/20">
                                Promoted
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2 text-xs text-slate-400 mt-1">
                            <Clock className="w-3 h-3 text-slate-500" />
                            <span>{v.first_seen_at.split(' ')[1] || v.first_seen_at} → {v.last_seen_at.split(' ')[1] || v.last_seen_at}</span>
                          </div>
                          {v.merged_from_codes && v.merged_from_codes.length > 0 && (
                            <p className="text-[10px] text-violet-400 mt-1">
                              Includes: {v.merged_from_codes.join(', ')}
                            </p>
                          )}
                        </div>
                      </div>

                      <div className="flex items-center gap-2 shrink-0">
                        <span className="px-2 py-1 bg-slate-800 text-slate-300 text-xs font-mono rounded-lg">
                          {v.sighting_count} sight
                        </span>
                        <ChevronRight className="w-4 h-4 text-slate-500" />
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>

          {/* Right Column: Visitor Profile, Snapshots & Timeline Journey (7 cols) */}
          <div className="lg:col-span-7 space-y-6">
            {selectedVisitor ? (
              <>
                {/* Visitor Profile Detail Header Card */}
                <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-6 relative overflow-hidden">
                  <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-6">
                    <div className="flex items-center gap-5">
                      <VisitorAvatar
                        url={selectedVisitor.primary_snapshot_url}
                        code={selectedVisitor.visitor_code}
                        dateKey={selectedVisitor.date_key}
                        className="w-24 h-24 rounded-2xl border-2 border-cyan-500/40 shadow-xl shadow-cyan-500/10"
                        fallbackSize="w-10 h-10"
                      />


                      <div className="space-y-1">
                        <div className="flex items-center gap-3">
                          <h2 className="text-2xl font-black tracking-tight text-white">{selectedVisitor.visitor_code}</h2>
                          <span className={clsx(
                            "px-2.5 py-1 rounded-full text-xs font-semibold uppercase tracking-wider border",
                            selectedVisitor.status === 'promoted'
                              ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                              : "bg-cyan-500/10 text-cyan-400 border-cyan-500/20"
                          )}>
                            {selectedVisitor.status}
                          </span>
                        </div>

                        <div className="flex flex-wrap items-center gap-4 text-xs text-slate-400 pt-1">
                          <div className="flex items-center gap-1.5">
                            <Calendar className="w-3.5 h-3.5 text-slate-500" />
                            <span>Date Key: <strong className="text-slate-200 font-mono">{dateKeyToDisplayDate(selectedVisitor.date_key)}</strong></span>
                          </div>
                          {selectedVisitor.merged_from_codes && selectedVisitor.merged_from_codes.length > 0 && (
                            <div className="flex items-center gap-1.5 text-violet-400">
                              <GitMerge className="w-3.5 h-3.5" />
                              <span>Merged from: <strong>{selectedVisitor.merged_from_codes.join(', ')}</strong></span>
                            </div>
                          )}
                          <div className="flex items-center gap-1.5">
                            <Clock className="w-3.5 h-3.5 text-slate-500" />
                            <span>First: <strong className="text-slate-200">{selectedVisitor.first_seen_at}</strong></span>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <Clock className="w-3.5 h-3.5 text-slate-500" />
                            <span>Last: <strong className="text-slate-200">{selectedVisitor.last_seen_at}</strong></span>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-3 shrink-0">
                      {selectedVisitor.status !== 'promoted' ? (
                        <button
                          onClick={() => openPromoteModal(
                            checkedVisitorIds.includes(selectedVisitor.id) && checkedActiveCount >= 2
                              ? checkedVisitorIds
                              : [selectedVisitor.id]
                          )}
                          className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white font-medium text-sm shadow-lg shadow-cyan-500/20 transition-all cursor-pointer"
                        >
                          <UserCheck className="w-4 h-4" />
                          <span>
                            {checkedVisitorIds.includes(selectedVisitor.id) && checkedActiveCount >= 2
                              ? `Register ${checkedActiveCount} as One Person`
                              : 'Register Person'}
                          </span>
                        </button>
                      ) : (
                        <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold">
                          <ShieldCheck className="w-4 h-4" />
                          <span>Registered as {selectedVisitor.promoted_person_id}</span>
                        </div>
                      )}

                      <button
                        onClick={handleDeleteVisitor}
                        disabled={deleting}
                        className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/30 hover:border-rose-500/50 font-medium text-sm transition-all cursor-pointer"
                        title="Delete Visitor Profile"
                      >
                        <Trash2 className="w-4 h-4" />
                        <span>{deleting ? 'Deleting...' : 'Delete Visitor'}</span>
                      </button>
                    </div>
                  </div>
                </div>

                {/* Captured Face Snapshots (Multi-Frame Gallery) Card */}
                <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-6 space-y-4">
                  <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                    <div className="flex items-center gap-2">
                      <Sparkles className="w-4 h-4 text-cyan-400" />
                      <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-200">Captured Face Snapshots</h3>
                    </div>
                    <span className="text-xs text-cyan-400 font-mono">Gallery Samples ({snapshots.length})</span>
                  </div>

                  <p className="text-xs text-slate-400 leading-relaxed">
                    High-quality face crops collected while the person was inside the camera frame. These samples form the embedding gallery used to track and recognize the person across all CCTV cameras without creating duplicate profiles.
                  </p>

                  {loadingSnapshots ? (
                    <div className="flex items-center justify-center h-28 text-slate-500 text-sm">
                      Loading face snapshots...
                    </div>
                  ) : snapshots.length === 0 ? (
                    <div className="text-center py-8 text-slate-500 text-xs border border-dashed border-slate-800 rounded-xl">
                      No multi-frame face samples stored for this visitor yet.
                    </div>
                  ) : (
                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                      {snapshots.map((snap) => (
                        <div key={snap.id} className="bg-slate-950/80 border border-slate-800/80 hover:border-cyan-500/40 rounded-xl p-2.5 transition-all flex flex-col items-center text-center space-y-2 group">
                          {snap.snapshot_url ? (
                            <img
                              src={snap.snapshot_url}
                              alt={`Sample ${snap.id}`}
                              className="w-20 h-20 rounded-lg object-cover border border-slate-800 group-hover:scale-105 transition-transform"
                            />
                          ) : (
                            <div className="w-20 h-20 rounded-lg bg-slate-800 flex items-center justify-center text-slate-500 text-xs">
                              No Crop
                            </div>
                          )}

                          <div className="w-full space-y-1 text-[11px]">
                            <div className="flex items-center justify-between font-mono text-slate-300">
                              <span className="text-slate-500">Quality:</span>
                              <span className="font-bold text-cyan-400">{(snap.quality_score * 100).toFixed(0)}%</span>
                            </div>
                            <div className="flex items-center justify-between font-mono text-slate-400">
                              <span className="text-slate-500">Blur:</span>
                              <span>{snap.blur_score.toFixed(1)}</span>
                            </div>
                            <div className="flex items-center justify-between font-mono text-slate-400">
                              <span className="text-slate-500">Yaw:</span>
                              <span>{(snap.yaw * 57.3).toFixed(1)}°</span>
                            </div>
                            <div className="pt-1 border-t border-slate-900 text-[10px] text-slate-500 font-mono truncate">
                              {snap.timestamp.split(' ')[1] || snap.timestamp}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Visitor Journey Timeline Section */}
                <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-6 space-y-4">
                  <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">Journey Timeline</h3>
                    <span className="text-xs text-slate-500 font-mono">Camera Sightings ({timeline?.sightings.length ?? 0})</span>
                  </div>

                  {loadingTimeline ? (
                    <div className="flex items-center justify-center h-40 text-slate-500 text-sm">
                      Loading journey timeline...
                    </div>
                  ) : !timeline || timeline.sightings.length === 0 ? (
                    <div className="text-center py-12 text-slate-500 text-sm">
                      No sighting timeline recorded for this visitor.
                    </div>
                  ) : (
                    <div className="relative pl-6 space-y-6 before:absolute before:left-2.5 before:top-3 before:bottom-3 before:w-0.5 before:bg-slate-800 max-h-[520px] overflow-y-auto custom-scrollbar pr-2 pt-1 pb-1">
                      {timeline.sightings.map((s) => (
                        <div key={s.id} className="relative flex items-start gap-4 group">
                          {/* Timeline dot */}
                          <div className="absolute -left-6 top-1.5 w-3 h-3 rounded-full bg-cyan-400 border-2 border-slate-950 ring-4 ring-cyan-500/20 group-hover:scale-125 transition-transform" />

                          {/* Card */}
                          <div className="flex-1 bg-slate-950/70 border border-slate-800/80 hover:border-slate-700 rounded-xl p-4 transition-all">
                            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-3">
                              <div className="flex items-center gap-2">
                                <MapPin className="w-4 h-4 text-cyan-400" />
                                <span className="font-bold text-sm text-white">{s.camera_name}</span>
                                <span className="text-xs font-mono text-slate-500">({s.camera_id})</span>
                              </div>

                              <div className="flex items-center gap-3 text-xs text-slate-400 font-mono">
                                <span>{s.entered_at.split(' ')[1]} → {s.last_seen_at.split(' ')[1]}</span>
                                <span className="px-2 py-0.5 bg-slate-800 text-cyan-400 rounded-md font-semibold">{s.duration_formatted}</span>
                              </div>
                            </div>

                            <div className="flex items-center gap-4">
                              {s.snapshot_url ? (
                                <img
                                  src={s.snapshot_url}
                                  alt={s.camera_name}
                                  className="w-16 h-16 rounded-lg object-cover border border-slate-800 shrink-0"
                                />
                              ) : (
                                <div className="w-16 h-16 rounded-lg bg-slate-800 flex items-center justify-center text-slate-500 text-xs shrink-0">
                                  No Crop
                                </div>
                              )}

                              <div className="grid grid-cols-3 gap-3 text-xs flex-1 bg-slate-900/50 p-2.5 rounded-lg border border-slate-800/50">
                                <div>
                                  <span className="text-slate-500 block text-[10px] uppercase font-semibold">Best Sim</span>
                                  <span className="font-mono text-slate-200 font-bold">{(s.best_similarity * 100).toFixed(1)}%</span>
                                </div>
                                <div>
                                  <span className="text-slate-500 block text-[10px] uppercase font-semibold">Margin</span>
                                  <span className="font-mono text-emerald-400 font-bold">+{s.match_margin.toFixed(2)}</span>
                                </div>
                                <div>
                                  <span className="text-slate-500 block text-[10px] uppercase font-semibold">Confidence</span>
                                  <span className="font-mono text-cyan-400 font-bold">{(s.identity_confidence * 100).toFixed(0)}%</span>
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-12 text-center text-slate-500 text-sm">
                Select a visitor from the list to view profile and journey timeline.
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Visitor Promotion Modal */}
      {promoteModalVisitors.length > 0 && (
        <VisitorPromotionModal
          visitorIds={promoteModalVisitors.map(v => v.id)}
          visitorCodes={promoteModalVisitors.map(v => v.visitor_code)}
          primarySnapshotUrl={promoteModalVisitors[0]?.primary_snapshot_url}
          isOpen={promoteModalOpen}
          onClose={() => {
            setPromoteModalOpen(false)
            setPromoteVisitorIds([])
          }}
          onSuccess={() => {
            setCheckedVisitorIds([])
            setPromoteVisitorIds([])
            loadData()
          }}
        />
      )}

      {promoteModalVisitors.length >= 2 && (
        <VisitorMergeModal
          visitorIds={promoteModalVisitors.map(v => v.id)}
          visitorCodes={promoteModalVisitors.map(v => v.visitor_code)}
          primaryVisitorId={promoteModalVisitors[0]?.id}
          isOpen={mergeModalOpen}
          onClose={() => {
            setMergeModalOpen(false)
            setPromoteVisitorIds([])
          }}
          onSuccess={(primaryId) => {
            setCheckedVisitorIds([])
            setPromoteVisitorIds([])
            setSelectedVisitorId(primaryId)
            loadData()
          }}
        />
      )}
    </div>
  )
}
