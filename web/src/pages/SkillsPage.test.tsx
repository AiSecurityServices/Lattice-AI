import { render, screen } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import SkillsPage from './SkillsPage'
import * as api from '../api'
import type { GroupsPayload } from '../api'
import type { Skill } from '../types'

vi.mock('../api', () => ({
  createSkill: vi.fn(),
  deleteSkill: vi.fn(),
  listGroups: vi.fn(),
  listSkills: vi.fn(),
  setGroupMembers: vi.fn(),
  updateSkill: vi.fn(),
}))

const mockedApi = vi.mocked(api)

const groups: GroupsPayload = { tool_groups: [], skill_groups: [] }

beforeEach(() => {
  vi.clearAllMocks()
  mockedApi.listGroups.mockResolvedValue(groups)
})

test('shows the source badge even when the skill has no tags (rework ③)', async () => {
  const noTags: Skill = { name: 'bare-nuclei', description: 'd', source: 'nuclei', tags: [] }
  mockedApi.listSkills.mockResolvedValue({ skills: [noTags] })
  render(<SkillsPage activeTemplate={null} refreshKey={0} />)
  expect(await screen.findByText('nuclei')).toBeTruthy()
})

test('shows the classification line (CVE/CWE/CVSS) for imported skills', async () => {
  const classified: Skill = {
    name: 'with-cve',
    description: 'd',
    tags: ['cve'],
    source: 'nuclei',
    classification: { cve: 'CVE-2024-1', cwe: 'CWE-79', cvss: '9.8' },
  }
  mockedApi.listSkills.mockResolvedValue({ skills: [classified] })
  render(<SkillsPage activeTemplate={null} refreshKey={0} />)
  expect(await screen.findByText('nuclei')).toBeTruthy()
  expect(await screen.findByText('CVE-2024-1 · CWE-79 · CVSS 9.8')).toBeTruthy()
})
