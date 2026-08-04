import React from 'react'
import clsx from 'clsx'

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode
  variant?: 'glass' | 'solid' | 'bordered'
  className?: string
}

export function Card({
  children,
  variant = 'glass',
  className,
  ...props
}: CardProps) {
  const variantClasses = {
    glass:
      'bg-white/85 dark:bg-slate-800/70 backdrop-blur-xl border border-slate-200 dark:border-slate-700/80 shadow-md dark:shadow-lg',
    solid:
      'bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-sm dark:shadow-md',
    bordered:
      'bg-transparent border border-slate-200 dark:border-slate-700/80',
  }

  return (
    <div
      className={clsx(
        'rounded-2xl transition-all duration-200 overflow-hidden',
        variantClasses[variant],
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
}

export function CardHeader({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={clsx('px-5 py-4 border-b border-slate-200 dark:border-slate-700/80 flex items-center justify-between', className)}>
      {children}
    </div>
  )
}

export function CardTitle({ children, className, icon }: { children: React.ReactNode; className?: string; icon?: React.ReactNode }) {
  return (
    <h3 className={clsx('text-sm font-bold text-slate-800 dark:text-slate-100 uppercase tracking-wider flex items-center gap-2', className)}>
      {icon}
      {children}
    </h3>
  )
}

export function CardBody({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={clsx('p-5', className)}>{children}</div>
}

export function CardFooter({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={clsx('px-5 py-3 border-t border-slate-200 dark:border-slate-700/80 bg-slate-50/80 dark:bg-slate-900/40 flex items-center justify-between', className)}>
      {children}
    </div>
  )
}
