import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import './i18n'
import { ThemeProvider } from '@/lib/theme'
import App from './App.tsx'
import { RouteErrorBoundary } from '@/components/ErrorBoundary'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <BrowserRouter>
        <RouteErrorBoundary><App /></RouteErrorBoundary>
      </BrowserRouter>
    </ThemeProvider>
  </StrictMode>,
)
