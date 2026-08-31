import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import WorkflowGraph, { deriveEdges, layoutNodes, statusOf, type WorkflowGraphHandle } from './WorkflowGraph'
import { createRef } from 'react'
import type { Template } from '../types'

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

const template = {
  id: 't',
  name: 'T',
  start: 'a',
  stages: [
    { id: 'a', name: 'A' },
    { id: 'b', name: 'B', depends_on: ['a'], condition: { op: 'truthy', key: 'go' } },
    { id: 'c', name: 'C', depends_on: ['b'], optional: true },
  ],
  tools: [],
} as Template

it('derives edges from depends_on and computes status', () => {
  const edges = deriveEdges(template)
  expect(edges).toEqual([
    { id: 'dep-a-b', source: 'a', target: 'b', condition: { op: 'truthy', key: 'go' } },
    { id: 'dep-b-c', source: 'b', target: 'c', condition: null },
  ])
  expect(statusOf({ stage_status: { a: 'completed', b: 'running' }, current_stage: 'b' } as never, 'b')).toBe('running')
  expect(statusOf(null, 'a')).toBe('idle')
  const positions = layoutNodes(template)
  expect(positions.a).toBeDefined()
  expect(positions.b).toBeDefined()
  expect(positions.c).toBeDefined()
})

it('renders stage nodes with runtime status badges', () => {
  vi.stubGlobal('ResizeObserver', ResizeObserverMock)
  render(
    <WorkflowGraph
      template={template}
      runtime={{ run_id: 'r', current_stage: 'b', stage_status: { a: 'completed', b: 'running', c: 'pending' } }}
    />,
  )
  expect(screen.getAllByText('A').length).toBeGreaterThan(0)
  expect(screen.getAllByText('B').length).toBeGreaterThan(0)
  expect(screen.getByText('running')).toBeTruthy()
  expect(screen.getByText('completed')).toBeTruthy()
  vi.unstubAllGlobals()
})

it('applies four-state status classes to stage nodes', () => {
  vi.stubGlobal('ResizeObserver', ResizeObserverMock)
  render(
    <WorkflowGraph
      template={template}
      runtime={{ run_id: 'r', current_stage: 'b', stage_status: { a: 'completed', b: 'running', c: 'failed' } }}
    />,
  )
  expect(document.querySelector('.stage-node.wf-st-completed')).toBeTruthy()
  expect(document.querySelector('.stage-node.wf-st-running')).toBeTruthy()
  expect(document.querySelector('.stage-node.wf-st-failed')).toBeTruthy()
  vi.unstubAllGlobals()
})

it('applies waiting and skipped state classes and leaves idle nodes unclassed', () => {
  vi.stubGlobal('ResizeObserver', ResizeObserverMock)
  render(
    <WorkflowGraph
      template={template}
      runtime={{ run_id: 'r', current_stage: 'b', stage_status: { b: 'skipped' } }}
    />,
  )
  expect(document.querySelector('.stage-node.wf-st-skipped')).toBeTruthy()
  expect(document.querySelector('.stage-node.wf-st-pending')).toBeNull()
  expect(document.querySelector('.stage-node.wf-st-running')).toBeNull()
  vi.unstubAllGlobals()
})

it('exposes focusStage via ref and highlights the requested stage', () => {
  vi.stubGlobal('ResizeObserver', ResizeObserverMock)
  const ref = createRef<WorkflowGraphHandle>()
  render(
    <WorkflowGraph
      ref={ref}
      template={template}
      runtime={{ run_id: 'r', current_stage: 'b', stage_status: { a: 'completed' } }}
      highlightStageId="a"
    />,
  )
  expect(typeof ref.current?.focusStage).toBe('function')
  expect(() => ref.current?.focusStage('a')).not.toThrow()
  expect(document.querySelector('.stage-node.wf-highlight')).toBeTruthy()
  vi.unstubAllGlobals()
})
