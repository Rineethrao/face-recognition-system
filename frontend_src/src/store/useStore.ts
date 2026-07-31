import { create } from 'zustand'
import type { HealthData, CameraConfig, RecognitionEvent } from '../lib/api'

type Theme = 'light' | 'dark'

interface AppState {
  health: HealthData | null
  cameras: CameraConfig[]
  recentEvents: RecognitionEvent[]
  activeCamera: string | null
  sidebarCollapsed: boolean
  theme: Theme

  setHealth: (h: HealthData) => void
  setCameras: (c: CameraConfig[]) => void
  setRecentEvents: (e: RecognitionEvent[]) => void
  addEvent: (e: RecognitionEvent) => void
  setActiveCamera: (id: string) => void
  toggleSidebar: () => void
  toggleTheme: () => void
  setTheme: (t: Theme) => void
}

function getInitialTheme(): Theme {
  if (typeof window === 'undefined') return 'dark'
  const stored = localStorage.getItem('app-theme')
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

export const useStore = create<AppState>((set) => ({
  health: null,
  cameras: [],
  recentEvents: [],
  activeCamera: null,
  sidebarCollapsed: false,
  theme: getInitialTheme(),

  setHealth: (h) => set({ health: h }),
  setCameras: (c) => set({ cameras: c }),
  setRecentEvents: (e) => set({ recentEvents: e }),
  addEvent: (e) =>
    set((s) => ({
      recentEvents: [e, ...s.recentEvents].slice(0, 100),
    })),
  setActiveCamera: (id) => set({ activeCamera: id }),
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  toggleTheme: () =>
    set((s) => {
      const next = s.theme === 'dark' ? 'light' : 'dark'
      localStorage.setItem('app-theme', next)
      return { theme: next }
    }),
  setTheme: (t) => {
    localStorage.setItem('app-theme', t)
    set({ theme: t })
  },
}))
