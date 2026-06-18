import * as React from 'react'
import { cn } from '@/lib/utils'

type Variant = 'primary' | 'ghost' | 'outline'
type Size = 'default' | 'sm' | 'icon'

const VARIANT: Record<Variant, string> = {
  primary: 'bg-primary text-primary-foreground hover:bg-primary/90 active:translate-y-px',
  ghost: 'bg-card border border-border text-muted-foreground hover:bg-muted hover:text-foreground',
  outline: 'border border-border bg-card text-foreground hover:bg-muted',
}
const SIZE: Record<Size, string> = {
  default: 'h-9 px-4 text-sm',
  sm: 'h-8 px-3 text-xs',
  icon: 'h-9 w-9',
}

export function Button({
  variant = 'primary',
  size = 'default',
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center gap-1.5 rounded-full font-semibold transition-colors disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background',
        VARIANT[variant],
        SIZE[size],
        className,
      )}
      {...props}
    />
  )
}
