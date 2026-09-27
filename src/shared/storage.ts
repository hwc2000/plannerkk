import { useEffect, useState } from 'react'

export function useStoredState<T>(storageKey: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    const saved = localStorage.getItem(storageKey)
    if (!saved) return initial

    try {
      return JSON.parse(saved) as T
    } catch {
      return initial
    }
  })

  useEffect(() => {
    localStorage.setItem(storageKey, JSON.stringify(value))
  }, [storageKey, value])

  return [value, setValue] as const
}
