import { useEffect, useState, useCallback } from 'react'
import {
  BarChart2, Users, FileDown, FileSpreadsheet, Calendar,
  Eye, UserCheck, UserX, Fingerprint, Loader2, RefreshCw,
} from 'lucide-react'
import clsx from 'clsx'

import { TopBar } from '../components/TopBar'
import { getReportSummary, downloadReportCsv, downloadReportPdf } from '../lib/api'
import type { ReportSummary } from '../lib/api'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, PieChart, Pie, Cell, AreaChart, Area,
} from 'recharts'

const TOOLTIP_STYLE = {
  backgroundColor: '#0d1224',
  border: '1px solid rgba(255,255,255,0.08)',
  borderRadius: '12px',
  color: '#e2e8f0',
  fontSize: '12px',
}

function todayStr() {
  return new Date().toISOString().slice(0, 10)
}
function daysAgoStr(n: number) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

interface SummaryCardProps {
  icon: React.ElementType
  label: string
  value: string | number
  color: string
}

function SummaryCard({ icon: Icon, label, value, color }: SummaryCardProps) {
  const colors: Record<string, string> = {
    blue: 'text-blue-500 dark:text-blue-400 bg-blue-500/10',
    green: 'text-green-500 dark:text-green-400 bg-green-500/10',
    red: 'text-red-500 dark:text-red-400 bg-red-500/10',
    teal: 'text-teal-500 dark:text-teal-400 bg-teal-500/10',
    purple: 'text-purple-500 dark:text-purple-400 bg-purple-500/10',
  }
  return (
    <div className="glass rounded-2xl p-4 flex items-center gap-3">
      <div className={clsx('w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0', colors[color])}>
        <Icon className="w-5 h-5" />
      </div>
      <div className="min-w-0">
        <div className="text-xl font-bold text-slate-900 dark:text-white leading-tight">{value}</div>
        <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">{label}</div>
      </div>
    </div>
  )
}

