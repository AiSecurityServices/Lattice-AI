function uniqueId(prefix: string, existing: Array<{ id: string }>): string {
  let id = `${prefix}${crypto.randomUUID()}`
  while (existing.some((item) => item.id === id)) {
    id = `${prefix}${crypto.randomUUID()}`
  }
  return id
}

export function nextStageId(stages: { id: string }[]): string {
  return uniqueId('stage_', stages)
}

export function nextTransitionId(transitions: { id: string }[]): string {
  return uniqueId('t_', transitions)
}
