import type { ToolBinding } from '../types'

export function newToolBindingId(): string {
  return crypto.randomUUID()
}

export function toolBindingKey(binding: ToolBinding): string {
  return binding.key ?? binding.tool
}
