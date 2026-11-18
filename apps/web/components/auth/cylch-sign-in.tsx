'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { setTokens } from '@/lib/auth'
import { safeInternalPath } from '@/lib/safe-redirect'
import { Button } from '@/components/ui/button'

/**
 * Signing in with Cylch, the studio's own app and the one place its team is
 * kept. The team has no password here: they sign in to Cylch, and Cylch sends
 * them across with a one-time ticket. Clients are not in Cylch and sign in
 * here as before.
 *
 * Two parts: the button on the sign-in page, shown only when Cylch is
 * connected, and the landing step that swaps the ticket for a session.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

/** "Sign in with Cylch", or nothing where Cylch is not connected. */
export function CylchSignInButton() {
  const [signInUrl, setSignInUrl] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    fetch(`${API_URL}/auth/cylch`, { cache: 'no-store' })
      .then((answer) => (answer.ok ? answer.json() : null))
      .then((offer) => {
        if (live && offer && typeof offer.sign_in_url === 'string') setSignInUrl(offer.sign_in_url)
      })
      .catch(() => {})
    return () => {
      live = false
    }
  }, [])

  if (!signInUrl) return null

  function go() {
    if (!signInUrl) return
    // Cylch sends the person back to where they were heading.
    const from = safeInternalPath(new URLSearchParams(window.location.search).get('from'))
    // Cylch is another site, so this is a real navigation, not a route change.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign(`${signInUrl}?next=${encodeURIComponent(from)}`)
  }

  return (
    <div className="mb-6">
      <Button type="button" size="lg" className="w-full" onClick={go}>
        Sign in with Cylch
      </Button>
      <p className="mt-2 text-center text-xs text-text-tertiary">For the Stori Cymru team. Clients sign in below.</p>
      <div className="mt-5 flex items-center gap-3 text-xs text-text-tertiary" aria-hidden="true">
        <span className="h-px flex-1 bg-border" />
        or
        <span className="h-px flex-1 bg-border" />
      </div>
    </div>
  )
}

/** Where Cylch sends a browser: swap the ticket for a session and carry on. */
export function CylchSignInLanding() {
  const router = useRouter()
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    // The ticket rides in the fragment, which is not sent to any server. It is
    // taken out of the address at once so it is not left in the history.
    const ticket = new URLSearchParams(window.location.hash.replace(/^#/, '')).get('ticket')
    const next = safeInternalPath(new URLSearchParams(window.location.search).get('next'))
    window.history.replaceState(null, '', window.location.pathname)
    let live = true
    // No ticket at all is refused the same way as one the server turns down.
    const asked = ticket
      ? fetch(`${API_URL}/auth/cylch/exchange`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ticket }),
        })
      : Promise.reject(new Error('no ticket'))
    asked
      .then(async (answer) => {
        if (!answer.ok) throw new Error('refused')
        const tokens = await answer.json()
        setTokens(tokens.access_token, tokens.refresh_token)
        if (live) router.replace(next)
      })
      .catch(() => {
        if (live) setFailed(true)
      })
    return () => {
      live = false
    }
  }, [router])

  if (failed) {
    return (
      <div className="text-center">
        <h1 className="text-xl text-text-primary">That sign-in link has expired</h1>
        <p className="mt-2 text-sm text-text-secondary">
          It works once, for a minute. Open Adborth from Cylch again, or sign in another way.
        </p>
        <Button type="button" variant="secondary" className="mt-5" onClick={() => router.replace('/login')}>
          Go to sign-in
        </Button>
      </div>
    )
  }
  return (
    <div className="flex flex-col items-center gap-3 py-4" role="status">
      <div aria-hidden="true" className="h-8 w-8 animate-spin rounded-full border-4 border-bg-tertiary border-t-accent" />
      <p className="text-sm text-text-secondary">Signing you in from Cylch…</p>
    </div>
  )
}
