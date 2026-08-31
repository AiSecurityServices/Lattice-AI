import { useEffect, useState } from 'react'
import { onToast, type ToastPayload } from '../../lib/toast'

let seq = 0

/** Hosts transient toasts fired via lib/toast; mounted once in App. */
export function ToastHost() {
  const [items, setItems] = useState<Array<ToastPayload & { id: number }>>([])
  useEffect(() => {
    const timers: number[] = []
    const off = onToast((payload) => {
      const id = ++seq
      setItems((prev) => [...prev, { ...payload, id }])
      timers.push(window.setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), 4200))
    })
    return () => {
      off()
      timers.forEach((t) => window.clearTimeout(t))
    }
  }, [])
  if (items.length === 0) return null
  return (
    <div className="toast-host" role="status">
      {items.map((item) => (
        <div key={item.id} className={`toast toast-${item.kind}`}>
          {item.message}
        </div>
      ))}
    </div>
  )
}
