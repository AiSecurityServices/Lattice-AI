import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { isLlmMissingError, LlmRequiredNotice } from './LlmRequiredNotice'

describe('isLlmMissingError', () => {
  it('matches backend messages', () => {
    expect(isLlmMissingError('400: {"detail":"LLM 未配置；请在设置里填写 API Key"}')).toBe(true)
    expect(isLlmMissingError('400: {"detail":"LLM not configured; set API key"}')).toBe(true)
    expect(isLlmMissingError('timeout')).toBe(false)
  })
})

describe('LlmRequiredNotice', () => {
  it('renders copy and calls onConfigure', () => {
    const onConfigure = vi.fn()
    render(<LlmRequiredNotice onConfigure={onConfigure} />)
    expect(screen.getByText('需要先配置大模型')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '去配置 LLM' }))
    expect(onConfigure).toHaveBeenCalled()
  })
})
