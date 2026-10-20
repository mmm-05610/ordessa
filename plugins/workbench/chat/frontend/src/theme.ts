// Theme resolution for Chat v1: explicit host prop first, else the OS
// preference. Streamdown code themes key the markdown render (theme change →
// remount), so a flip never loses the body — US1 verification covers it.
import { useEffect, useState } from 'react'
import type { ChatTheme } from './components/messages/markdown-body'

export function usePreferredTheme(): ChatTheme {
  const [theme, setTheme] = useState<ChatTheme>(() =>
    typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    const query = window.matchMedia('(prefers-color-scheme: dark)')
    const listener = (event: MediaQueryListEvent) => setTheme(event.matches ? 'dark' : 'light')
    query.addEventListener('change', listener)
    return () => query.removeEventListener('change', listener)
  }, [])
  return theme
}

export type { ChatTheme }
