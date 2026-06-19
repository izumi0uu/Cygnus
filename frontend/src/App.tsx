import { lazy } from 'react'
import { Routes, Route } from 'react-router-dom'
import Landing from '@/pages/Landing'
import AppShell from '@/components/layout/AppShell'

const Overview = lazy(() => import('@/pages/Overview'))
const ReviewQueue = lazy(() => import('@/pages/ReviewQueue'))
const AudiencePublish = lazy(() => import('@/pages/AudiencePublish'))
const KnowledgeObjects = lazy(() => import('@/pages/KnowledgeObjects'))
const SourcesEvidence = lazy(() => import('@/pages/SourcesEvidence'))
const CoverageDrift = lazy(() => import('@/pages/CoverageDrift'))
const Placeholder = lazy(() => import('@/pages/Placeholder'))

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/console" element={<AppShell />}>
        <Route index element={<Overview />} />
        <Route path="queue" element={<ReviewQueue />} />
        <Route path="objects" element={<KnowledgeObjects />} />
        <Route path="sources" element={<SourcesEvidence />} />
        <Route path="audience" element={<AudiencePublish />} />
        <Route path="drift" element={<CoverageDrift />} />
        <Route path="propagation" element={<Placeholder sectionKey="propagation" />} />
        <Route path="audit" element={<Placeholder sectionKey="audit" />} />
      </Route>
    </Routes>
  )
}
