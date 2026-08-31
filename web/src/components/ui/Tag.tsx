import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

type Tone = 'neutral' | 'primary' | 'success' | 'warning' | 'danger'

export function Tag({ children, tone = 'neutral' }: { children: ReactNode; tone?: Tone }) {
  return <span className={cn('tag', tone !== 'neutral' && tone)}>{children}</span>
}
