import { Routes, Route } from 'react-router-dom'
import Landing from '@/pages/Landing'
import AppShell from '@/components/layout/AppShell'
import Overview from '@/pages/Overview'
import ReviewQueue from '@/pages/ReviewQueue'
import AudiencePublish from '@/pages/AudiencePublish'
import KnowledgeObjects from '@/pages/KnowledgeObjects'
import SourcesEvidence from '@/pages/SourcesEvidence'
import CoverageDrift from '@/pages/CoverageDrift'
import Placeholder from '@/pages/Placeholder'

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
