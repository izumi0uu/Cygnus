// Blueprint stat tile — engineering title-block cell (sharp corners, blue line border, diamond marker).
export function Stat({ n, label, dot }: { n: number; label: string; dot?: string }) {
  return (
    <div className="bp-panel flex min-w-[120px] items-baseline gap-2 px-4 py-3">
      {dot && <span className="h-2 w-2 self-center rotate-45" style={{ background: dot }} />}
      <span className="font-mono text-[22px] font-bold tracking-tight">{n}</span>
      <span className="font-mono text-[10px] uppercase tracking-wide text-muted-foreground">{label}</span>
    </div>
  )
}
