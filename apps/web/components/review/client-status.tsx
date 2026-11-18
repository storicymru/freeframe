'use client'

/**
 * What the client sees of this video in the client portal, set by the team.
 *
 * It is the asset's status under plainer names: a draft is hidden from the
 * client, "For review" puts it in their review list (and emails them),
 * "Delivered" releases the download, and "Archived" files it under their
 * archive. A client signing it off marks it delivered by itself.
 */
import * as React from 'react'
import { Eye, EyeOff, Loader2 } from 'lucide-react'
import { api } from '@/lib/api'
import type { AssetStatus } from '@/types'

const OPTIONS: { value: AssetStatus; label: string }[] = [
  { value: 'draft', label: 'Hidden from client' },
  { value: 'in_review', label: 'For review' },
  { value: 'rejected', label: 'Changes requested' },
  { value: 'approved', label: 'Delivered' },
  { value: 'archived', label: 'Archived' },
]

export function ClientStatusSelect({
  assetId, status, disabled, disabledReason, onChanged,
}: {
  assetId: string
  status: AssetStatus
  /** A signed-off video keeps its status until it is reopened. */
  disabled?: boolean
  disabledReason?: string
  onChanged?: (status: AssetStatus) => void
}) {
  const [value, setValue] = React.useState<AssetStatus>(status)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  React.useEffect(() => { setValue(status) }, [status])

  const change = async (next: AssetStatus) => {
    const previous = value
    setValue(next)
    setBusy(true)
    setError(null)
    try {
      await api.patch(`/assets/${assetId}`, { status: next })
      onChanged?.(next)
    } catch (e) {
      setValue(previous)
      setError(e instanceof Error && e.message ? e.message : 'The status could not be changed')
    } finally {
      setBusy(false)
    }
  }

  const hidden = value === 'draft'
  return (
    <label
      className="inline-flex items-center gap-1.5 rounded-md border border-border px-2 h-8 text-xs text-text-secondary"
      title={error ?? (disabled ? disabledReason : 'What the client sees in their portal')}
    >
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : hidden ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
      <span className="sr-only">Client portal status</span>
      <select
        value={value}
        disabled={disabled || busy}
        onChange={(e) => change(e.target.value as AssetStatus)}
        className="bg-transparent text-xs font-medium text-text-primary focus:outline-none disabled:opacity-60 cursor-pointer disabled:cursor-not-allowed"
      >
        {OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      {error && <span role="alert" className="sr-only">{error}</span>}
    </label>
  )
}
