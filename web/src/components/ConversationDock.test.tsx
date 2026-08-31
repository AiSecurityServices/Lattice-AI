import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ConversationDock } from './ConversationDock'
import type { Session } from '../types'

const assistantSession: Session = {
  id: 'c1',
  name: '管理对话',
  kind: 'assistant',
  template_id: 'demo',
  model: 'gpt-5.1',
  reasoning_effort: 'off',
  project_id: 'default',
  created_at: '',
  updated_at: '',
  messages: [],
  target: '',
  autonomous: false,
  last_run_id: '',
}

const taskSession: Session = { ...assistantSession, id: 'c2', kind: 'task', name: '任务' }

describe('ConversationDock', () => {
  it('renders assistant chat input with model/effort selects', () => {
    render(<ConversationDock session={assistantSession} busy={false} models={['gpt-5.1', 'gpt-5.2']} efforts={['off', 'low', 'medium', 'high']} onSubmit={vi.fn()} onUpdate={vi.fn()} onCancel={vi.fn()} />)
    expect(screen.getByRole('textbox')).toBeInTheDocument()
    expect(screen.getByLabelText('模型')).toBeInTheDocument()
    expect(screen.getByLabelText('思考等级')).toBeInTheDocument()
  })

  it('renders task target input with autonomous toggle', () => {
    render(<ConversationDock session={taskSession} busy={false} models={[]} efforts={[]} onSubmit={vi.fn()} onUpdate={vi.fn()} onCancel={vi.fn()} />)
    expect(screen.getByLabelText('目标')).toBeInTheDocument()
    expect(screen.getAllByRole('checkbox')).toHaveLength(2)
  })

  it('shows autonomous and self-check toggles with help dots', () => {
    render(<ConversationDock session={taskSession} busy={false} models={[]} efforts={[]} onSubmit={vi.fn()} onUpdate={vi.fn()} onCancel={vi.fn()} />)
    expect(screen.getByRole('button', { name: '自主说明' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '自检说明' })).toBeInTheDocument()
  })

  it('keeps task target input local while typing', () => {
    render(<ConversationDock session={taskSession} busy={false} models={[]} efforts={[]} onSubmit={vi.fn()} onUpdate={vi.fn()} onCancel={vi.fn()} />)
    const input = screen.getByLabelText('目标')
    fireEvent.change(input, { target: { value: 'example.com' } })
    expect(input).toHaveValue('example.com')
  })

  it('shows pause control for a busy task and calls onStop', () => {
    const onStop = vi.fn()
    render(<ConversationDock session={taskSession} busy models={[]} efforts={[]} onSubmit={vi.fn()} onUpdate={vi.fn()} onCancel={vi.fn()} onStop={onStop} />)
    fireEvent.click(screen.getByRole('button', { name: /暂停/ }))
    expect(onStop).toHaveBeenCalled()
  })

  it('keeps cancel behavior for a busy assistant stream', () => {
    const onCancel = vi.fn()
    render(<ConversationDock session={assistantSession} busy models={[]} efforts={[]} onSubmit={vi.fn()} onUpdate={vi.fn()} onCancel={onCancel} onStop={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /取消/ }))
    expect(onCancel).toHaveBeenCalled()
  })
})
