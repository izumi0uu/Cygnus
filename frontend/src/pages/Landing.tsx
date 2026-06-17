import { useRef, useState } from 'react'
import { motion, AnimatePresence, useSpring, type Variants } from 'framer-motion'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

// --- skiper6 HoverMember, exact params (extracted from source chunk 106 / module 51613) ---
const ACCENT = '#A826FF'
const SPRING_POS = { mass: 0.1, damping: 16, stiffness: 71 }
const SPRING_SCALE = { mass: 0.1, damping: 10, stiffness: 150 }
const EASE: [number, number, number, number] = [0.19, 1, 0.22, 1]
// center-out per-character stagger: middle char first, edges last
const k = (i: number, len: number) => 0.055 * Math.abs(i - Math.floor(len / 2))
// hovered name: rolls up from below, exits up
const V_NAME: Variants = { hidden: { y: '100%' }, visible: { y: '0%' }, exit: { y: '-100%' } }
// default headline: rolls down from above
const V_DEFAULT: Variants = { hidden: { y: '-100%' }, visible: { y: '0%' }, exit: { y: '0%' } }
const BORDER = 'rgba(255,255,255,0.1)'

type Member = { zh: string; en: string; glyph: string }
const MEMBERS: Member[] = [
  { zh: '答案卡', en: 'Answer', glyph: '▤' },
  { zh: '排障流', en: 'Flow', glyph: '⑂' },
  { zh: '策略', en: 'Policy', glyph: '§' },
  { zh: '已知问题', en: 'Known', glyph: '◉' },
  { zh: '升级路径', en: 'Escalate', glyph: '↯' },
  { zh: '受众', en: 'Audience', glyph: '◈' },
]

function Roll({ text, variants, color }: { text: string; variants: Variants; color: string }) {
  const chars = Array.from(text)
  return (
    <motion.div
      className="absolute inset-0 flex items-center justify-center"
      initial="hidden"
      animate="visible"
      exit="hidden"
      transition={{ duration: 0.8, ease: EASE }}
    >
      <h1
        className="select-none whitespace-nowrap text-[20vw] uppercase leading-none"
        style={{ color, fontFamily: "'Thunder', system-ui, sans-serif", letterSpacing: '0.05em' }}
      >
        {chars.map((ch, i) => (
          <motion.span
            key={i}
            className="inline-block"
            variants={variants}
            transition={{ duration: 0.8, ease: EASE, delay: k(i, chars.length) }}
          >
            {ch === ' ' ? ' ' : ch}
          </motion.span>
        ))}
      </h1>
    </motion.div>
  )
}

function Tile({ member, index, onHover }: { member: Member; index: number; onHover: (i: number | null) => void }) {
  const [big, setBig] = useState(false)
  const size = big ? 84 : 60
  return (
    <motion.div
      className="relative cursor-pointer p-[5px]"
      style={{ width: size, height: size }}
      animate={{ width: size, height: size }}
      transition={{ duration: 0.2, ease: 'easeOut' }}
      onHoverStart={() => {
        setBig(true)
        onHover(index)
      }}
      onHoverEnd={() => {
        setBig(false)
        onHover(null)
      }}
    >
      <div
        className="flex h-full w-full items-center justify-center rounded-lg text-2xl transition-colors"
        style={{ background: '#1c1820', color: big ? ACCENT : '#cfcad0' }}
      >
        {member.glyph}
      </div>
    </motion.div>
  )
}

function ArrowBadge() {
  return (
    <svg width="18" height="18" viewBox="0 0 16 16" fill="none">
      <path d="M6.52182 2.75026L12.8858 9.11422L15.253 0.38299L6.52182 2.75026Z" fill="#fff" />
      <path d="M0.333095 12.3331L3.30294 15.3029L10.3402 6.56864L9.0674 5.29585L0.333095 12.3331Z" fill="#fff" />
    </svg>
  )
}

