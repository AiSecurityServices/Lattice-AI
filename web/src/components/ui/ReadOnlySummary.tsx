import { t, useLang } from '../../i18n'

export function ReadOnlySummary({ title, value }: { title: string; value: unknown }) {
  useLang()
  const text = value == null ? t('ros.none') : typeof value === 'string' ? value : JSON.stringify(value, null, 2)

  return (
    <div className="readonly-summary">
      <div className="readonly-summary-title">{title}</div>
      <div className="readonly-summary-value">{text}</div>
    </div>
  )
}
