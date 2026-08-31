import type { ReactNode } from 'react'

export function AppHeader({
  breadcrumb,
  title,
  context,
  actions,
}: {
  breadcrumb: string
  title: string
  context?: ReactNode
  actions?: ReactNode
}) {
  return (
    <header className="app-header">
      <div className="app-header-left">
        {breadcrumb && <span className="breadcrumb">{breadcrumb}{title ? ' /' : ''}</span>}
        {title && <h1 className="page-title app-header-title">{title}</h1>}
      </div>
      {context && <div className="app-header-context">{context}</div>}
      <div className="app-header-actions">{actions}</div>
    </header>
  )
}
