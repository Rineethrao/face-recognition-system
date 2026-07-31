import { useState } from 'react'
import { Save, Sliders } from 'lucide-react'

import { TopBar } from '../components/TopBar'

export function Settings() {
  const [similarity, setSimilarity] = useState('0.45')
  const [detectionFps, setDetectionFps] = useState('8')
  const [qualityThresh, setQualityThresh] = useState('55')
  const [saved, setSaved] = useState(false)

  const handleSave = () => {
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <TopBar title="Settings" />

      <div className="flex-1 overflow-y-auto p-6 max-w-2xl mx-auto w-full space-y-6">
        <div className="glass rounded-2xl p-6 border border-white/5 space-y-6">
          <div className="flex items-center gap-3 pb-4 border-b border-white/5">
            <div className="w-10 h-10 rounded-xl bg-primary-500/15 text-primary-400 flex items-center justify-center">
              <Sliders className="w-5 h-5" />
            </div>
            <div>
              <h2 className="font-bold text-white text-lg">Engine Parameters</h2>
              <p className="text-xs text-slate-400">Configure AI detection, thresholds, and performance</p>
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <label className="text-xs font-medium text-slate-300 mb-1 block">Recognition Similarity Threshold ({similarity})</label>
              <input
                type="range"
                min="0.30"
                max="0.85"
                step="0.05"
                value={similarity}
                onChange={e => setSimilarity(e.target.value)}
                className="w-full"
              />
              <span className="text-[10px] text-slate-500">Lower = more false positives, Higher = stricter matching.</span>
            </div>

            <div>
              <label className="text-xs font-medium text-slate-300 mb-1 block">Target Detection FPS ({detectionFps} FPS)</label>
              <input
                type="range"
                min="2"
                max="25"
                step="1"
                value={detectionFps}
                onChange={e => setDetectionFps(e.target.value)}
                className="w-full"
              />
            </div>

            <div>
              <label className="text-xs font-medium text-slate-300 mb-1 block">Face Quality Gate Threshold ({qualityThresh}%)</label>
              <input
                type="range"
                min="30"
                max="80"
                step="5"
                value={qualityThresh}
                onChange={e => setQualityThresh(e.target.value)}
                className="w-full"
              />
            </div>

            <button onClick={handleSave} className="btn-primary w-full justify-center">
              <Save className="w-4 h-4" /> {saved ? 'Settings Saved!' : 'Save Configuration'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
