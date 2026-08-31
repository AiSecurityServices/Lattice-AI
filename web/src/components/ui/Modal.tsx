import { useEffect, useRef, type ReactNode } from 'react'

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

/**
 * Shared modal shell: styled backdrop + dialog card, Escape closes, backdrop
 * mousedown dismisses, Tab is trapped inside and initial focus moves into the
 * card. Every centered dialog renders through this so keyboard behavior is
 * uniform (previously each dialog rolled its own, and several had none).
 */
export function Modal({
  open,
  onClose,
  ariaLabel,
  wide = false,
  children,
}: {
  open: boolean
  onClose: () => void
  ariaLabel: string
  wide?: boolean
  children: ReactNode
}) {
  const cardRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
        return
      }
      if (event.key !== 'Tab') return
      const card = cardRef.current
      if (!card) return
      const focusables = card.querySelectorAll<HTMLElement>(FOCUSABLE)
      if (focusables.length === 0) return
      const first = focusables[0]
      const last = focusables[focusables.length - 1]
      const active = document.activeElement
      if (event.shiftKey && (active === first || !card.contains(active))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (active === last || !card.contains(active))) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKeyDown, true)
    const timer = window.setTimeout(() => {
      const card = cardRef.current
      if (!card || card.contains(document.activeElement)) return
      card.querySelector<HTMLElement>(FOCUSABLE)?.focus()
    }, 0)
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKeyDown, true)
      window.clearTimeout(timer)
      document.body.style.overflow = ''
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="dialog-backdrop" onMouseDown={onClose}>
      <div
        ref={cardRef}
        className={wide ? 'dialog dialog-wide' : 'dialog'}
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        onMouseDown={(event) => event.stopPropagation()}
      >
        {children}
      </div>
    </div>
  )
}
