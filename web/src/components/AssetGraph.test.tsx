import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { AssetGraph } from './AssetGraph'

test('renders empty state', () => {
  render(<AssetGraph graph={{ nodes: [], edges: [] }} />)
  expect(screen.getByText(/资产关系/)).toBeTruthy()
})

test('renders asset nodes', () => {
  render(
    <AssetGraph
      graph={{
        nodes: [
          { id: 'a1', kind: 'domain', value: 'example.com', natural_key: 'domain:example.com' },
          { id: 'a2', kind: 'ip', value: '203.0.113.10', natural_key: 'ip:203.0.113.10' },
        ],
        edges: [{ id: 'r1', from_asset: 'a1', to_asset: 'a2', relation: 'resolves_to' }],
      }}
    />,
  )
  expect(screen.getByLabelText('asset graph')).toBeTruthy()
  expect(screen.getByText('example.com')).toBeTruthy()
  expect(screen.getByText('203.0.113.10')).toBeTruthy()
})
