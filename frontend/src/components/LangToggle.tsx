import { useTranslation } from 'react-i18next'

export default function LangToggle() {
  const { t, i18n } = useTranslation()
  const isEn = i18n.resolvedLanguage?.startsWith('en') ?? i18n.language.startsWith('en')
  const toggle = () => {
    const next = isEn ? 'zh' : 'en'
    void i18n.changeLanguage(next)
    try {
      localStorage.setItem('cygnus-lang', next)
    } catch {
      // Language changes remain available when storage is unavailable.
    }
  }

  return (
    <button
      type="button"
      className="lang-toggle bp-toggle-hit"
      aria-label={t(isEn ? 'lang.switchToZh' : 'lang.switchToEn')}
      aria-pressed={isEn}
      onClick={toggle}
    >
      {isEn ? 'EN' : '中'}
    </button>
  )
}
