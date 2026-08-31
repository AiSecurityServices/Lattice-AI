import { Component, type ReactNode } from 'react'
import { t } from '../i18n'
import { Button } from './ui/Button'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/** Keeps a render crash contained to the page area instead of blanking the
 * whole app; the sidebar and navigation stay usable. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error) {
    console.error('[lattice] render error:', error)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="page" style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: 24 }}>
          <h3>{t('error.title')}</h3>
          <p className="muted">{String(this.state.error?.message || this.state.error)}</p>
          <div>
            <Button size="sm" onClick={() => this.setState({ error: null })}>
              {t('error.retry')}
            </Button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
