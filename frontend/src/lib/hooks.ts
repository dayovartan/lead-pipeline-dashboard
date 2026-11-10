import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { Me } from '@/api/types'
import { load, save } from './storage'

export function useMe() {
  // remembered so the floor list knows the user's role when it opens offline
  return useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      const me = await api.me()
      save('leads.me', me)
      return me
    },
    placeholderData: () => load<Me | undefined>('leads.me', undefined),
    staleTime: 5 * 60_000,
    retry: 1,
  })
}

/** True only when /api/me says so; while loading, writes stay hidden. */
export function useCanEdit(): boolean {
  const { data } = useMe()
  return !!data?.is_editor
}

export function useConventions() {
  return useQuery({ queryKey: ['conventions'], queryFn: api.conventions, staleTime: 60_000 })
}

export function useMediaQuery(q: string): boolean {
  const [m, setM] = useState(() => (typeof window !== 'undefined' ? window.matchMedia(q).matches : false))
  useEffect(() => {
    const mq = window.matchMedia(q)
    const on = () => setM(mq.matches)
    on()
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [q])
  return m
}

export const useIsDesktop = () => useMediaQuery('(min-width: 768px)')

export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

export function useOnline(): boolean {
  const [on, setOn] = useState(() => navigator.onLine)
  useEffect(() => {
    const up = () => setOn(true)
    const down = () => setOn(false)
    window.addEventListener('online', up)
    window.addEventListener('offline', down)
    return () => {
      window.removeEventListener('online', up)
      window.removeEventListener('offline', down)
    }
  }, [])
  return on
}
