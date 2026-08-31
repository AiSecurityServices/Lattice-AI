import { useEffect, useState } from 'react'
import { Crosshair } from '@phosphor-icons/react'
import { getScope } from '../api'
import { t, useLang } from '../i18n'
import type { ScopePolicy } from '../types'

export function RunScopeBadge() {
  useLang()
  const [scope, setScope] = useState<ScopePolicy | null>(null)

  useEffect(() => {
    getScope()
      .then((value) =>
        setScope({
          allow_domains: value.allow_domains ?? [],
          allow_ips: value.allow_ips ?? [],
          allow_cidrs: value.allow_cidrs ?? [],
          allow_ports: value.allow_ports ?? [],
          allow_url_prefixes: value.allow_url_prefixes ?? [],
        }),
      )
      .catch(() => setScope(null))
  }, [])

  if (!scope) return null

  const parts = [
    scope.allow_domains.length ? t('rsb.part.domains').replace('{list}', scope.allow_domains.join(', ')) : '',
    scope.allow_ips.length ? t('rsb.part.ips').replace('{list}', scope.allow_ips.join(', ')) : '',
    scope.allow_cidrs.length ? t('rsb.part.cidrs').replace('{list}', scope.allow_cidrs.join(', ')) : '',
  ].filter(Boolean)
  const isConfigured = parts.length > 0

  return (
    <div className={`run-scope-badge${isConfigured ? '' : ' warn'}`}>
      <Crosshair size={13} weight="duotone" />
      <span>
        {isConfigured
          ? t('rsb.configured').replace('{scope}', parts.join(' · '))
          : t('rsb.unconfigured')}
      </span>
    </div>
  )
}