export function Analytics() {
  const [summary, setSummary] = useState<ReportSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [startDate, setStartDate] = useState(daysAgoStr(6))
  const [endDate, setEndDate] = useState(todayStr())
  const [exporting, setExporting] = useState<'csv' | 'pdf' | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    getReportSummary({ start_date: startDate, end_date: endDate })
      .then(setSummary)
      .catch(() => setSummary(null))
      .finally(() => setLoading(false))
  }, [startDate, endDate])

  useEffect(() => { load() }, [load])

  const applyPreset = (days: number) => {
    setStartDate(daysAgoStr(days - 1))
    setEndDate(todayStr())
  }

  const handleExport = async (type: 'csv' | 'pdf') => {
    setExporting(type)
    try {
      if (type === 'csv') await downloadReportCsv({ start_date: startDate, end_date: endDate })
      else await downloadReportPdf({ start_date: startDate, end_date: endDate })
    } catch (e) {
      console.error(e)
    } finally {
      setExporting(null)
    }
  }

  const cameraData = (summary?.by_camera || []).map(c => ({ name: c.camera_id, events: c.count }))
  const dayData = (summary?.by_day || []).map(d => ({ date: d.date.slice(5), events: d.count }))
  const pieData = summary ? [
    { name: 'Known Persons', value: summary.known_events || 0, color: '#3b82f6' },
    { name: 'Unknown Faces', value: summary.unknown_events || 0, color: '#ef4444' },
  ] : []

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <TopBar title="Analytics & Reports" />

      <div className="flex-1 overflow-y-auto p-6 space-y-6">

        {/* Filter & Export Toolbar */}
        <div className="glass rounded-2xl p-4 flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 text-slate-400 text-xs font-semibold">
            <Calendar className="w-4 h-4" />
            Date Range
          </div>
          <input
            type="date"
            value={startDate}
            max={endDate}
            onChange={e => setStartDate(e.target.value)}
            className="input-field py-1.5 text-xs w-36"
          />
          <span className="text-slate-500 text-xs">to</span>
          <input
            type="date"
            value={endDate}
            min={startDate}
            max={todayStr()}
            onChange={e => setEndDate(e.target.value)}
            className="input-field py-1.5 text-xs w-36"
          />

          <div className="flex items-center gap-1 glass p-1 rounded-xl border border-white/5">
            {[
              ['Today', 1], ['7 Days', 7], ['30 Days', 30],
            ].map(([label, d]: any) => (
              <button
                key={label}
                onClick={() => applyPreset(d)}
                className="px-2.5 py-1 rounded-lg text-[11px] font-semibold text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-white/5 transition-all"
              >
                {label}
              </button>
            ))}
          </div>

          <button
            onClick={load}
            className="w-8 h-8 rounded-xl flex items-center justify-center text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-white/5 transition-all"
            title="Refresh"
          >
            <RefreshCw className={clsx('w-4 h-4', loading && 'animate-spin')} />
          </button>

          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={() => handleExport('csv')}
              disabled={exporting !== null}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-xl border border-slate-200 dark:border-white/10 text-slate-700 dark:text-slate-200 hover:border-primary-500/40 hover:text-slate-900 dark:hover:text-white transition-all disabled:opacity-50"
            >
              {exporting === 'csv' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileSpreadsheet className="w-3.5 h-3.5" />}
              Export CSV
            </button>
            <button
              onClick={() => handleExport('pdf')}
              disabled={exporting !== null}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-xl bg-gradient-to-r from-primary-500 to-teal-500 text-white font-semibold shadow-md hover:opacity-90 transition-all disabled:opacity-50"
            >
              {exporting === 'pdf' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileDown className="w-3.5 h-3.5" />}
              Export PDF Report
            </button>
          </div>
        </div>

        {/* Summary Cards */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <SummaryCard icon={Eye} label="Total Events" value={summary?.total_events ?? '—'} color="blue" />
          <SummaryCard icon={UserCheck} label="Recognized Events" value={summary?.known_events ?? '—'} color="green" />
          <SummaryCard icon={UserX} label="Unknown Detections" value={summary?.unknown_events ?? '—'} color="red" />
          <SummaryCard icon={Fingerprint} label="Unique Persons Seen" value={summary?.unique_persons_seen ?? '—'} color="teal" />
          <SummaryCard icon={Users} label="Registered Persons" value={summary?.total_persons_registered ?? '—'} color="purple" />
        </div>

        {/* Charts */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="glass rounded-2xl p-6">
            <h3 className="font-bold text-slate-900 dark:text-white text-base mb-4 flex items-center gap-2">
              <BarChart2 className="w-5 h-5 text-blue-500 dark:text-primary-400" />
              Recognitions by Camera
            </h3>
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={cameraData}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                <XAxis dataKey="name" tick={{ fill: '#64748b', fontSize: 11 }} />
                <YAxis tick={{ fill: '#64748b', fontSize: 11 }} allowDecimals={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Bar dataKey="events" fill="#3b82f6" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="glass rounded-2xl p-6">
            <h3 className="font-bold text-slate-900 dark:text-white text-base mb-4 flex items-center gap-2">
              <Users className="w-5 h-5 text-teal-500 dark:text-teal-400" />
              Recognition Ratio
            </h3>
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label>
                  {pieData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </div>

          <div className="glass rounded-2xl p-6 lg:col-span-2">
            <h3 className="font-bold text-slate-900 dark:text-white text-base mb-4 flex items-center gap-2">
              <BarChart2 className="w-5 h-5 text-teal-500 dark:text-primary-400" />
              Daily Activity — {summary?.range.start} to {summary?.range.end}
            </h3>
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={dayData}>
                <defs>
                  <linearGradient id="dayGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#14b8a6" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="#14b8a6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} />
                <YAxis tick={{ fill: '#64748b', fontSize: 11 }} allowDecimals={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Area type="monotone" dataKey="events" stroke="#14b8a6" fill="url(#dayGrad)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Top Persons Table */}
        <div className="glass rounded-2xl p-6">
          <h3 className="font-bold text-slate-900 dark:text-white text-base mb-4 flex items-center gap-2">
            <Fingerprint className="w-5 h-5 text-blue-500 dark:text-primary-400" />
            Most Frequently Recognized
          </h3>
          {summary && summary.top_persons.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-slate-500 border-b border-slate-200 dark:border-white/5">
                    <th className="py-2 pr-4 font-semibold">Person</th>
                    <th className="py-2 pr-4 font-semibold">Person ID</th>
                    <th className="py-2 font-semibold text-right">Recognitions</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.top_persons.map(p => (
                    <tr key={p.person_id} className="border-b border-slate-200 dark:border-white/5 last:border-0">
                      <td className="py-2.5 pr-4 text-slate-800 dark:text-slate-200 font-medium">{p.name}</td>
                      <td className="py-2.5 pr-4 text-slate-500 font-mono">{p.person_id}</td>
                      <td className="py-2.5 text-right text-blue-600 dark:text-primary-400 font-bold">{p.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-10 text-slate-500 text-xs">
              No recognition activity in this date range.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
