import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SegmentedControl } from './SegmentedControl'

describe('SegmentedControl', () => {
  it('renders options and switches selection', async () => {
    const onChange = vi.fn()
    render(
      <SegmentedControl
        options={[
          { value: 'chat', label: '对话' },
          { value: 'run', label: '运行目标' },
        ]}
        value="chat"
        onChange={onChange}
        ariaLabel="输入模式"
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: '运行目标' }))
    expect(onChange).toHaveBeenCalledWith('run')
  })

  it('marks the active option as pressed', () => {
    render(
      <SegmentedControl
        options={[
          { value: 'a', label: 'A' },
          { value: 'b', label: 'B' },
        ]}
        value="a"
        onChange={() => {}}
      />,
    )
    expect(screen.getByRole('button', { name: 'A' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'B' })).toHaveAttribute('aria-pressed', 'false')
  })
})
