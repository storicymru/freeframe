'use client'

import { useEffect, useRef, useState } from 'react'

/**
 * "Adborth is updating": the notice people see instead of errors while the
 * site restarts to put a new version live.
 *
 * During a restart the front door answers 502, 503, 504 or nothing at all for
 * a minute or so. A page that is already open checks quietly every twenty
 * seconds while it is on screen, once it has seen the site working; one failed check is looked at again two
 * seconds later, so a single dropped request shows nothing. Once the notice is
 * up it checks every two seconds and reloads the page by itself as soon as
 * both the API and the site answer. After ninety seconds it says the
 * connection is the likelier cause, and keeps trying.
 *
 * Mounted once in the root layout, so team pages, the client portal and share
 * links all have it.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const WATCH_EVERY = 20_000
const LOOK_AGAIN_AFTER = 2_000
const RETRY_EVERY = 2_000
const SLOW_AFTER = 90_000

type Health = 'up' | 'down' | 'offline'

async function reach(url: string): Promise<Health> {
  try {
    const answer = await fetch(url, { cache: 'no-store' })
    return answer.status === 502 || answer.status === 503 || answer.status === 504 ? 'down' : 'up'
  } catch {
    // No answer at all: a restart, unless this device has simply lost its connection.
    return typeof navigator !== 'undefined' && navigator.onLine === false ? 'offline' : 'down'
  }
}

export function UpdatingScreen() {
  const [showing, setShowing] = useState(false)
  const [slow, setSlow] = useState(false)
  const showingRef = useRef(false)
  // The notice is only for a site this page has seen working. Where the check
  // itself can never succeed (a browser that blocks it, a misconfigured
  // address), saying "updating" for ever would be worse than saying nothing.
  const seenUp = useRef(false)

  // Watch quietly while the page is open and on screen.
  useEffect(() => {
    let lookAgain: ReturnType<typeof setTimeout> | undefined
    reach(`${API_URL}/health`).then((first) => {
      if (first === 'up') seenUp.current = true
    })
    const watch = setInterval(async () => {
      if (showingRef.current || document.hidden) return
      const now = await reach(`${API_URL}/health`)
      if (now === 'up') seenUp.current = true
      if (now !== 'down' || !seenUp.current) return
      lookAgain = setTimeout(async () => {
        if (showingRef.current) return
        if ((await reach(`${API_URL}/health`)) === 'down') {
          showingRef.current = true
          setShowing(true)
        }
      }, LOOK_AGAIN_AFTER)
    }, WATCH_EVERY)
    return () => {
      clearInterval(watch)
      if (lookAgain) clearTimeout(lookAgain)
    }
  }, [])

  // While the notice is up: keep trying, and carry on by reloading once it is all back.
  useEffect(() => {
    if (!showing) return
    const started = Date.now()
    const retry = setInterval(async () => {
      if (Date.now() - started > SLOW_AFTER) setSlow(true)
      if ((await reach(`${API_URL}/health`)) !== 'up') return
      if ((await reach(window.location.href)) !== 'up') return
      clearInterval(retry)
      window.location.reload()
    }, RETRY_EVERY)
    return () => clearInterval(retry)
  }, [showing])

  if (!showing) return null

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 p-6 backdrop-blur-sm"
    >
      <div className="w-full max-w-xs rounded-[28px] bg-bg-secondary px-8 py-7 text-center shadow-xl">
        <div
          aria-hidden="true"
          className="mx-auto mb-4 h-10 w-10 animate-spin rounded-full border-4 border-bg-tertiary border-t-accent"
        />
        <p className="text-lg font-semibold text-text-primary">
          {slow ? 'Can’t reach Adborth' : 'Adborth is updating'}
        </p>
        <p className="mt-1.5 text-sm leading-snug text-text-secondary">
          {slow
            ? 'Check your internet connection. Still trying; this page carries on by itself.'
            : 'Back in a moment. This page carries on by itself.'}
        </p>
      </div>
    </div>
  )
}
