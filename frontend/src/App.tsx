import { Routes, Route } from 'react-router-dom'
import Landing from '@/pages/Landing'
import Console from '@/pages/Console'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/console" element={<Console />} />
    </Routes>
  )
}
