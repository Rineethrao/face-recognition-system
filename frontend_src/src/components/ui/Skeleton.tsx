import clsx from 'clsx'

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={clsx(
        'skeleton rounded-xl transition-all duration-300',
        className
      )}
    />
  )
}

export function StatCardSkeleton() {
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-5 space-y-3">
      <div className="flex items-center justify-between">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-8 w-8 rounded-xl" />
      </div>
      <Skeleton className="h-7 w-20" />
      <Skeleton className="h-3 w-36" />
    </div>
  )
}

export function CameraCardSkeleton() {
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-2xl overflow-hidden aspect-video relative flex items-center justify-center p-4">
      <Skeleton className="w-full h-full rounded-xl" />
    </div>
  )
}

export function TableRowSkeleton() {
  return (
    <div className="flex items-center gap-4 px-4 py-3 border-b border-slate-800/60">
      <Skeleton className="w-9 h-9 rounded-xl flex-shrink-0" />
      <div className="flex-1 space-y-1.5">
        <Skeleton className="h-3.5 w-1/3" />
        <Skeleton className="h-2.5 w-1/4" />
      </div>
      <Skeleton className="h-6 w-16 rounded-full" />
    </div>
  )
}
