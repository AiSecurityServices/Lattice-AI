import { SettingsShell } from '../components/settings/SettingsShell'
import { t, useLang } from '../i18n'

export default function SettingsPage() {
  useLang()
  return (
    <div className="page">
      <div className="page-heading">
        <div className="page-heading-main">
          <h2 className="page-heading-title">{t('page.title')}</h2>
          <p className="page-heading-desc">{t('page.desc')}</p>
        </div>
      </div>
      <div className="page-body">
        <SettingsShell />
      </div>
    </div>
  )
}
