import { useState } from 'react'

const KEY = 'replan-ai-consent'

function read() {
  try {
    return localStorage.getItem(KEY) === 'yes'
  } catch {
    return false
  }
}

export function useAiConsent(): [boolean, (value: boolean) => void] {
  const [consent, setConsent] = useState(read)
  function update(value: boolean) {
    setConsent(value)
    try {
      if (value) localStorage.setItem(KEY, 'yes')
      else localStorage.removeItem(KEY)
    } catch {
      return
    }
  }
  return [consent, update]
}
