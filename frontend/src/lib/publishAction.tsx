import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react'
import type { PublishApplyResult } from '@/lib/api'

// The last publish action run from any PublishPreviewModal in the session.
//
// APPLY is deliberately persisted:false (the backend store is fixture-backed),
// so a trace *refetch* after apply returns byte-identical data. Instead of
// pretending the trace changed, the traceability drawer reads this context and
// renders a clearly-tagged *projection* of what the apply would open / remove /
// hold. This keeps the fixture/rehearsal nature honest: the loop is real, the
// durability is not, and the UI never claims durable state the backend lacks.
export type PublishActionRecord = {
  objectRef: string
  result: PublishApplyResult
  // session-only monotonic id, so consumers can detect "a new apply happened"
  // without Date.now() in render.
  seq: number
}

type PublishActionContextValue = {
  last: PublishActionRecord | null
  record: (objectRef: string, result: PublishApplyResult) => void
  clear: () => void
}

const PublishActionContext = createContext<PublishActionContextValue>({
  last: null,
  record: () => {},
  clear: () => {},
})

export function PublishActionProvider({ children }: { children: ReactNode }) {
  const seqRef = useRef(0)
  const [last, setLast] = useState<PublishActionRecord | null>(null)

  const record = useCallback((objectRef: string, result: PublishApplyResult) => {
    seqRef.current += 1
    setLast({ objectRef, result, seq: seqRef.current })
  }, [])

  const clear = useCallback(() => setLast(null), [])

  return (
    <PublishActionContext.Provider value={{ last, record, clear }}>
      {children}
    </PublishActionContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export const usePublishAction = () => useContext(PublishActionContext)
