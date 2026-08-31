import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { GeneralSection } from './GeneralSection'

vi.mock('../../api', () => ({
  getPreferences: vi.fn().mockResolvedValue({ theme: 'system', language: 'zh' }),
  putPreferences: vi.fn().mockResolvedValue({ theme: 'system', language: 'en' }),
}))

describe('GeneralSection', () => {
  it('renders theme and language controls', async () => {
    render(<GeneralSection />)
    expect(await screen.findByLabelText('主题')).toBeInTheDocument()
    expect(screen.getByLabelText('语言')).toBeInTheDocument()
  })

  it('switches the whole UI language to English and persists it', async () => {
    render(<GeneralSection />)
    fireEvent.change(await screen.findByLabelText('语言'), { target: { value: 'en' } })
    await waitFor(() => expect(document.documentElement.lang).toBe('en'))
    expect(screen.getByText('Language')).toBeInTheDocument()
    expect(screen.getByText('General')).toBeInTheDocument()
    const api = await import('../../api')
    expect(api.putPreferences).toHaveBeenCalledWith({ language: 'en' })
  })
})
