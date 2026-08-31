import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ReadOnlySummary } from './ReadOnlySummary'

describe('ReadOnlySummary', () => {
  it('renders title and JSON value', () => {
    render(<ReadOnlySummary title="默认参数" value={{ port: 80 }} />)
    expect(screen.getByText('默认参数')).toBeInTheDocument()
    expect(screen.getByText(/port/)).toBeInTheDocument()
  })
})
