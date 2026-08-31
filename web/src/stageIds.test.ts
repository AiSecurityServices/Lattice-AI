import { describe, expect, it } from 'vitest'
import { nextStageId, nextTransitionId } from './stageIds'

describe('id generation', () => {
  it('creates unique stage ids', () => {
    const existing = [{ id: 'stage_1' }, { id: 'stage_2' }]
    const created = Array.from({ length: 50 }, () => nextStageId(existing))
    expect(new Set(created).size).toBe(50)
    expect(created.every((id) => id.startsWith('stage_'))).toBe(true)
  })

  it('creates unique transition ids', () => {
    const existing = [{ id: 't_1' }]
    const created = Array.from({ length: 50 }, () => nextTransitionId(existing))
    expect(new Set(created).size).toBe(50)
    expect(created.every((id) => id.startsWith('t_'))).toBe(true)
  })
})
