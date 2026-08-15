import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn('animate-pulse motion-reduce:animate-none rounded-lg bg-muted', className)} />
}

// Generic console-page loading skeleton: a stat-tile row + a content block.
export function PageSkeleton() {
  const { t } = useTranslation()
  return (
    <div className="bp-page-skeleton" role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">{t('state.loading')}</span>
      <div className="mb-4 flex flex-wrap gap-3">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-[88px] min-w-[130px] flex-1" />
        ))}
      </div>
      <Skeleton className="h-[320px] w-full" />
    </div>
  )
}
