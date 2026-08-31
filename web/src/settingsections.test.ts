import { describe, expect, it } from 'vitest'
import { SETTINGS_GROUPS, SETTINGS_SECTIONS } from './settingsections'

describe('settingsections', () => {
  it('has 4 groups', () => {
    expect(SETTINGS_GROUPS.map((g) => g.key)).toEqual(['model', 'scope', 'toolchain', 'general'])
  })
  it('covers all section ids exactly once', () => {
    const ids = SETTINGS_SECTIONS.map((s) => s.id)
    expect(ids).toEqual(['llm', 'scope', 'plan', 'toolchain', 'general'])
    expect(new Set(ids).size).toBe(ids.length)
  })
  it('every section belongs to a known group', () => {
    const keys = new Set(SETTINGS_GROUPS.map((g) => g.key))
    for (const s of SETTINGS_SECTIONS) expect(keys.has(s.group)).toBe(true)
  })
})
