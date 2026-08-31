import type { Template } from './types'

export interface TemplateDiff {
  changedConnections: { id: string; before: string[]; after: string[] }[]
  summaryBefore: string
  summaryAfter: string
}

export function diffTemplates(before: Template, after: Template): TemplateDiff {
  const beforeById = new Map(before.stages.map((s) => [s.id, new Set(s.depends_on ?? [])]))
  const changedConnections = after.stages
    .filter((s) => {
      const beforeDeps = beforeById.get(s.id) ?? new Set<string>()
      const afterDeps = new Set(s.depends_on ?? [])
      return beforeDeps.size !== afterDeps.size || [...beforeDeps].some((d) => !afterDeps.has(d))
    })
    .map((s) => ({ id: s.id, before: [...(beforeById.get(s.id) ?? new Set<string>())], after: [...(s.depends_on ?? [])] }))

  return {
    changedConnections,
    summaryBefore: before.summary ?? '',
    summaryAfter: after.summary ?? '',
  }
}
