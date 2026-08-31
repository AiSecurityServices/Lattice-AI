import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import ImportPreviewDialog from './ImportPreviewDialog'

vi.mock('../api', () => ({
  previewAssetImport: vi.fn().mockResolvedValue({ source: 'x', fingerprint: 'abc', assets: [{ type: 'skill', name: 'recon', description: 'desc' }], suggested_bindings: [], warnings: [] }),
  applyAssetImport: vi.fn().mockResolvedValue({ skills: ['recon'], tools: [], bindings: [] }),
}))

test('renders skill import preview', async () => {
  render(<ImportPreviewDialog source="x" template={null} onClose={() => {}} onImported={() => {}} />)
  expect(await screen.findByText('recon')).toBeTruthy()
})
