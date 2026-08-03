import { useState, useEffect } from 'react'
import { CheckCircle2, AlertTriangle, AlertCircle, Info, X } from 'lucide-react'
import clsx from 'clsx'

export interface ToastMessage {
  id: string
  title: string
  message?: string
  type?: 'success' | 'warning' | 'error' | 'info'
  duration?: number
}

interface ToastContextType {
  toasts: ToastMessage[]
  addToast: (toast: Omit<ToastMessage, 'id'>) => void
  removeToast: (id: string) => void
}

let toastListener: ((toasts: ToastMessage[]) => void) | null = null
let toastMemoryList: ToastMessage[] = []

export const toast = {
  success: (title: string, message?: string) => showGlobalToast({ title, message, type: 'success' }),
  warning: (title: string, message?: string) => showGlobalToast({ title, message, type: 'warning' }),
  error: (title: string, message?: string) => showGlobalToast({ title, message, type: 'error' }),
  info: (title: string, message?: string) => showGlobalToast({ title, message, type: 'info' }),
}

function showGlobalToast(t: Omit<ToastMessage, 'id'>) {
  const id = `toast_${Date.now()}_${Math.random().toString(36).substr(2, 4)}`
  const newToast: ToastMessage = { ...t, id }
  toastMemoryList = [newToast, ...toastMemoryList].slice(0, 5)
  if (toastListener) toastListener([...toastMemoryList])

  setTimeout(() => {
    toastMemoryList = toastMemoryList.filter(item => item.id !== id)
    if (toastListener) toastListener([...toastMemoryList])
  }, t.duration || 4000)
}

export function ToastContainer() {
  const [toasts, setToasts] = useState<ToastMessage[]>([])

  useEffect(() => {
    toastListener = (updated) => setToasts(updated)
    return () => {
      toastListener = null
    }
  }, [])

  if (toasts.length === 0) return null

  const icons = {
    success: <CheckCircle2 className="w-5 h-5 text-emerald-400 flex-shrink-0" />,
    warning: <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0" />,
    error: <AlertCircle className="w-5 h-5 text-rose-400 flex-shrink-0" />,
    info: <Info className="w-5 h-5 text-blue-400 flex-shrink-0" />,
  }

  const borders = {
    success: 'border-emerald-500/40 bg-slate-900/90 text-emerald-300',
    warning: 'border-amber-500/40 bg-slate-900/90 text-amber-300',
    error: 'border-rose-500/40 bg-slate-900/90 text-rose-300',
    info: 'border-blue-500/40 bg-slate-900/90 text-blue-300',
  }

  return (
    <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2.5 max-w-sm w-full pointer-events-none">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={clsx(
            'pointer-events-auto p-3.5 rounded-2xl border backdrop-blur-xl shadow-2xl flex items-start gap-3 transition-all duration-200 animate-slide-in-right',
            borders[t.type || 'info']
          )}
        >
          {icons[t.type || 'info']}
          <div className="flex-1 min-w-0">
            <h5 className="text-xs font-bold text-white">{t.title}</h5>
            {t.message && <p className="text-[11px] text-slate-300 mt-0.5 leading-snug">{t.message}</p>}
          </div>
          <button
            onClick={() => {
              toastMemoryList = toastMemoryList.filter(item => item.id !== t.id)
              setToasts([...toastMemoryList])
            }}
            className="text-slate-500 hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      ))}
    </div>
  )
}
