'use client'

/**
 * The one-time sign-in link from a client's invitation. It trades the token
 * for a session and opens the portal. A link that has been used or has
 * expired sends the client to sign in by emailed code instead.
 */
import * as React from 'react'
import Link from 'next/link'
import { Loader2 } from 'lucide-react'
import { setTokens } from '@/lib/auth'
import { withBasePath } from '@/lib/base-path'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function PortalEnterPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = React.use(params)
  const [failed, setFailed] = React.useState(false)
  const started = React.useRef(false)

  React.useEffect(() => {
    // The link works once: never send it twice (React runs effects twice in dev).
    if (started.current) return
    started.current = true
    fetch(`${API_URL}/auth/client-link`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    }).then(async (response) => {
      if (!response.ok) throw new Error('refused')
      const data = await response.json()
      setTokens(data.access_token, data.refresh_token)
      window.location.replace(withBasePath('/portal'))
    }).catch(() => setFailed(true))
  }, [token])

  return (
    <div className="min-h-dvh bg-bg-primary flex items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-xl border border-border bg-bg-secondary p-6 text-center shadow-xl">
        {failed ? (
          <>
            <h1 className="text-base font-semibold text-text-primary">This link has been used or has expired</h1>
            <p className="mt-2 text-sm text-text-secondary">
              For your security, the link in your invitation works once. Sign in with your email address and we will send you a code.
            </p>
            <Link href="/login?mode=code" className="mt-5 inline-flex items-center justify-center rounded-md bg-accent px-4 h-9 text-sm font-medium text-text-inverse hover:bg-accent-hover transition-colors">
              Sign in with your email
            </Link>
          </>
        ) : (
          <>
            <Loader2 className="mx-auto h-6 w-6 animate-spin text-text-tertiary" />
            <p className="mt-3 text-sm text-text-secondary">Opening your portal…</p>
          </>
        )}
      </div>
    </div>
  )
}
