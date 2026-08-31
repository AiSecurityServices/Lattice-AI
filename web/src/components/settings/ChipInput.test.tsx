import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ChipInput } from './ChipInput'

describe('ChipInput', () => {
  it('commits on Enter and skips invalid', () => {
    const onChange = vi.fn()
    render(<ChipInput value={[]} onChange={onChange} validate={(v) => v !== 'bad'} />)
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: 'good' } })
    fireEvent.click(input)
    fireEvent.change(input, { target: { value: 'good' } })
    fireEvent.focus(input)
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onChange).toHaveBeenCalledWith(['good'])
  })
  it('renders chips and removes on click', () => {
    const onChange = vi.fn()
    render(<ChipInput value={['a', 'b']} onChange={onChange} />)
    expect(screen.getByText('a')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('移除 a'))
    expect(onChange).toHaveBeenCalledWith(['b'])
  })
})
