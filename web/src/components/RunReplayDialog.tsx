import { useEffect, useState } from 'react'
import { replayRun } from '../api'
import { t, useLang } from '../i18n'
import { Button } from './ui/Button'
import type { ReplayPage, SessionEvent } from '../types'

export function RunReplayDialog({ runId, onClose }: { runId: string; onClose: () => void }) {
  useLang()
  const [events, setEvents] = useState<SessionEvent[]>([])
  const [after, setAfter] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    replayRun(runId, 0)
      .then((page: ReplayPage) => {
        if (cancelled) return
        setEvents(page.events)
        setAfter(page.next_after)
        setHasMore(page.has_more)
        setLoading(false)
      })
      .catch(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [runId])

  function loadMore() {
    replayRun(runId, after).then((page: ReplayPage) => {
      setEvents((prev) => [...prev, ...page.events])
      setAfter(page.next_after)
      setHasMore(page.has_more)
    })
  }

  return (
    <div className="dialog-backdrop" onMouseDown={onClose}>
      <div
        className="dialog dialog-wide"
        role="dialog"
        aria-modal="true"
        aria-label={t('rreplay.title')}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <h3>{t('rreplay.title')}</h3>
        <div className="dialog-scroll">
          {loading ? (
            <p className="muted">{t('common.loading')}</p>
          ) : events.length === 0 ? (
            <p className="muted">{t('rreplay.empty')}</p>
          ) : (
            events.map((event) => (
              <details key={`${runId}-${event.seq}`} className="output-log">
                <summary>
                  <span className="output-log-type">{event.type}</span>
                  <span className="muted output-log-time">#{event.seq}</span>
                </summary>
                <pre className="output-log-data">{JSON.stringify(event.data, null, 2)}</pre>
              </details>
            ))
          )}
        </div>
        <div className="dialog-actions">
          {hasMore && (
            <Button size="sm" variant="secondary" onClick={loadMore}>
              {t('rreplay.loadMore')}
            </Button>
          )}
          <Button size="sm" onClick={onClose}>
            {t('common.close')}
          </Button>
        </div>
      </div>
    </div>
  )
}
