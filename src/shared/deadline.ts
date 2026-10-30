import { dateKey } from './constants'

export type Tone = 'danger' | 'warn' | 'ok' | 'info' | 'neutral'

export function daysUntil(due: string, now = new Date()) {
  return Math.round((new Date(`${due}T12:00:00`).getTime() - new Date(`${dateKey(now)}T12:00:00`).getTime()) / 86400000)
}

export function deadlineTone(due: string, now = new Date()): Tone {
  const days = daysUntil(due, now)
  if (days <= 3) return 'danger'
  if (days <= 7) return 'warn'
  return 'neutral'
}
