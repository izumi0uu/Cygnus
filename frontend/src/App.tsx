import { Routes, Route } from 'react-router-dom'
import Landing from '@/pages/Landing'
import AppShell from '@/components/layout/AppShell'
import ReviewQueue from '@/pages/ReviewQueue'
import Placeholder from '@/pages/Placeholder'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/console" element={<AppShell />}>
        <Route index element={<ReviewQueue />} />
        <Route path="objects" element={<Placeholder sectionKey="objects" />} />
        <Route path="sources" element={<Placeholder sectionKey="sources" />} />
        <Route path="audience" element={<Placeholder sectionKey="audience" />} />
        <Route path="drift" element={<Placeholder sectionKey="drift" />} />
        <Route path="propagation" element={<Placeholder sectionKey="propagation" />} />
        <Route path="audit" element={<Placeholder sectionKey="audit" />} />
      </Route>
    </Routes>
  )
}
