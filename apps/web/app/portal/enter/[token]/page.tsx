'use client'

/**
 * The one-time sign-in link from a client's invitation. It trades the token
 * for a session and opens the portal. A link that has been used or has
 * expired sends the client to sign in by emailed code instead.
 */
import * as React from 'react'
import Link from 'next/link'
import { getAccessToken, setTokens } from '@/lib/auth'
import { withBasePath } from '@/lib/base-path'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

/** How long the welcome is on screen before the portal opens. */
const INTRO_MS = 2200

/**
 * The welcome a client sees on arriving from their invitation: the studio's
 * mark, then the service's name. Still, not animated, for anyone who has asked
 * their device for less motion.
 */
function AdborthIntro() {
  // The mark draws itself in the order it reads: the speech bubble, the play
  // button inside it, then the name.
  return (
    <div className="flex flex-col items-center text-white" aria-live="polite">
      <style>{`
        @keyframes adborth-pop { 0% { opacity: 0; transform: scale(.6) } 70% { opacity: 1; transform: scale(1.06) } 100% { opacity: 1; transform: scale(1) } }
        @keyframes adborth-play { 0% { opacity: 0; transform: translateX(-6px) scale(.7) } 100% { opacity: 1; transform: translateX(0) scale(1) } }
        @keyframes adborth-rise { 0% { opacity: 0; transform: translateY(12px) } 100% { opacity: 1; transform: translateY(0) } }
        @keyframes adborth-bar { 0% { transform: scaleX(0) } 100% { transform: scaleX(1) } }
        .adborth-bubble { transform-origin: 40% 80%; animation: adborth-pop .6s cubic-bezier(.2,.8,.2,1) both }
        .adborth-play { transform-box: fill-box; transform-origin: center; animation: adborth-play .35s ease-out .5s both }
        .adborth-name { animation: adborth-rise .45s ease-out .7s both }
        .adborth-line { animation: adborth-rise .45s ease-out .95s both }
        .adborth-bar { transform-origin: left; animation: adborth-bar 1.9s ease-in-out .2s both }
        @media (prefers-reduced-motion: reduce) { .adborth-bubble, .adborth-play, .adborth-name, .adborth-line, .adborth-bar { animation: none } }
      `}</style>
      <svg width="112" height="112" viewBox="16 10 76 76" role="img" aria-label="Adborth">
        <g transform="translate(2 -3)" fill="currentColor">
          <g className="adborth-bubble">
            <path fillRule="evenodd" d="M16 50a34 34 0 1 0 68 0a34 34 0 1 0-68 0ZM28 50a22 22 0 1 0 44 0a22 22 0 1 0-44 0Z" />
            <path d="M44.10 83.48 L21.06 87.04 Q25.5 79 22.15 69.50 Z" />
          </g>
          <path className="adborth-play" stroke="currentColor" strokeWidth="2.5" strokeLinejoin="round" d="M45.5 40.5 L45.5 59.5 L61 50 Z" />
        </g>
      </svg>
      <p className="adborth-name font-display mt-6 text-5xl uppercase leading-none">Adborth</p>
      <p className="adborth-line mt-3 text-sm text-white/75">Your videos, your feedback, in one place.</p>
      <div className="mt-8 h-1 w-44 overflow-hidden rounded-full bg-white/15">
        <div className="adborth-bar h-full w-full rounded-full bg-accent" />
      </div>
    </div>
  )
}

export default function PortalEnterPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = React.use(params)
  const [failed, setFailed] = React.useState(false)
  // A team member signed in to this browser: opening a client's link would
  // replace their session, so they are asked first.
  const [teamUser, setTeamUser] = React.useState<string | null>(null)
  const [checked, setChecked] = React.useState(false)
  const [confirmed, setConfirmed] = React.useState(false)
  const started = React.useRef(false)
  const startedAt = React.useRef(0)

  React.useEffect(() => {
    let cancelled = false
    const existing = getAccessToken()
    if (!existing) {
      setChecked(true)
      return
    }
    fetch(`${API_URL}/auth/me`, { headers: { Authorization: `Bearer ${existing}` } })
      .then((response) => (response.ok ? response.json() : null))
      .then((me) => {
        if (cancelled) return
        if (me && !me.is_client) setTeamUser(me.name || me.email || 'a team account')
        setChecked(true)
      })
      .catch(() => { if (!cancelled) setChecked(true) })
    return () => { cancelled = true }
  }, [])

  React.useEffect(() => {
    if (!checked || (teamUser && !confirmed)) return
    // The link works once: never send it twice (React runs effects twice in dev).
    if (started.current) return
    started.current = true
    startedAt.current = Date.now()
    fetch(`${API_URL}/auth/client-link`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    }).then(async (response) => {
      if (!response.ok) throw new Error('refused')
      const data = await response.json()
      setTokens(data.access_token, data.refresh_token)
      // Let the welcome play: the exchange itself takes a fraction of a second.
      const shown = Date.now() - startedAt.current
      window.setTimeout(() => window.location.replace(withBasePath('/portal')), Math.max(0, INTRO_MS - shown))
    }).catch(() => setFailed(true))
  }, [token, checked, teamUser, confirmed])

  const showIntro = !failed && !(teamUser && !confirmed)
  return (
    <div className={`min-h-dvh flex items-center justify-center px-4 ${showIntro ? 'bg-[#1b365d]' : 'bg-bg-primary'}`}>
      <div className={showIntro ? 'w-full max-w-sm text-center' : 'w-full max-w-sm rounded-3xl bg-bg-secondary p-7 text-center shadow-sm'}>
        {teamUser && !confirmed ? (
          <>
            <h1 className="text-base font-semibold text-text-primary">This is a client&apos;s sign-in link</h1>
            <p className="mt-2 text-sm text-text-secondary">
              You are signed in here as <strong>{teamUser}</strong>. Opening this link will sign this browser in as the client
              instead, and use up their one-time link. To see what a client sees without losing your session, open the link in a private window.
            </p>
            <div className="mt-5 flex items-center justify-center gap-2">
              <Link href="/projects" className="inline-flex items-center justify-center rounded-md bg-accent px-4 h-9 text-sm font-medium text-text-inverse hover:bg-accent-hover transition-colors">
                Stay signed in
              </Link>
              <button
                onClick={() => setConfirmed(true)}
                className="inline-flex items-center justify-center rounded-md border border-border px-4 h-9 text-sm font-medium text-text-secondary hover:text-text-primary hover:bg-bg-hover transition-colors"
              >
                Sign in as the client
              </button>
            </div>
          </>
        ) : failed ? (
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
          <AdborthIntro />
        )}
      </div>
    </div>
  )
}
