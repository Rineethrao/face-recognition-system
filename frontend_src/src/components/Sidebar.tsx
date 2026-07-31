import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, Video, Camera, Users, UserPlus,
  Bell, BarChart2, Settings, LogOut, ChevronLeft, Shield,
} from 'lucide-react'
import { useStore } from '../store/useStore'
import clsx from 'clsx'

const navItems = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/live', icon: Video, label: 'Live Recognition' },
  { to: '/cameras', icon: Camera, label: 'Cameras' },
  { to: '/persons', icon: Users, label: 'Registered Persons' },
  { to: '/register', icon: UserPlus, label: 'Register Person' },
  { to: '/events', icon: Bell, label: 'Events' },
  { to: '/analytics', icon: BarChart2, label: 'Analytics' },
  { to: '/settings', icon: Settings, label: 'Settings' },
]

export function Sidebar() {
  const { sidebarCollapsed, toggleSidebar, health } = useStore()

  return (
    <aside
      className={clsx(
        'flex flex-col h-screen glass border-r border-white/5 transition-all duration-300 ease-in-out flex-shrink-0',
        sidebarCollapsed ? 'w-16' : 'w-60'
      )}
    >
      {/* Logo */}
      <div className="flex items-center gap-3 px-4 py-5 border-b border-white/5 min-h-[72px]">
        <div className="flex-shrink-0 w-9 h-9 rounded-xl bg-gradient-to-br from-primary-500 to-teal-500 flex items-center justify-center shadow-lg shadow-primary-500/20">
          <Shield className="w-5 h-5 text-white" />
        </div>
        {!sidebarCollapsed && (
          <div className="animate-fade-in overflow-hidden">
            <div className="text-base font-bold gradient-text whitespace-nowrap">AI.Vision</div>
            <div className="text-[10px] text-slate-500 whitespace-nowrap">Enterprise CCTV Platform</div>
          </div>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 px-2 py-4 space-y-1 overflow-y-auto">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              clsx(
                'nav-item group',
                isActive && 'active',
                sidebarCollapsed && 'justify-center px-2'
              )
            }
            title={sidebarCollapsed ? label : undefined}
          >
            <Icon className="w-4.5 h-4.5 flex-shrink-0" />
            {!sidebarCollapsed && (
              <span className="animate-fade-in whitespace-nowrap">{label}</span>
            )}
          </NavLink>
        ))}
      </nav>

      {/* System Status */}
      {!sidebarCollapsed && (
        <div className="px-3 py-3 border-t border-white/5">
          <div className="glass rounded-xl px-3 py-2.5">
            <div className="flex items-center gap-2 mb-2">
              <span className={clsx(
                'w-2 h-2 rounded-full flex-shrink-0',
                health?.status === 'healthy' ? 'online-dot' : 'live-dot'
              )} />
              <span className="text-xs font-semibold text-slate-300">
                {health?.status === 'healthy' ? 'System Online' : 'System Check'}
              </span>
            </div>
            <div className="text-[10px] text-slate-500 space-y-0.5">
              <div className="flex justify-between">
                <span>FAISS Vectors</span>
                <span className="text-primary-400 font-mono">
                  {health?.faiss?.total_registered_vectors ?? 0}
                </span>
              </div>
              <div className="flex justify-between">
                <span>Persons DB</span>
                <span className="text-teal-400 font-mono">
                  {health?.database?.total_persons ?? 0}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Bottom actions */}
      <div className={clsx('px-2 pb-4 space-y-1', sidebarCollapsed && 'flex flex-col items-center')}>
        <button
          onClick={toggleSidebar}
          className="nav-item w-full"
          title={sidebarCollapsed ? 'Expand' : 'Collapse'}
        >
          <ChevronLeft className={clsx('w-4 h-4 transition-transform duration-300', sidebarCollapsed && 'rotate-180')} />
          {!sidebarCollapsed && <span>Collapse</span>}
        </button>
        <button className="nav-item w-full text-red-400 hover:text-red-300 hover:bg-red-500/5">
          <LogOut className="w-4 h-4 flex-shrink-0" />
          {!sidebarCollapsed && <span>Logout</span>}
        </button>
      </div>
    </aside>
  )
}
