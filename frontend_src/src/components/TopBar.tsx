import { useEffect, useState } from 'react'
import { Clock, Sun, Moon, Camera as CameraIcon } from 'lucide-react'
import { useStore } from '../store/useStore'
import { Badge } from './ui/Badge'
import clsx from 'clsx'

export function TopBar({ title }: { title: string }) {
  const { health, cameras, theme, toggleTheme } = useStore()
  const [time, setTime] = useState(new Date())

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  const activeCamCount = cameras.filter(c => c.enabled && c.status !== 'OFFLINE').length
  const totalCamCount = cameras.length
  const isHealthy = health?.status === 'healthy'

  return (
    <header className="flex items-center justify-between px-6 py-3.5 border-b border-slate-200 dark:border-slate-800/80 glass flex-shrink-0 min-h-[64px] z-20">
      <div>
        <h1 className="text-base font-bold text-slate-900 dark:text-white tracking-tight">{title}</h1>
        <p className="text-[11px] text-slate-500 font-medium hidden md:block">Real-time CCTV Monitoring & Analytics Platform</p>
      </div>

      <div className="flex items-center gap-3">
        {/* Active Cameras Summary Pill */}
        <div className="hidden sm:flex items-center gap-2 px-3 py-1 rounded-xl bg-white/60 dark:bg-slate-900/80 border border-slate-200 dark:border-slate-800 text-xs text-slate-600 dark:text-slate-300">
          <CameraIcon className="w-3.5 h-3.5 text-blue-500 dark:text-blue-400" />
          <span className="font-semibold">{activeCamCount}/{totalCamCount} Active</span>
        </div>

        {/* System Health Badge */}
        <Badge variant={isHealthy ? 'success' : 'danger'} dot>
          {isHealthy ? 'System Online' : 'Check System'}
        </Badge>

        {/* Theme Toggle */}
        <button
          onClick={toggleTheme}
          className="w-8 h-8 rounded-xl bg-white/60 dark:bg-slate-900/80 border border-slate-200 dark:border-slate-800 flex items-center justify-center hover:border-slate-300 dark:hover:border-slate-700 text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition-all cursor-pointer"
          title={theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
        >
          {theme === 'dark' ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4 text-slate-600" />}
        </button>

        {/* Digital Clock */}
        <div className="flex items-center gap-1.5 px-3 py-1 rounded-xl bg-white/60 dark:bg-slate-900/80 border border-slate-200 dark:border-slate-800 text-xs font-mono text-slate-600 dark:text-slate-300">
          <Clock className="w-3.5 h-3.5 text-slate-400" />
          <span>{time.toLocaleTimeString()}</span>
        </div>
      </div>
    </header>
  )
}
