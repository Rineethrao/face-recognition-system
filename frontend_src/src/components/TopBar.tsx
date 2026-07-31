import { useEffect, useState } from 'react'
import { Bell, Cpu, Clock, Sun, Moon } from 'lucide-react'
import { useStore } from '../store/useStore'
import clsx from 'clsx'

export function TopBar({ title }: { title: string }) {
  const { health, theme, toggleTheme } = useStore()
  const [time, setTime] = useState(new Date())

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  const cpu = health?.system?.cpu_percent ?? 0
  const isHealthy = health?.status === 'healthy'

  return (
    <header className="flex items-center justify-between px-6 py-3.5 border-b border-white/5 glass flex-shrink-0">
      <h1 className="text-lg font-bold text-slate-800 dark:text-white transition-colors">{title}</h1>

      <div className="flex items-center gap-3">
        {/* System health */}
        <div className={clsx(
          'flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold border transition-all',
          isHealthy
            ? 'bg-green-500/10 text-green-600 dark:text-green-400 border-green-500/25'
            : 'bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/25'
        )}>
          <span className={clsx('w-1.5 h-1.5 rounded-full', isHealthy ? 'online-dot' : 'live-dot')} />
          {isHealthy ? 'Healthy' : 'Degraded'}
        </div>

        {/* CPU */}
        <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400 glass px-3 py-1.5 rounded-full border border-white/5">
          <Cpu className="w-3.5 h-3.5 text-primary-500 dark:text-primary-400" />
          <span className="font-mono">{cpu.toFixed(0)}%</span>
        </div>

        {/* Theme Toggle Button */}
        <button
          onClick={toggleTheme}
          className="w-8 h-8 rounded-full glass border border-white/5 flex items-center justify-center hover:border-primary-500/30 text-slate-500 dark:text-slate-400 hover:text-primary-500 dark:hover:text-primary-400 transition-all cursor-pointer group"
          title={theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
        >
          {theme === 'dark' ? (
            <Sun className="w-4 h-4 transition-transform group-hover:rotate-45" />
          ) : (
            <Moon className="w-4 h-4 transition-transform group-hover:-rotate-12" />
          )}
        </button>

        {/* Alerts bell */}
        <button className="relative w-8 h-8 rounded-full glass border border-white/5 flex items-center justify-center hover:border-primary-500/30 text-slate-500 dark:text-slate-400 hover:text-primary-500 dark:hover:text-primary-400 transition-all cursor-pointer">
          <Bell className="w-4 h-4" />
        </button>

        {/* Clock */}
        <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
          <Clock className="w-3.5 h-3.5" />
          <span className="font-mono">{time.toLocaleTimeString()}</span>
        </div>
      </div>
    </header>
  )
}
