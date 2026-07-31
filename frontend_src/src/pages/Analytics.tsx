import { useEffect, useState } from 'react'
import { BarChart2, Users } from 'lucide-react'

import { TopBar } from '../components/TopBar'
import { getRecognitions } from '../lib/api'
import type { RecognitionEvent } from '../lib/api'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell,
} from 'recharts'

export function Analytics() {
  const [events, setEvents] = useState<RecognitionEvent[]>([])

  useEffect(() => {
    getRecognitions(100).then(setEvents).catch(() => {})
  }, [])

  const cameraCounts: Record<string, number> = {}
  let known = 0
  let unknown = 0

  events.forEach(e => {
    cameraCounts[e.camera_id] = (cameraCounts[e.camera_id] || 0) + 1
    if (e.person_id === 'unknown') unknown++
    else known++
  })

  const cameraData = Object.entries(cameraCounts).map(([cam, count]) => ({
    name: cam,
    events: count,
  }))

  const pieData = [
    { name: 'Known Persons', value: known || 1, color: '#3b82f6' },
    { name: 'Unknown Faces', value: unknown, color: '#ef4444' },
  ]

  const TOOLTIP_STYLE = {
    backgroundColor: '#0d1224',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: '12px',
    color: '#e2e8f0',
    fontSize: '12px',
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <TopBar title="Analytics & Reports" />

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="glass rounded-2xl p-6">
            <h3 className="font-bold text-white text-base mb-4 flex items-center gap-2">
              <BarChart2 className="w-5 h-5 text-primary-400" />
              Recognitions by Camera
            </h3>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={cameraData}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                <XAxis dataKey="name" tick={{ fill: '#64748b', fontSize: 11 }} />
                <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Bar dataKey="events" fill="#3b82f6" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="glass rounded-2xl p-6">
            <h3 className="font-bold text-white text-base mb-4 flex items-center gap-2">
              <Users className="w-5 h-5 text-teal-400" />
              Recognition Ratio
            </h3>
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label>
                  {pieData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip contentStyle={TOOLTIP_STYLE} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  )
}
