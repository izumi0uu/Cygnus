export function Stat({ n, label, dot }: { n: number; label: string; dot?: string }) {
  return (
    <div className="flex min-w-[120px] items-baseline gap-2 rounded-xl border border-border bg-card px-4 py-3 shadow-card">
      {dot && <span className="h-2 w-2 self-center rounded-full" style={{ background: dot }} />}
      <span className="text-[22px] font-bold tracking-tight">{n}</span>
      <span className="font-mono text-[10px] uppercase tracking-wide text-muted-foreground">{label}</span>
    </div>
  )
}
