import { Component, type ReactNode } from 'react'
import { Translation } from 'react-i18next'
import { Link, useLocation } from 'react-router-dom'
import { RotateCcw, ShieldAlert } from 'lucide-react'

type ErrorBoundaryProps = {
  children: ReactNode
  resetKey: string
}

type ErrorBoundaryState = {
  error: Error | null
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }
  private fallbackRef: HTMLElement | null = null

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch() {
    requestAnimationFrame(() => this.fallbackRef?.focus())
  }

  componentDidUpdate(previousProps: ErrorBoundaryProps) {
    if (this.state.error && previousProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null })
    }
  }

  private reset = () => {
    this.setState({ error: null })
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <Translation>
        {(t) => (
          <main className="bp-grid flex min-h-dvh items-center justify-center px-4 py-8">
            <section
              ref={(node) => { this.fallbackRef = node }}
              tabIndex={-1}
              role="alert"
              aria-labelledby="app-error-title"
              aria-describedby="app-error-description"
              className="bp-panel w-full max-w-xl p-5 sm:p-6"
            >
              <div className="flex items-center gap-2 text-urgent">
                <ShieldAlert size={18} aria-hidden="true" />
                <span className="bp-label" style={{ color: 'var(--urgent)', opacity: 1 }}>
                  {t('errorBoundary.eyebrow')}
                </span>
              </div>
              <h1 id="app-error-title" className="mt-3 font-mono text-xl font-bold tracking-tight">
                {t('errorBoundary.title')}
              </h1>
              <p id="app-error-description" className="mt-2 font-mono text-sm leading-relaxed text-muted-foreground">
                {t('errorBoundary.description')}
              </p>
              <p className="mt-3 border-l-2 border-border pl-3 font-mono text-xs leading-relaxed text-muted-foreground">
                {t('errorBoundary.truthNote')}
              </p>
              <div className="mt-5 flex flex-wrap gap-2">
                <button type="button" className="bp-cmd" onClick={this.reset}>
                  <RotateCcw size={14} aria-hidden="true" />
                  {t('errorBoundary.retry')}
                </button>
                <Link to="/console" className="bp-cmd" onClick={this.reset}>
                  {t('errorBoundary.returnHome')}
                </Link>
                <button type="button" className="bp-panel min-h-9 px-3 font-mono text-xs text-muted-foreground hover:bg-muted" onClick={() => window.location.reload()}>
                  {t('errorBoundary.reload')}
                </button>
              </div>
            </section>
          </main>
        )}
      </Translation>
    )
  }
}

export function RouteErrorBoundary({ children }: { children: ReactNode }) {
  const location = useLocation()
  const resetKey = `${location.pathname}${location.search}${location.hash}`
  return <ErrorBoundary resetKey={resetKey}>{children}</ErrorBoundary>
}
