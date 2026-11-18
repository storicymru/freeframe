'use client'

/**
 * Client sign-off on a share link.
 *
 * A link can ask the client to sign the video off. Until they do, the page
 * shows a "Sign off" button and no download; once they have, it shows who
 * signed and the download opens. The server decides all of it: this only asks
 * `GET /share/{token}/sign-off/{asset}` what the state is and posts the form.
 */
import * as React from 'react'
import { CheckCircle2, Loader2, PenLine } from 'lucide-react'
import { shareAuthHeaders } from './share-download'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export interface ShareSignOffStatus {
  /** Whether this link asks for a sign-off at all. */
  required: boolean
  signed_off: boolean
  signer_name?: string | null
  signed_at?: string | null
  version_number?: number | null
  /** The words the signer agrees to, exactly as they will be recorded. */
  statement?: string | null
}

function query(shareSession?: string | null, versionId?: string | null): string {
  const params = new URLSearchParams()
  if (shareSession) params.set('share_session', shareSession)
  if (versionId) params.set('version_id', versionId)
  const text = params.toString()
  return text ? `?${text}` : ''
}

export async function fetchShareSignOff(
  token: string, assetId: string, shareSession?: string | null, versionId?: string | null,
): Promise<ShareSignOffStatus | null> {
  try {
    const response = await fetch(`${API_URL}/share/${token}/sign-off/${assetId}${query(shareSession, versionId)}`, { headers: shareAuthHeaders() })
    if (!response.ok) return null
    return (await response.json()) as ShareSignOffStatus
  } catch {
    return null
  }
}

