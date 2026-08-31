import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Markdown } from './Markdown'

describe('Markdown', () => {
  it('renders gfm markdown', () => {
    render(<Markdown content={'# Title\n\n**bold**\n\n- item'} />)
    expect(screen.getByRole('heading', { level: 1, name: 'Title' })).toBeInTheDocument()
    expect(screen.getByText('bold')).toBeInTheDocument()
  })

  it('does not execute raw html/script', () => {
    const { container } = render(<Markdown content={'<script>window.pwned=true</script>\n\nhello'} />)
    expect(container.querySelector('script')).toBeNull()
    expect((window as unknown as { pwned?: boolean }).pwned).toBeUndefined()
  })
})
