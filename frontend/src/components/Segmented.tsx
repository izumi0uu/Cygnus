import { cn } from '@/lib/utils'

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  className,
}: {
  options: { value: T; label: string }[]
  value: T
  onChange: (v: T) => void
  className?: string
}) {
  const n = options.length
  const idx = Math.max(0, options.findIndex((o) => o.value === value))
  return (
    <div className={cn('seg', className)} role="tablist">
      <span
        className="seg-glider"
        style={{ width: `calc((100% - 10px) / ${n})`, transform: `translateX(${idx * 100}%)` }}
      />
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={value === o.value}
          data-on={value === o.value}
          className="seg-btn flex-1"
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
