import { useTheme } from '@/lib/theme'
import { useTranslation } from 'react-i18next'

export default function ThemeToggle() {
  const { t } = useTranslation()
  const { resolvedTheme, setTheme } = useTheme()
  return (
    <input
      type="checkbox"
      className="theme-switch"
      checked={resolvedTheme === 'dark'}
      onChange={(e) => setTheme(e.target.checked ? 'dark' : 'light')}
      aria-label={t('toggle.darkMode')}
    />
  )
}
