import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, Video, Camera, Users, UserPlus,
  Bell, BarChart2, Settings, ChevronLeft, Shield, Radio, Sparkles
} from 'lucide-react'
import { useStore } from '../store/useStore'
import clsx from 'clsx'
import logoImg from '../assets/logo.png'

interface NavGroup {
  groupName?: string
  items: {
    to: string
    icon: any
    label: string
    featured?: boolean
  }[]
}

const navGroups: NavGroup[] = [
  {
    groupName: 'Overview',
    items: [
      { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
    ],
  },
  {
    groupName: 'Monitoring',
    items: [
      { to: '/live', icon: Video, label: 'Live Recognition' },
      { to: '/cameras', icon: Camera, label: 'Cameras' },
    ],
  },
  {
    groupName: 'People',
    items: [
      { to: '/persons', icon: Users, label: 'Registered Persons' },
      { to: '/register', icon: UserPlus, label: 'Register Person', featured: true },
    ],
  },
  {
    groupName: 'Insights',
    items: [
      { to: '/events', icon: Bell, label: 'Events' },
      { to: '/analytics', icon: BarChart2, label: 'Analytics & Reports' },
    ],
  },
  {
    groupName: 'System',
    items: [
      { to: '/settings', icon: Settings, label: 'Settings' },
    ],
  },
]

export function Sidebar() {
  const { sidebarCollapsed, toggleSidebar, health } = useStore()
  const isHealthy = health?.status === 'healthy'

  return (
    <aside
      className={clsx(
        'flex flex-col h-screen glass border-r border-slate-200 dark:border-slate-800 transition-all duration-200 ease-in-out flex-shrink-0 z-30 select-none',
        sidebarCollapsed ? 'w-20' : 'w-64'
      )}
    >
      {/* Brand Header */}
      <div className="flex items-center justify-between px-4 py-4 border-b border-slate-200 dark:border-slate-800/80 min-h-[72px]">
        <div className="flex items-center gap-3 overflow-hidden">
          <div className="flex-shrink-0 w-11 h-11 rounded-xl bg-white border border-slate-200 dark:border-slate-800/50 flex items-center justify-center p-1 shadow-md">
            <img src={logoImg} alt="VisionTrack Logo" className="w-full h-full object-contain" />
          </div>
          {!sidebarCollapsed && (
            <div className="min-w-0">
              <div className="text-sm font-bold text-slate-900 dark:text-white tracking-tight flex items-center gap-1">
                <span className="text-blue-500">👁️</span> VisionTrack AI
              </div>
              <div className="text-[9px] font-medium text-slate-500 dark:text-slate-400 truncate">Intelligent Video Security</div>
            </div>
          )}
        </div>
      </div>

      {/* Navigation Menu */}
      <nav className="flex-1 px-3 py-4 space-y-5 overflow-y-auto">
        {navGroups.map((group, idx) => (
          <div key={group.groupName || idx} className="space-y-1">
            {!sidebarCollapsed && group.groupName && (
              <div className="px-2 mb-1.5 text-[10px] font-extrabold uppercase tracking-wider text-slate-500">
                {group.groupName}
              </div>
            )}
            {group.items.map(({ to, icon: Icon, label, featured }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  clsx(
                    'nav-item group relative transition-all duration-150',
                    isActive && 'active font-bold',
                    featured && !isActive && 'bg-blue-600/10 text-blue-400 border border-blue-500/30 hover:bg-blue-600/20',
                    featured && isActive && 'bg-blue-600 text-white shadow-md shadow-blue-600/25',
                    sidebarCollapsed && 'justify-center px-2 py-2.5'
                  )
                }
                title={sidebarCollapsed ? label : undefined}
              >
                <Icon className={clsx('w-4 h-4 flex-shrink-0', featured && !sidebarCollapsed && 'text-blue-400')} />
                {!sidebarCollapsed && (
                  <span className="truncate flex-1 flex items-center justify-between">
                    {label}
                    {featured && (
                      <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
                    )}
                  </span>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      {/* System Status Footbar */}
      {!sidebarCollapsed && (
        <div className="px-3 py-3 border-t border-slate-800/80 bg-slate-950/40">
          <div className="flex items-center justify-between text-xs px-2 py-1.5 rounded-xl bg-slate-900/80 border border-slate-800">
            <div className="flex items-center gap-2">
              <span className={clsx('w-2 h-2 rounded-full', isHealthy ? 'bg-emerald-400' : 'bg-rose-400 animate-ping')} />
              <span className="text-[11px] font-semibold text-slate-300">
                {isHealthy ? 'System Active' : 'System Degraded'}
              </span>
            </div>
            <span className="text-[10px] font-mono text-slate-500">v2.0</span>
          </div>
        </div>
      )}

      {/* Collapse Toggle */}
      <div className="px-3 py-2 border-t border-slate-800/80 flex items-center justify-end">
        <button
          onClick={toggleSidebar}
          className="p-1.5 rounded-xl hover:bg-slate-800/80 text-slate-400 hover:text-white transition-colors cursor-pointer w-full flex items-center justify-center gap-2"
          title={sidebarCollapsed ? 'Expand Sidebar' : 'Collapse Sidebar'}
        >
          <ChevronLeft className={clsx('w-4 h-4 transition-transform duration-200', sidebarCollapsed && 'rotate-180')} />
          {!sidebarCollapsed && <span className="text-[11px] font-semibold text-slate-400">Collapse</span>}
        </button>
      </div>
    </aside>
  )
}
