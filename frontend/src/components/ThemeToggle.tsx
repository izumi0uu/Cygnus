import { useTheme } from '@/lib/theme'

export default function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme()
  return (
    <input
      type="checkbox"
      className="theme-switch"
      checked={resolvedTheme === 'dark'}
      onChange={(e) => setTheme(e.target.checked ? 'dark' : 'light')}
      aria-label="Toggle dark mode"
    />
  )
}
