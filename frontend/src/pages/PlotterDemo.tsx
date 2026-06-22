import { useMemo, useState } from 'react'
import { PlotterPanel } from '@/components/PlotterPanel'

/**
 * PlotterDemo — isolated view of the "pen plotter" reveal (HANDOFF §12 Idea 1).
 *
 * Route-guard-free so you can view it with `pnpm dev` alone — no backend, no
 * login. The controls stay minimal (handy, not a lab). Numbers in the sample
 * sheet are stable so REPLAY shows the same layout — only the animation
 * re-runs.
 */
const NODES = [
  { id: 'NODE-01', val: 412 },
  { id: 'NODE-02', val: 877 },
  { id: 'NODE-03', val: 203 },
]

export default function PlotterDemo() {
  const [epoch, setEpoch] = useState(0)
  const [lapMs, setLapMs] = useState(1050)

  const stableBody = useMemo(
    () => (
      <div className="p-6">
        <p className="font-mono text-[12px] leading-relaxed text-[var(--card-foreground)]">
          The pen laps the four edges while content seeps in from all four
          sides at different speeds. Title-block values write last, as the pen
          labels what it drew. Adjust LAP and REPLAY to feel the pacing.
        </p>
        <div className="mt-4 grid grid-cols-3 gap-3">
          {NODES.map((n) => (
            <div key={n.id} className="bp-panel p-3">
              <span className="bp-label">{n.id}</span>
              <div className="mt-2 font-mono text-[11px] text-[var(--faint)]">
                {n.val}
              </div>
            </div>
          ))}
        </div>
      </div>
    ),
    [],
  )

  return (
    <div className="bp-grid min-h-screen w-full p-8">
      <div className="mx-auto max-w-3xl">
        <div className="mb-4 flex items-baseline justify-between">
          <span className="bp-label">DWG-DEMO · PLOTTER REVEAL</span>
          <span className="bp-label" style={{ opacity: 0.5 }}>
            §12 Idea 1
          </span>
        </div>

        <div className="bp-panel mb-6 flex flex-wrap items-end gap-6 p-4">
          <div className="flex flex-col gap-1">
            <span className="bp-label">LAP (ms)</span>
            <input
              type="range"
              min={300}
              max={2000}
              step={50}
              value={lapMs}
              onChange={(e) => setLapMs(Number(e.target.value))}
              className="accent-[var(--primary)]"
            />
            <span className="font-mono text-[10px] text-[var(--faint)]">
              {(lapMs / 1000).toFixed(2)}s · content seeps while pen draws
            </span>
          </div>
          <button
            type="button"
            className="bp-cmd"
            onClick={() => setEpoch((n) => n + 1)}
          >
            REPLAY ↻
          </button>
        </div>

        <PlotterPanel
          label="PLOTTER PANEL · SAMPLE SHEET"
          drawingId="DWG-P01"
          lapDuration={lapMs / 1000}
          replayKey={epoch}
          titleBlock={[
            { key: 'SHEET', value: 'A3 · LANDSCAPE' },
            { key: 'SCALE', value: '1:1' },
            { key: 'TOL', value: '±0.05mm' },
            { key: 'REV', value: 'A' },
          ]}
        >
          {stableBody}
        </PlotterPanel>

        <p className="mt-4 font-mono text-[10px] text-[var(--faint)]">
          Route /demo/plotter · no auth required · view with{' '}
          <span className="text-[var(--primary)]">pnpm dev</span> alone
        </p>
      </div>
    </div>
  )
}
