import { useTranslation } from 'react-i18next'

export default function LangToggle() {
  const { t, i18n } = useTranslation()
  const isEn = i18n.language.startsWith('en')
  const toggle = () => {
    const next = isEn ? 'zh' : 'en'
    i18n.changeLanguage(next)
    localStorage.setItem('cygnus-lang', next)
  }
  return (
    <label
      className="lang-toggle-wrapper bp-toggle-hit"
      role="switch"
      tabIndex={0}
      aria-checked={isEn}
      aria-label={t(isEn ? 'lang.switchToZh' : 'lang.switchToEn')}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          toggle()
        }
      }}
    >
      <input
        type="checkbox"
        id="lang-toggle"
        className="lang-tgl lang-tgl-skewed"
        checked={isEn}
        onChange={toggle}
        tabIndex={-1}
        aria-hidden="true"
      />
      <span
        data-tg-on="EN"
        data-tg-off="中"
        className="lang-tgl-btn"
        aria-hidden="true"
      />
    </label>
  )
}
