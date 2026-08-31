import { render, screen, waitFor } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import ToolsPage from './ToolsPage'

vi.mock('../api', () => ({
  listTools: vi.fn(),
  listGroups: vi.fn(),
  deleteRecipe: vi.fn(),
  updateTool: vi.fn(),
  runTool: vi.fn(),
  setGroupMembers: vi.fn(),
}))

test('renders availability label for tools', async () => {
  const api = await import('../api')
  vi.mocked(api.listTools as any).mockResolvedValue({
    tools: [
      { name: 'dnsx', description: 'res', runner: 'builtin', available: true, status: 'builtin' },
      { name: 'nuclei', description: 'scanner', runner: 'cli', available: false, status: 'unavailable' },
    ],
  })
  vi.mocked(api.listGroups as any).mockResolvedValue({ tool_groups: [], skill_groups: [] })

  render(<ToolsPage activeTemplate={null} refreshKey={0} />)
  await waitFor(() => expect(screen.getByText('dnsx')).toBeTruthy())
  expect(screen.getByText('已安装')).toBeTruthy()
  expect(screen.getByText('未安装')).toBeTruthy()
})
