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
import { SelectMenu, type SelectMenuOption } from '@/components/ui/select-menu'
import type { AssetStatus } from '@/types'

const OPTIONS: SelectMenuOption<AssetStatus>[] = [
  { value: 'draft', label: 'Hidden from client', detail: 'Not in their portal' },
  { value: 'in_review', label: 'For review', detail: 'In their review list, and they are emailed' },
  { value: 'rejected', label: 'Changes requested', detail: 'Still in their review list' },
  { value: 'approved', label: 'Delivered', detail: 'Download released' },
  { value: 'archived', label: 'Archived', detail: 'Filed under their archive' },
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
    <>
      <SelectMenu<AssetStatus>
        label="Client portal status"
        value={value}
        onChange={change}
        options={OPTIONS}
        disabled={disabled || busy}
        size="sm"
        variant="quiet"
        align="end"
        title={error ?? (disabled ? disabledReason : 'What the client sees in their portal')}
        icon={busy ? <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" /> : hidden ? <EyeOff className="h-3.5 w-3.5 shrink-0" /> : <Eye className="h-3.5 w-3.5 shrink-0" />}
      />
      {error && <span role="alert" className="sr-only">{error}</span>}
    </>
  )
}
