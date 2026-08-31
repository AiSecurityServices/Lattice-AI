import { t } from '../i18n'
import type { LogLine } from '../types'

/** Event-type vocabulary shared by the logs page and the run timeline.
 * Built per call so the labels follow the current language. */
function typeLabels(): Record<string, string> {
  return {
    run_started: t('logs.type.run_started'),
    stage_started: t('logs.type.stage_started'),
    stage_finished: t('logs.type.stage_finished'),
    agent_message: t('logs.type.agent_message'),
    tool_call: t('drawer.trace.toolCalls'),
    tool_result: t('logs.type.tool_result'),
    tool_tier: t('run.tier.title'),
    error: t('drawer.trace.error'),
  }
}

export function logTypeLabel(type?: string): string {
  const labels = typeLabels()
  return (type && labels[type]) || type || t('logs.type.event')
}

/** One-line human summary so event rows scan without opening the raw JSON. */
export function describeLog(log: LogLine): string {
  const data = log.data ?? {}
  const tool = typeof data.tool === 'string' ? data.tool : ''
  const stage = typeof data.stage === 'string' ? data.stage : ''
  const message = typeof data.message === 'string' ? data.message : ''
  switch (log.type) {
    case 'tool_call':
      return tool || message || t('logs.fallback.callTool')
    case 'tool_result':
      return tool || message || t('logs.fallback.toolResult')
    case 'tool_tier':
      return tool ? `${tool} ${message}`.trim() : message || t('logs.fallback.tier')
    case 'stage_started':
      return stage ? t('logs.stage.started').replace('{name}', stage) : message || t('logs.type.stage_started')
    case 'stage_finished':
      return stage ? t('logs.stage.finished').replace('{name}', stage) : message || t('logs.type.stage_finished')
    case 'run_started':
      return message || t('logs.type.run_started')
    default:
      return message.slice(0, 140)
  }
}