export default function Landing() {
  const { t, i18n } = useTranslation()
  const isZh = i18n.language.startsWith('zh')
  const [active, setActive] = useState<number | null>(null)

  const railRef = useRef<HTMLDivElement>(null)
  const mx = useSpring(0, SPRING_POS)
  const my = useSpring(0, SPRING_POS)
  const cscale = useSpring(0, SPRING_SCALE)

  const onRailMove = (e: React.PointerEvent) => {
    const el = railRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    mx.set(e.clientX - r.left)
    my.set(e.clientY - r.top)
  }

  const toggleLang = () => {
    const next = isZh ? 'en' : 'zh'
    i18n.changeLanguage(next)
    localStorage.setItem('cygnus-lang', next)
  }

  const members = MEMBERS.map((m) => ({ name: m.en, glyph: m.glyph }))

  const features = [
    { k: '01 / 编译', h: '把分散来源变成知识对象', p: '工单、release、SOP、incident —— 归一化、聚类，编译成结构化知识对象，而非匿名 chunk。' },
    { k: '02 / 审阅 · 发布', h: '人在环的治理命令', p: '按风险重排审阅；发布前预览爆炸半径（受众 × 渠道），支持限制 / 拆分 / 暂停。' },
    { k: '03 / 追溯', h: '每个答案都连着来源', p: '对象 → 证据 → 版本 → 发布记录，全链路可追溯；来源失效即治理失明。' },
  ]

  return (
    <div className="min-h-screen w-full overflow-x-hidden" style={{ background: '#121212', color: '#F2EEE6' }}>
      <nav className="fixed inset-x-0 top-0 z-30 flex items-center gap-6 px-8 py-6">
        <span className="text-lg font-extrabold tracking-wide">
          CYGNUS<span style={{ color: ACCENT }}>.</span>
        </span>
        <div className="ml-auto flex items-center gap-5 text-sm" style={{ color: '#8C867B' }}>
          <button onClick={toggleLang} className="transition-colors hover:text-[#F2EEE6]">
            {isZh ? '中 / EN' : 'EN / 中'}
          </button>
          <Link
            to="/console"
            className="rounded-full border px-4 py-1.5 transition-colors hover:border-[#A826FF]"
            style={{ borderColor: BORDER, color: '#F2EEE6' }}
          >
            {t('landing.enter')}
          </Link>
        </div>
      </nav>

      <section className="relative flex min-h-screen w-full flex-col items-center justify-center gap-12 overflow-hidden px-6">
        <p className="font-mono text-xs uppercase tracking-[0.3em]" style={{ color: '#8C867B' }}>
          {t('landing.eyebrow')}
        </p>

        {/* thumbnail rail (fixed height so growth doesn't reflow) + custom cursor */}
        <div
          ref={railRef}
          onPointerMove={onRailMove}
          onPointerEnter={() => cscale.set(1)}
          onPointerLeave={() => cscale.set(0)}
          className="relative flex h-[100px] cursor-none flex-wrap items-center justify-center gap-2"
        >
          {members.map((m, i) => (
            <Tile key={m.name} member={MEMBERS[i]} index={i} onHover={setActive} />
          ))}
          <motion.div
            aria-hidden
            style={{ x: mx, y: my, scale: cscale, transformOrigin: 'left top', background: ACCENT }}
            className="pointer-events-none absolute left-0 top-0 z-10 flex h-14 w-14 items-center justify-center rounded-full"
          >
            <ArrowBadge />
          </motion.div>
        </div>

        {/* rolling headline */}
        <div className="relative h-[22vw] w-full overflow-hidden">
          <AnimatePresence>
            {active === null && <Roll key="default" text="CYGNUS" variants={V_DEFAULT} color="#F2EEE6" />}
          </AnimatePresence>
          {members.map((m, i) => (
            <AnimatePresence key={m.name}>
              {active === i && <Roll key={m.name} text={m.name} variants={V_NAME} color={ACCENT} />}
            </AnimatePresence>
          ))}
        </div>

        <p className="max-w-xl text-center text-sm leading-relaxed" style={{ color: '#8C867B' }}>
          {t('landing.sub')}
        </p>

        <div className="flex flex-wrap items-center justify-center gap-3">
          <Link
            to="/console"
            className="rounded-full px-6 py-3 text-sm font-semibold text-white transition-colors"
            style={{ background: ACCENT }}
          >
            {t('landing.enter')} →
          </Link>
          <a
            href="#"
            className="rounded-full border px-6 py-3 text-sm transition-colors hover:border-white/40"
            style={{ borderColor: BORDER, color: '#F2EEE6' }}
          >
            {t('landing.docs')}
          </a>
        </div>
      </section>

      <section className="mx-auto grid max-w-[1100px] grid-cols-1 border-t md:grid-cols-3" style={{ borderColor: BORDER }}>
        {features.map((f, i) => (
          <div
            key={f.k}
            className="px-7 py-9"
            style={{ borderLeft: i > 0 ? `1px solid ${BORDER}` : undefined }}
          >
            <div className="font-mono text-xs tracking-wide" style={{ color: ACCENT }}>{f.k}</div>
            <h3 className="mt-3 text-xl font-bold">{f.h}</h3>
            <p className="mt-2 text-sm leading-relaxed" style={{ color: '#8C867B' }}>{f.p}</p>
          </div>
        ))}
      </section>

      <footer
        className="mx-auto flex max-w-[1100px] items-center justify-between border-t px-7 py-8 font-mono text-xs"
        style={{ borderColor: BORDER, color: '#8C867B' }}
      >
        <span>CYGNUS · Arkon-enhanced support knowledge OS</span>
        <span>© 2026</span>
      </footer>
    </div>
  )
}
