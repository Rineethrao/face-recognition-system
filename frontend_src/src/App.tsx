import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'

import { Sidebar } from './components/Sidebar'
import { Dashboard } from './pages/Dashboard'
import { LiveRecognition } from './pages/LiveRecognition'
import { Cameras } from './pages/Cameras'
import { Persons } from './pages/Persons'
import { RegisterPerson } from './pages/RegisterPerson'
import { Events } from './pages/Events'
import { Analytics } from './pages/Analytics'
import { Settings } from './pages/Settings'
import { useStore } from './store/useStore'

export default function App() {
  const { theme } = useStore()

  useEffect(() => {
    const root = window.document.documentElement
    if (theme === 'dark') {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }
  }, [theme])

  return (
    <BrowserRouter>
      <div className="flex h-screen w-screen overflow-hidden bg-navy-950 transition-colors duration-300">
        <Sidebar />
        <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/live" element={<LiveRecognition />} />
            <Route path="/cameras" element={<Cameras />} />
            <Route path="/persons" element={<Persons />} />
            <Route path="/register" element={<RegisterPerson />} />
            <Route path="/events" element={<Events />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
