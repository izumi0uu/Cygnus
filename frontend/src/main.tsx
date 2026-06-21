import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import './i18n'
import { ThemeProvider } from '@/lib/theme'
import { ZoomProvider } from '@/lib/zoom'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <BrowserRouter>
        <ZoomProvider>
          <App />
        </ZoomProvider>
      </BrowserRouter>
    </ThemeProvider>
  </StrictMode>,
)