/** Posts the sign-off. Throws an Error whose message is fit to show the signer. */
export async function submitShareSignOff(
  token: string, assetId: string,
  body: { name: string; email: string; agree: boolean; version_id?: string },
  shareSession?: string | null,
): Promise<ShareSignOffStatus> {
  let response: Response
  try {
    response = await fetch(`${API_URL}/share/${token}/sign-off/${assetId}${query(shareSession)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...shareAuthHeaders() },
      body: JSON.stringify(body),
    })
  } catch {
    throw new Error('Could not reach the server. Check your connection and try again.')
  }
  if (response.ok) return (await response.json()) as ShareSignOffStatus
  let detail: unknown
  try {
    detail = (await response.json())?.detail
  } catch {
    detail = undefined
  }
  if (response.status === 422) throw new Error('Enter your full name and a valid email address.')
  if (response.status === 429) throw new Error('Too many attempts. Please wait a few minutes and try again.')
  throw new Error(typeof detail === 'string' ? detail : 'The sign-off could not be saved. Please try again.')
}

/**
 * The sign-off state for the asset on screen. `status` is null until the first
 * answer arrives, and stays null if the server could not be asked, which reads
 * the same as a link that does not ask for a sign-off.
 */
export function useShareSignOff(
  token: string, assetId: string | undefined, shareSession?: string | null, versionId?: string | null,
) {
  const [status, setStatus] = React.useState<ShareSignOffStatus | null>(null)

  const refresh = React.useCallback(async () => {
    if (!assetId) return
    const next = await fetchShareSignOff(token, assetId, shareSession, versionId)
    if (next) setStatus(next)
  }, [token, assetId, shareSession, versionId])

  React.useEffect(() => {
    let cancelled = false
    if (!assetId) return
    fetchShareSignOff(token, assetId, shareSession, versionId).then((next) => {
      if (!cancelled && next) setStatus(next)
    })
    return () => { cancelled = true }
  }, [token, assetId, shareSession, versionId])

  return { status, setStatus, refresh }
}

function formatSignedAt(iso?: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' })
}

/** Top-bar control: the button that opens the form, or who signed once it is done. */
export function SignOffControl({ status, onOpen }: { status: ShareSignOffStatus | null; onOpen: () => void }) {
  if (!status?.required && !status?.signed_off) return null
  if (status.signed_off) {
    const when = formatSignedAt(status.signed_at)
    return (
      <span
        className="flex items-center gap-1.5 h-7 px-2 sm:px-3 rounded-md text-xs font-medium text-status-success bg-status-success/10 min-w-0"
        title={`Signed off by ${status.signer_name ?? 'the client'}${when ? ` on ${when}` : ''}`}
      >
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
        <span className="hidden sm:inline truncate">Signed off{status.signer_name ? ` by ${status.signer_name}` : ''}</span>
      </span>
    )
  }
  return (
    <button
      onClick={onOpen}
      className="flex items-center gap-1.5 h-7 px-2 sm:px-3 rounded-md text-xs font-medium text-text-inverse bg-accent hover:bg-accent-hover transition-colors"
    >
      <PenLine className="h-3 w-3" /> Sign off
    </button>
  )
}

/** Shown in place of the comment box once the asset is signed off. */
export function SignedOffNotice({ status }: { status: ShareSignOffStatus }) {
  const when = formatSignedAt(status.signed_at)
  return (
    <div className="shrink-0 border-t border-border px-4 py-3 text-xs text-text-secondary">
      <p className="flex items-center gap-1.5 font-medium text-text-primary">
        <CheckCircle2 className="h-3.5 w-3.5 text-status-success" /> Signed off
      </p>
      <p className="mt-1">
        {status.signer_name ? `${status.signer_name} approved` : 'The client approved'}
        {status.version_number ? ` version ${status.version_number}` : ' this'} as final{when ? ` on ${when}` : ''}.
        Comments are closed.
      </p>
    </div>
  )
}

export function SignOffDialog({
  assetName, status, defaultName = '', defaultEmail = '', onSubmit, onCancel,
}: {
  assetName: string
  status: ShareSignOffStatus
  defaultName?: string
  defaultEmail?: string
  /** Resolves once the sign-off is recorded; rejects with a message to show. */
  onSubmit: (name: string, email: string) => Promise<void>
  onCancel: () => void
}) {
  const [name, setName] = React.useState(defaultName)
  const [email, setEmail] = React.useState(defaultEmail)
  const [agree, setAgree] = React.useState(false)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const emailLooksRight = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())
  const ready = name.trim().length >= 2 && emailLooksRight && agree && !busy

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!ready) return
    setBusy(true)
    setError(null)
    try {
      await onSubmit(name.trim(), email.trim())
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : 'The sign-off could not be saved. Please try again.')
      setBusy(false)
    }
  }

  const inputClass = 'w-full rounded-md border border-border bg-bg-tertiary px-3 py-2 text-[16px] [@media(hover:hover)]:text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <form
        onSubmit={submit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="sign-off-title"
        className="w-full max-w-md rounded-xl border border-border bg-bg-secondary p-5 shadow-xl"
      >
        <h3 id="sign-off-title" className="text-sm font-semibold text-text-primary mb-1">Sign off {assetName}</h3>
        <p className="text-xs text-text-tertiary mb-4">
          Signing off confirms this version is final. It will be locked, and you will be able to download the finished file.
        </p>
        <div className="space-y-3">
          <div>
            <label htmlFor="sign-off-name" className="block text-xs font-medium text-text-secondary mb-1">Full name</label>
            <input
              id="sign-off-name" type="text" autoComplete="name" autoFocus
              value={name} onChange={(e) => setName(e.target.value)} className={inputClass}
            />
          </div>
          <div>
            <label htmlFor="sign-off-email" className="block text-xs font-medium text-text-secondary mb-1">Email address</label>
            <input
              id="sign-off-email" type="email" autoComplete="email"
              value={email} onChange={(e) => setEmail(e.target.value)} className={inputClass}
            />
            <p className="mt-1 text-[11px] text-text-tertiary">We&apos;ll email you a confirmation with the download link.</p>
          </div>
          <label className="flex items-start gap-2.5 rounded-md border border-border bg-bg-tertiary px-3 py-2.5 cursor-pointer">
            <input
              type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)}
              className="mt-0.5 h-4 w-4 shrink-0 accent-accent"
            />
            <span className="text-xs text-text-primary leading-relaxed">
              {status.statement ?? 'I approve this version as final and confirm that no further changes are required.'}
            </span>
          </label>
        </div>
        {error && <p role="alert" className="mt-3 text-xs text-status-error">{error}</p>}
        <div className="flex items-center justify-end gap-2 mt-4">
          <button type="button" onClick={onCancel} disabled={busy} className="px-3 py-1.5 text-xs text-text-tertiary hover:text-text-primary transition-colors disabled:opacity-50">
            Cancel
          </button>
          <button
            type="submit" disabled={!ready}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-md bg-accent text-xs font-medium text-white hover:bg-accent/90 disabled:opacity-50 transition-colors"
          >
            {busy && <Loader2 className="h-3 w-3 animate-spin" />} Sign off
          </button>
        </div>
      </form>
    </div>
  )
}
