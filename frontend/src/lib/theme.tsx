import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type Theme = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

const ThemeContext = createContext<{
  theme: Theme
  resolvedTheme: ResolvedTheme
  setTheme: (t: Theme) => void
}>({
  theme: 'system',
  resolvedTheme: 'light',
  setTheme: () => {},
})

function resolveDark(theme: Theme, mqMatches: boolean): ResolvedTheme {
  return theme === 'dark' || (theme === 'system' && mqMatches) ? 'dark' : 'light'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem('cygnus-theme') as Theme) || 'system',
  )
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>(() =>
    resolveDark(
      (localStorage.getItem('cygnus-theme') as Theme) || 'system',
      typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches,
    ),
  )

  useEffect(() => {
    const root = document.documentElement
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      const resolved = resolveDark(theme, mq.matches)
      root.classList.toggle('dark', resolved === 'dark')
      setResolvedTheme(resolved)
    }
    apply()
    localStorage.setItem('cygnus-theme', theme)
    if (theme === 'system') {
      mq.addEventListener('change', apply)
      return () => mq.removeEventListener('change', apply)
    }
  }, [theme])

  return (
    <ThemeContext.Provider value={{ theme, resolvedTheme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export const useTheme = () => useContext(ThemeContext)
