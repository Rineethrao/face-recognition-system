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
      'bg-white/70 dark:bg-slate-900/80 backdrop-blur-xl border border-slate-200 dark:border-slate-800 shadow-xl',
    solid:
      'bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-md',
    bordered:
      'bg-transparent border border-slate-200 dark:border-slate-800/80',
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
    <div className={clsx('px-5 py-4 border-b border-slate-200 dark:border-slate-800/80 flex items-center justify-between', className)}>
      {children}
    </div>
  )
}

export function CardTitle({ children, className, icon }: { children: React.ReactNode; className?: string; icon?: React.ReactNode }) {
  return (
    <h3 className={clsx('text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider flex items-center gap-2', className)}>
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
    <div className={clsx('px-5 py-3 border-t border-slate-200 dark:border-slate-800/80 bg-slate-100/40 dark:bg-slate-950/40 flex items-center justify-between', className)}>
      {children}
    </div>
  )
}
