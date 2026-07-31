import { useEffect, useState } from 'react'
import { Search, Download } from 'lucide-react'

import { TopBar } from '../components/TopBar'
import { getRecognitions } from '../lib/api'
import type { RecognitionEvent } from '../lib/api'

export function Events() {
  const [events, setEvents] = useState<RecognitionEvent[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getRecognitions(100).then(data => {
      setEvents(data)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  const filtered = events.filter(e =>
    e.name.toLowerCase().includes(search.toLowerCase()) ||
    e.person_id.toLowerCase().includes(search.toLowerCase()) ||
    e.camera_id.toLowerCase().includes(search.toLowerCase())
  )

  const exportCSV = () => {
    const headers = ['ID', 'Person ID', 'Name', 'Similarity', 'Track ID', 'Camera ID', 'Timestamp']
    const rows = filtered.map(e => [
      e.id, e.person_id, `"${e.name}"`, e.similarity, e.track_id, e.camera_id, `"${e.recognized_at}"`
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
        <div className="flex items-center justify-between gap-4">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              className="input-field pl-9"
              placeholder="Search by name, ID, or camera..."
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>

          <button onClick={exportCSV} className="btn-secondary">
            <Download className="w-4 h-4" /> Export CSV
          </button>
        </div>

        <div className="glass rounded-2xl overflow-hidden border border-white/5">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="bg-navy-950/80 text-slate-400 font-semibold border-b border-white/5 uppercase tracking-wider">
                <tr>
                  <th className="p-4">Time</th>
                  <th className="p-4">Person</th>
                  <th className="p-4">Camera</th>
                  <th className="p-4">Track ID</th>
                  <th className="p-4">Confidence</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {filtered.map(e => (
                  <tr key={e.id} className="hover:bg-white/5 transition-colors">
                    <td className="p-4 font-mono text-slate-400">{e.recognized_at}</td>
                    <td className="p-4">
                      <div className="font-semibold text-white">{e.name}</div>
                      <div className="text-[10px] text-primary-400 font-mono">ID: {e.person_id}</div>
                    </td>
                    <td className="p-4 font-mono text-slate-400">{e.camera_id}</td>
                    <td className="p-4 font-mono text-slate-400">#{e.track_id}</td>
                    <td className="p-4">
                      <span className={`conf-pill text-[10px] ${
                        e.similarity >= 0.85 ? 'conf-high' : e.similarity >= 0.7 ? 'conf-mid' : 'conf-low'
                      }`}>
                        {Math.round(e.similarity * 100)}%
                      </span>
                    </td>
                  </tr>
                ))}
                {filtered.length === 0 && !loading && (
                  <tr>
                    <td colSpan={5} className="p-8 text-center text-slate-500">
                      No recognition events found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
