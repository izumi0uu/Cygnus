import { lazy } from 'react'
import { Routes, Route } from 'react-router-dom'
import Landing from '@/pages/Landing'
import AppShell from '@/components/layout/AppShell'
import RequireAuth from '@/components/RequireAuth'
import RequireAdmin from '@/components/RequireAdmin'
import { AuthProvider } from '@/lib/auth'
import { ToastProvider } from '@/lib/toast'
import Login from '@/pages/Login'

const Overview = lazy(() => import('@/pages/Overview'))
const Copilot = lazy(() => import('@/pages/Copilot'))
const ReviewQueue = lazy(() => import('@/pages/ReviewQueue'))
const AudiencePublish = lazy(() => import('@/pages/AudiencePublish'))
const KnowledgeObjects = lazy(() => import('@/pages/KnowledgeObjects'))
const SourcesEvidence = lazy(() => import('@/pages/SourcesEvidence'))
const CoverageDrift = lazy(() => import('@/pages/CoverageDrift'))
const TicketInsights = lazy(() => import('@/pages/TicketInsights'))
const Propagation = lazy(() => import('@/pages/Propagation'))
const RecoveryDetail = lazy(() => import('@/pages/RecoveryDetail'))
const Audit = lazy(() => import('@/pages/Audit'))
const EmployeeManagement = lazy(() => import('@/pages/EmployeeManagement'))
const RoleManagement = lazy(() => import('@/pages/RoleManagement'))
const Settings = lazy(() => import('@/pages/Settings'))
const PlotterDemo = lazy(() => import('@/pages/PlotterDemo'))
const Mastermind = lazy(() => import('@/pages/Mastermind'))

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route element={<RequireAuth />}>
            <Route path="/demo/plotter" element={<PlotterDemo />} />
            <Route path="/demo/mastermind" element={<Mastermind />} />
            <Route path="/console" element={<AppShell />}>
              <Route index element={<Overview />} />
              <Route path="copilot" element={<Copilot />} />
              <Route path="queue" element={<ReviewQueue />} />
              <Route path="objects" element={<KnowledgeObjects />} />
              <Route path="sources" element={<SourcesEvidence />} />
              <Route path="tickets" element={<TicketInsights />} />
              <Route path="audience" element={<AudiencePublish />} />
              <Route path="drift" element={<CoverageDrift />} />
              <Route path="propagation" element={<Propagation />} />
              <Route path="recovery/:commandId" element={<RecoveryDetail />} />
              <Route path="audit" element={<Audit />} />
              <Route element={<RequireAdmin />}>
                <Route path="employees" element={<EmployeeManagement />} />
                <Route path="roles" element={<RoleManagement />} />
                <Route path="settings" element={<Settings />} />
              </Route>
            </Route>
          </Route>
        </Routes>
      </ToastProvider>
    </AuthProvider>
  )
}
