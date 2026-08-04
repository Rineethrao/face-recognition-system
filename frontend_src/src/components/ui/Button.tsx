import React from 'react'
import clsx from 'clsx'
import { Loader2 } from 'lucide-react'

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  children?: React.ReactNode
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'success'
  size?: 'sm' | 'md' | 'lg'
  isLoading?: boolean
  icon?: React.ReactNode
}

export function Button({
  children,
  variant = 'primary',
  size = 'md',
  isLoading = false,
  icon,
  className,
  disabled,
  ...props
}: ButtonProps) {
  const sizeClasses = {
    sm: 'px-2.5 py-1.5 text-xs rounded-lg gap-1.5',
    md: 'px-4 py-2 text-xs font-semibold rounded-xl gap-2',
    lg: 'px-5 py-2.5 text-sm font-bold rounded-xl gap-2.5',
  }

  const variantClasses = {
    primary:
      'bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white shadow-md shadow-blue-600/15 border border-blue-500/25',
    secondary:
      'bg-white hover:bg-slate-50 active:bg-slate-100 text-slate-700 border border-slate-200 dark:bg-slate-800/80 dark:hover:bg-slate-700 dark:active:bg-slate-900 dark:text-slate-200 dark:border-slate-600',
    ghost:
      'bg-transparent hover:bg-slate-100 text-slate-500 hover:text-slate-800 dark:hover:bg-slate-800/60 dark:text-slate-400 dark:hover:text-slate-200',
    danger:
      'bg-rose-500/10 hover:bg-rose-500/20 active:bg-rose-500/30 text-rose-600 dark:text-rose-400 border border-rose-500/30',
    success:
      'bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-white shadow-md shadow-emerald-600/15 border border-emerald-500/25',
  }

  return (
    <button
      disabled={disabled || isLoading}
      className={clsx(
        'inline-flex items-center justify-center font-semibold transition-all duration-150 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed select-none',
        sizeClasses[size],
        variantClasses[variant],
        className
      )}
      {...props}
    >
      {isLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : icon}
      {children}
    </button>
  )
}
