import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { LlmSection } from './LlmSection'

vi.mock('../../api', () => ({
  getSettings: vi.fn().mockResolvedValue({ provider: 'openai', base_url: 'https://api.openai.com/v1', model: 'gpt-5.1', api_key: '', reasoning_effort: 'high', has_api_key: false }),
  listProviders: vi.fn().mockResolvedValue({ providers: { openai: { name: 'OpenAI', base_url: 'https://api.openai.com/v1', model: 'gpt-5.1', reasoning: { efforts: ['off', 'low', 'medium', 'high'] } } } }),
  listModels: vi.fn().mockResolvedValue({ provider: 'openai', models: ['gpt-5.1', 'gpt-6'], efforts: ['off', 'low', 'medium', 'high'] }),
  putSettings: vi.fn().mockResolvedValue({ provider: 'openai', base_url: 'https://api.openai.com/v1', model: 'gpt-5.1', api_key: '', reasoning_effort: 'high', has_api_key: false }),
  testProvider: vi.fn().mockResolvedValue({ ok: true }),
}))

describe('LlmSection', () => {
  it('renders dynamic preset providers plus a fixed custom option', async () => {
    render(<LlmSection />)
    expect(await screen.findByText('OpenAI')).toBeInTheDocument()
    expect(screen.getByText('其他（自定义）')).toBeInTheDocument()
  })

  it('fetches the live model list and renders reasoning effort options', async () => {
    const api = await import('../../api')
    render(<LlmSection />)
    expect(await screen.findByLabelText('推理档位')).toBeInTheDocument()
    expect(api.listModels).toHaveBeenCalledWith({ base_url: 'https://api.openai.com/v1', api_key: '' })
    expect(screen.getByLabelText('模型')).toHaveValue('gpt-5.1')
  })

  it('supports the custom provider flow with manual model entry and model fetch', async () => {
    const api = await import('../../api')
    render(<LlmSection />)
    fireEvent.click(await screen.findByRole('radio', { name: /其他（自定义）/ }))
    expect(screen.getAllByText('手动填写 Base URL、模型与 API Key（OpenAI 兼容接口）').length).toBeGreaterThan(0)

    const modelInput = screen.getByLabelText('模型')
    fireEvent.change(modelInput, { target: { value: 'my-custom-model' } })
    expect(modelInput).toHaveValue('my-custom-model')

    fireEvent.click(screen.getByRole('button', { name: '获取模型列表' }))
    expect(api.listModels).toHaveBeenCalledWith({ base_url: 'https://api.openai.com/v1', api_key: '' })
  })
})
