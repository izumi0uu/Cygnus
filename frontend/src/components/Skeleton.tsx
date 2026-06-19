import { cn } from '@/lib/utils'

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded-lg bg-muted', className)} />
}

// Generic console-page loading skeleton: a stat-tile row + a content block.
export function PageSkeleton() {
  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-[88px] min-w-[130px] flex-1" />
        ))}
      </div>
      <Skeleton className="h-[320px] w-full" />
    </div>
  )
}
