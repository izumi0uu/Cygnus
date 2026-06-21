import { useTranslation } from 'react-i18next'

export default function LangToggle() {
  const { i18n } = useTranslation()
  const isEn = i18n.language.startsWith('en')
  const toggle = () => {
    const next = isEn ? 'zh' : 'en'
    i18n.changeLanguage(next)
    localStorage.setItem('cygnus-lang', next)
  }
  return (
    <div className="lang-toggle-wrapper">
      <input
        type="checkbox"
        id="lang-toggle"
        className="lang-tgl lang-tgl-skewed"
        checked={isEn}
        onChange={toggle}
      />
      <label
        htmlFor="lang-toggle"
        data-tg-on="EN"
        data-tg-off="中"
        className="lang-tgl-btn"
      />
    </div>
  )
}
