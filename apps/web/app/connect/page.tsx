'use client'

/**
 * Connecting the Adborth desktop app to an account.
 *
 * The app opens this page in the browser with the hash of a secret it keeps
 * (`challenge`) and a `state` it will check on the way back. The person, who
 * is usually signed in here already, agrees; the server gives a one-time code;
 * and this page hands the code to the app through its `adborth://` address.
 * The app then trades the code and its secret for a session of its own.
 */
import * as React from 'react'
import { api } from '@/lib/api'
import { getAccessToken } from '@/lib/auth'
import { withBasePath } from '@/lib/base-path'

interface Pending {
  challenge: string
  state: string
  name: string
}

const KEY = 'ff-connect-pending'
const SHAPE = /^[A-Za-z0-9_-]{16,128}$/

/** What the app asked for: from the address, or kept from before signing in. */
function readPending(): Pending | null {
  try {
    const params = new URLSearchParams(window.location.search)
    const challenge = params.get('challenge') ?? ''
    const state = params.get('state') ?? ''
    if (SHAPE.test(challenge) && SHAPE.test(state)) {
      const pending = { challenge, state, name: (params.get('name') ?? '').slice(0, 80) }
      sessionStorage.setItem(KEY, JSON.stringify(pending))
      // Keep the values out of the address bar and the history.
      window.history.replaceState(null, '', withBasePath('/connect'))
      return pending
    }
    const kept = sessionStorage.getItem(KEY)
    if (!kept) return null
    const pending = JSON.parse(kept) as Pending
    return SHAPE.test(pending.challenge) && SHAPE.test(pending.state) ? pending : null
  } catch {
    return null
  }
}

function Mark() {
  return (
    <svg width="72" height="72" viewBox="16 10 76 76" role="img" aria-label="Adborth" className="mx-auto text-white">
      <g transform="translate(2 -3)" fill="currentColor">
        <path fillRule="evenodd" d="M16 50a34 34 0 1 0 68 0a34 34 0 1 0-68 0ZM28 50a22 22 0 1 0 44 0a22 22 0 1 0-44 0Z" />
        <path d="M44.10 83.48 L21.06 87.04 Q25.5 79 22.15 69.50 Z" />
        <path stroke="currentColor" strokeWidth="2.5" strokeLinejoin="round" d="M45.5 40.5 L45.5 59.5 L61 50 Z" />
      </g>
    </svg>
  )
}

type Step = 'loading' | 'signed-out' | 'nothing' | 'ask' | 'working' | 'done' | 'client' | 'error'

export default function ConnectPage() {
  const [step, setStep] = React.useState<Step>('loading')
  const [pending, setPending] = React.useState<Pending | null>(null)
  const [who, setWho] = React.useState<{ name: string; email: string } | null>(null)
  const [appLink, setAppLink] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    // Everything is decided inside one promise chain, so the state is set from
    // a callback and never in the body of the effect.
    Promise.resolve(readPending())
      .then(async (asked): Promise<[Pending | null, Step, { name: string; email: string } | null]> => {
        if (!asked) return [null, 'nothing', null]
        if (!getAccessToken()) return [asked, 'signed-out', null]
        try {
          const me = await api.get<{ name: string; email: string; is_client?: boolean }>('/auth/me')
          return [asked, me.is_client ? 'client' : 'ask', { name: me.name, email: me.email }]
        } catch {
          return [asked, 'signed-out', null]
        }
      })
      .then(([asked, next, me]) => {
        if (cancelled) return
        setPending(asked)
        setWho(me)
        setStep(next)
      })
    return () => { cancelled = true }
  }, [])

  const connect = async () => {
    if (!pending) return
    setStep('working')
    try {
      const { code } = await api.post<{ code: string }>('/auth/device/approve', {
        code_challenge: pending.challenge,
        device_name: pending.name || null,
      })
      try { sessionStorage.removeItem(KEY) } catch { /* nothing to clear */ }
      const link = `adborth://connect?code=${encodeURIComponent(code)}&state=${encodeURIComponent(pending.state)}`
      setAppLink(link)
      setStep('done')
      window.location.href = link
    } catch {
      setStep('error')
    }
  }

  const cancel = () => {
    try { sessionStorage.removeItem(KEY) } catch { /* nothing to clear */ }
    window.location.href = withBasePath('/projects')
  }

  const pill = 'inline-flex h-11 items-center justify-center rounded-full px-6 text-sm font-semibold transition-colors'

  return (
    <div className="surface-navy min-h-dvh bg-bg-primary flex items-center justify-center px-4">
      <div className="w-full max-w-sm text-center">
        <Mark />
        <h1 className="mt-5 text-4xl uppercase leading-none">Adborth</h1>

        {step === 'loading' && <p className="mt-6 text-sm text-text-secondary">One moment…</p>}

        {step === 'nothing' && (
          <p className="mt-6 text-sm text-text-secondary">
            Start from the Adborth app on your Mac: choose <strong className="text-text-primary">Sign in with your browser</strong> there.
          </p>
        )}

        {step === 'signed-out' && (
          <>
            <p className="mt-6 text-sm text-text-secondary">Sign in to connect the Adborth app on your Mac.</p>
            <a href={withBasePath('/login?from=/connect')} className={`${pill} mt-6 bg-accent text-white hover:bg-accent-hover`}>
              Sign in
            </a>
          </>
        )}

        {step === 'client' && (
          <p className="mt-6 text-sm text-text-secondary">
            The desktop app is for the Stori Cymru team. Your videos are in your portal.
          </p>
        )}

        {(step === 'ask' || step === 'working') && (
          <>
            <p className="mt-6 text-base">Connect the Adborth app{pending?.name ? ` on ${pending.name}` : ''}?</p>
            <p className="mt-2 text-sm text-text-secondary">
              It will be able to upload to your projects as {who?.name}
              {who?.email ? ` (${who.email})` : ''}, and stays signed in while you keep using it.
            </p>
            <div className="mt-7 flex items-center justify-center gap-3">
              <button type="button" onClick={cancel} disabled={step === 'working'} className={`${pill} bg-white/10 text-white hover:bg-white/20 disabled:opacity-50`}>
                Cancel
              </button>
              <button type="button" onClick={connect} disabled={step === 'working'} className={`${pill} bg-accent text-white hover:bg-accent-hover disabled:opacity-60`}>
                {step === 'working' ? 'Connecting…' : 'Connect'}
              </button>
            </div>
          </>
        )}

        {step === 'done' && (
          <>
            <p className="mt-6 text-base">Connected.</p>
            <p className="mt-2 text-sm text-text-secondary">Go back to the Adborth app. You can close this tab.</p>
            {appLink && (
              <a href={appLink} className="mt-5 inline-block text-sm text-white underline underline-offset-4">
                The app did not open? Open it
              </a>
            )}
          </>
        )}

        {step === 'error' && (
          <>
            <p role="alert" className="mt-6 text-sm text-text-secondary">That did not work. Start again from the Adborth app.</p>
            <button type="button" onClick={() => setStep('ask')} className={`${pill} mt-5 bg-white/10 text-white hover:bg-white/20`}>
              Try again
            </button>
          </>
        )}
      </div>
    </div>
  )
}
