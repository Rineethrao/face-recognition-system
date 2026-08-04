import React from 'react'
import clsx from 'clsx'

export interface EmptyStateProps {
  icon: React.ReactNode
  title: string
  description?: string
  action?: React.ReactNode
  className?: string
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={clsx(
        'flex flex-col items-center justify-center p-8 text-center rounded-2xl border border-dashed border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 space-y-3 min-h-[220px]',
        className
      )}
    >
      <div className="w-12 h-12 rounded-2xl bg-white dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700/80 flex items-center justify-center text-slate-500 dark:text-slate-400">
        {icon}
      </div>
      <div>
        <h4 className="text-sm font-bold text-slate-800 dark:text-slate-100 mb-1">{title}</h4>
        {description && (
          <p className="text-xs text-slate-500 dark:text-slate-400 max-w-sm mx-auto leading-relaxed">
            {description}
          </p>
        )}
      </div>
      {action && <div className="pt-2">{action}</div>}
    </div>
  )
}
