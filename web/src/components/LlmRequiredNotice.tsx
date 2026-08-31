import { GearSix, Plugs } from '@phosphor-icons/react'
import { t, useLang } from '../i18n'
import { Button } from './ui/Button'

export function isLlmMissingError(message: string): boolean {
  return /LLM\s*未配置|LLM\s*not configured|LLM\s*provider\s*not configured/i.test(message || '')
}

export function LlmRequiredNotice({ onConfigure }: { onConfigure?: () => void }) {
  useLang()
  return (
    <div className="llm-required-notice" role="alert">
      <span className="llm-required-icon" aria-hidden>
        <Plugs size={17} weight="duotone" />
      </span>
      <div className="llm-required-text">
        <strong>{t('llmn.title')}</strong>
        <p>{t('llmn.desc')}</p>
      </div>
      <Button
        size="sm"
        variant="secondary"
        icon={<GearSix size={15} weight="bold" />}
        onClick={onConfigure}
      >
        {t('llmn.configure')}
      </Button>
    </div>
  )
}
