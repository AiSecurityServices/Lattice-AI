import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { NameDialog } from './NameDialog'

describe('NameDialog', () => {
  it('submits the entered name', async () => {
    const onConfirm = vi.fn()
    render(<NameDialog open title="重命名" initialValue="旧名称" confirmLabel="保存" onConfirm={onConfirm} onCancel={vi.fn()} />)
    const input = screen.getByRole('textbox', { name: '名称' })
    await userEvent.clear(input)
    await userEvent.type(input, '新名称')
    await userEvent.click(screen.getByRole('button', { name: '保存' }))
    expect(onConfirm).toHaveBeenCalledWith('新名称')
  })
})
