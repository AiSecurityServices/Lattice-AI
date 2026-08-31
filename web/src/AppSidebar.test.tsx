import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AppSidebar, MODULES, SIDEBAR_DEFAULT, SIDEBAR_MAX, SIDEBAR_MIN } from './components/AppSidebar'

function renderSidebar(overrides: Record<string, unknown> = {}) {
  return render(
    <AppSidebar
      projects={[]}
      currentProjectId=""
      active="run"
      collapsed={false}
      onToggle={() => {}}
      onNavigate={() => {}}
      onSelectProject={() => {}}
      onCreateSession={vi.fn()}
      onProjectAction={() => {}}
      headerVisible
      dockVisible
      onToggleHeader={() => {}}
      onToggleDock={() => {}}
      {...overrides}
    />,
  )
}

describe('AppSidebar MODULES', () => {
  it('labels the run module as 任务 (no 渗透)', () => {
    const run = MODULES.find((m) => m.key === 'run')!
    expect(run.label).toBe('任务')
    expect(run.label).not.toMatch(/渗透/)
  })

  it('exposes sidebar sizing constants', () => {
    expect(SIDEBAR_DEFAULT).toBeGreaterThanOrEqual(SIDEBAR_MIN)
    expect(SIDEBAR_MAX).toBeGreaterThan(SIDEBAR_DEFAULT)
  })

  it('shows update dots on assets and findings when dirty', () => {
    renderSidebar({ assetsDirty: true, findingsDirty: true })
    expect(screen.getByTestId('nav-dot-assets')).toBeInTheDocument()
    expect(screen.getByTestId('nav-dot-findings')).toBeInTheDocument()
  })

  it('hides update dots when nothing is dirty', () => {
    renderSidebar()
    expect(screen.queryByTestId('nav-dot-assets')).toBeNull()
    expect(screen.queryByTestId('nav-dot-findings')).toBeNull()
  })
})
