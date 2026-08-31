export type ToastKind = 'error' | 'info'

export interface ToastPayload {
  message: string
  kind: ToastKind
}

const EVENT = 'lattice:toast'

/** Fire a transient toast from anywhere without threading state through the
 * tree — replaces the old blocking window.alert error popups. */
export function toast(message: string, kind: ToastKind = 'error') {
  window.dispatchEvent(new CustomEvent<ToastPayload>(EVENT, { detail: { message, kind } }))
}

export function onToast(handler: (payload: ToastPayload) => void) {
  const listener = (event: Event) => handler((event as CustomEvent<ToastPayload>).detail)
  window.addEventListener(EVENT, listener)
  return () => window.removeEventListener(EVENT, listener)
}
