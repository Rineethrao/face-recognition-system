import React from 'react'
import clsx from 'clsx'

export interface BadgeProps {
  children: React.ReactNode
  variant?: 'success' | 'warning' | 'danger' | 'info' | 'neutral'
  size?: 'sm' | 'md'
  dot?: boolean
  className?: string
}

export function Badge({
  children,
  variant = 'neutral',
  size = 'md',
  dot = false,
  className,
}: BadgeProps) {
  const variantClasses = {
    success:
      'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/30',
    warning:
      'bg-amber-500/15 text-amber-700 dark:text-amber-400 border-amber-500/30',
    danger:
      'bg-rose-500/15 text-rose-700 dark:text-rose-400 border-rose-500/30',
    info:
      'bg-blue-500/15 text-blue-700 dark:text-blue-400 border-blue-500/30',
    neutral:
      'bg-slate-100 text-slate-600 border-slate-200 dark:bg-slate-800/80 dark:text-slate-300 dark:border-slate-600',
  }

  const dotClasses = {
    success: 'bg-emerald-400',
    warning: 'bg-amber-400',
    danger: 'bg-rose-400',
    info: 'bg-blue-400',
    neutral: 'bg-slate-400',
  }

  const sizeClasses = {
    sm: 'text-[10px] px-2 py-0.5 font-bold',
    md: 'text-xs px-2.5 py-1 font-semibold',
  }

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full border backdrop-blur-md transition-colors',
        sizeClasses[size],
        variantClasses[variant],
        className
      )}
    >
      {dot && <span className={clsx('w-1.5 h-1.5 rounded-full flex-shrink-0', dotClasses[variant])} />}
      {children}
    </span>
  )
}
