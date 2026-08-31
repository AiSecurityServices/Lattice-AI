import type { ReactNode } from 'react'
import { Crosshair, GearSix, Plugs, ShieldWarning, Wrench } from '@phosphor-icons/react'
import { t } from './i18n'

export type SettingsSectionId = 'llm' | 'scope' | 'plan' | 'toolchain' | 'general'

export interface SettingsSection {
  id: SettingsSectionId
  label: string
  icon: ReactNode
  group: 'model' | 'scope' | 'toolchain' | 'general'
}

// Labels are lazy getters (reusing the nav.* keys) so they follow the current
// language instead of being fixed at module-load time.
export const SETTINGS_GROUPS: Array<{ key: string; label: string }> = [
  { key: 'model', get label() { return t('nav.group.model') } },
  { key: 'scope', get label() { return t('nav.group.scope') } },
  { key: 'toolchain', get label() { return t('nav.toolchain') } },
  { key: 'general', get label() { return t('nav.general') } },
]

export const SETTINGS_SECTIONS: SettingsSection[] = [
  { id: 'llm', get label() { return t('nav.llm') }, icon: <Plugs size={16} weight="duotone" />, group: 'model' },
  { id: 'scope', get label() { return t('nav.scope') }, icon: <Crosshair size={16} weight="duotone" />, group: 'scope' },
  { id: 'plan', get label() { return t('nav.plan') }, icon: <ShieldWarning size={16} weight="duotone" />, group: 'scope' },
  { id: 'toolchain', get label() { return t('nav.toolchain') }, icon: <Wrench size={16} weight="duotone" />, group: 'toolchain' },
  { id: 'general', get label() { return t('nav.general') }, icon: <GearSix size={16} weight="duotone" />, group: 'general' },
]
