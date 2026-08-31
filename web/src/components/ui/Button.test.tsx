import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Button } from './Button'

describe('Button', () => {
  it('renders label and handles click', async () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>保存</Button>)
    await userEvent.click(screen.getByRole('button', { name: '保存' }))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('applies danger variant class', () => {
    render(<Button variant="danger">删除</Button>)
    expect(screen.getByRole('button')).toHaveClass('btn-danger')
  })
})
