'use client'

/**
 * The team's view of a client sign-off: who signed which version and when,
 * and, for the project's owner, the way to reopen it.
 *
 * A signed-off asset is locked on the server (no new versions, no comments).
 * This shows why, so nobody is left guessing at a refused upload.
 */
import * as React from 'react'
import useSWR from 'swr'
import { CheckCircle2, Loader2, LockOpen } from 'lucide-react'
import { api } from '@/lib/api'

export interface SignOffRecord {
  id: string
  asset_id: string
  version_id: string
  version_number: number
  asset_name: string
  signer_name: string
  signer_email: string
  statement: string
  ip_address: string | null
  user_agent: string | null
  created_at: string
  reopened_at: string | null
  reopened_by: string | null
  reopen_reason: string | null
}

export interface AssetSignOffState {
  signed_off: boolean
  current: SignOffRecord | null
  history: SignOffRecord[]
}

/** The asset's sign-off state. Undefined while loading or if it could not be read. */
export function useAssetSignOff(assetId: string | undefined) {
  const { data, mutate } = useSWR<AssetSignOffState>(
    assetId ? `/assets/${assetId}/sign-off` : null,
    (key: string) => api.get<AssetSignOffState>(key),
  )
  return { signOff: data, mutate }
}

function formatWhen(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString(undefined, {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

/** Top-bar pill for a signed-off asset; opens the record. */
export function SignOffBadge({
  state, canReopen, onReopened,
}: {
  state: AssetSignOffState | undefined
  canReopen: boolean
  onReopened: (next: AssetSignOffState) => void
}) {
  const [open, setOpen] = React.useState(false)
  const record = state?.current
  if (!record) return null
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 rounded-md px-2.5 h-8 text-xs font-medium text-status-success bg-status-success/10 hover:bg-status-success/20 transition-colors min-w-0"
        title="View the sign-off"
      >
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">Signed off by {record.signer_name}</span>
      </button>
      {open && (
        <SignOffRecordDialog
          record={record}
          canReopen={canReopen}
          onClose={() => setOpen(false)}
          onReopened={(next) => { setOpen(false); onReopened(next) }}
        />
      )}
    </>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5">
      <dt className="text-xs text-text-tertiary shrink-0">{label}</dt>
      <dd className="text-xs text-text-primary text-right break-words min-w-0">{children}</dd>
    </div>
  )
}

function SignOffRecordDialog({
  record, canReopen, onClose, onReopened,
}: {
  record: SignOffRecord
  canReopen: boolean
  onClose: () => void
  onReopened: (next: AssetSignOffState) => void
}) {
  const [confirming, setConfirming] = React.useState(false)
  const [reason, setReason] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const reopen = async () => {
    setBusy(true)
    setError(null)
    try {
      const next = await api.post<AssetSignOffState>(
        `/assets/${record.asset_id}/sign-off/reopen`,
        { reason: reason.trim() || null },
      )
      onReopened(next)
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : 'Could not reopen this. Please try again.')
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div role="dialog" aria-modal="true" aria-labelledby="sign-off-record-title" className="w-full max-w-md rounded-xl border border-border bg-bg-secondary p-5 shadow-xl">
        <h3 id="sign-off-record-title" className="flex items-center gap-2 text-sm font-semibold text-text-primary mb-3">
          <CheckCircle2 className="h-4 w-4 text-status-success" /> Client sign-off
        </h3>
        <dl className="divide-y divide-border">
          <Row label="Signed by">{record.signer_name}</Row>
          <Row label="Email">{record.signer_email}</Row>
          <Row label="When">{formatWhen(record.created_at)}</Row>
          <Row label="Version">v{record.version_number}</Row>
          {record.ip_address && <Row label="Internet address">{record.ip_address}</Row>}
        </dl>
        <p className="mt-3 text-xs text-text-tertiary">They agreed:</p>
        <p className="mt-1 rounded-md border border-border bg-bg-tertiary px-3 py-2 text-xs text-text-primary leading-relaxed">{record.statement}</p>
        <p className="mt-3 text-xs text-text-tertiary">
          This is locked: no new versions or comments. The client can download the original from their share link.
        </p>

        {confirming && (
          <div className="mt-4">
            <label htmlFor="reopen-reason" className="block text-xs font-medium text-text-secondary mb-1">
              Why is this being reopened? (optional, kept on the record)
            </label>
            <textarea
              id="reopen-reason" rows={2} maxLength={1000} autoFocus
              value={reason} onChange={(e) => setReason(e.target.value)}
              className="w-full rounded-md border border-border bg-bg-tertiary px-3 py-2 text-[16px] [@media(hover:hover)]:text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent"
            />
            <p className="mt-1 text-[11px] text-text-tertiary">
              Reopening unlocks it and stops the client&apos;s download until it is signed off again. The sign-off above stays on record.
            </p>
          </div>
        )}
        {error && <p role="alert" className="mt-3 text-xs text-status-error">{error}</p>}

        <div className="flex items-center justify-end gap-2 mt-4">
          <button onClick={onClose} disabled={busy} className="px-3 py-1.5 text-xs text-text-tertiary hover:text-text-primary transition-colors disabled:opacity-50">
            Close
          </button>
          {canReopen && !confirming && (
            <button
              onClick={() => setConfirming(true)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-border text-xs font-medium text-text-secondary hover:text-text-primary hover:bg-bg-hover transition-colors"
            >
              <LockOpen className="h-3 w-3" /> Reopen
            </button>
          )}
          {canReopen && confirming && (
            <button
              onClick={reopen} disabled={busy}
              className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-md bg-accent text-xs font-medium text-white hover:bg-accent/90 disabled:opacity-50 transition-colors"
            >
              {busy && <Loader2 className="h-3 w-3 animate-spin" />} Reopen for changes
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

/** Stands in for the comment box on a signed-off asset. */
export function SignedOffLockNotice({ record }: { record: SignOffRecord }) {
  return (
    <div className="shrink-0 border-t border-border px-4 py-3 text-xs text-text-secondary">
      <p className="flex items-center gap-1.5 font-medium text-text-primary">
        <CheckCircle2 className="h-3.5 w-3.5 text-status-success" /> Signed off by {record.signer_name}
      </p>
      <p className="mt-1">Version {record.version_number} is locked. Comments and new versions are closed until it is reopened.</p>
    </div>
  )
}
