'use client'

/**
 * Managing a video's versions, for the project's owner.
 *
 * One dialog: every version with what it costs in storage, and four things to
 * do with them. Keep only the latest; delete one; release one as a video of
 * its own; or stack another video onto this one as its newest versions. The
 * server decides what is allowed and says why not; this shows its answers.
 * Removed versions go to the trash, where an admin can restore them or free
 * the space straight away.
 */
import * as React from 'react'
import { Layers, Loader2, X } from 'lucide-react'
import { api } from '@/lib/api'
import { cn, formatBytes, formatRelativeTime } from '@/lib/utils'
import { SelectMenu } from '@/components/ui/select-menu'
import type { Asset } from '@/types'

export interface TidyPlanVersion {
  version_id: string
  version_number: number
  processing_status: string
  bytes: number
  created_at?: string | null
  action: 'keep' | 'remove'
  reason: string | null
}

export interface TidyPlan {
  asset_id: string
  asset_name: string
  versions: TidyPlanVersion[]
  remove_count: number
  remove_bytes: number
  total_bytes: number
}

type Pending =
  | { kind: 'tidy' }
  | { kind: 'delete'; version: TidyPlanVersion }
  | { kind: 'release'; version: TidyPlanVersion }
  | { kind: 'reprocess'; version: TidyPlanVersion }
  | { kind: 'stack'; source: Asset }

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

const count = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

/** "18 Nov 2026, 04:27": the date and time a version was uploaded. */
function exactTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function ManageVersionsButton({
  assetId, projectId, assetType, onChanged, onReleased,
}: {
  assetId: string
  projectId: string
  assetType: string
  /** The stack changed: reload what the page shows. */
  onChanged: () => void
  /** A version became its own video; the page may want to go there. */
  onReleased?: (newAssetId: string, name: string) => void
}) {
  const [open, setOpen] = React.useState(false)
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="Manage versions"
        className="inline-flex h-7 items-center gap-1.5 rounded-md border border-border px-2.5 text-xs font-medium text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors"
      >
        <Layers className="h-3.5 w-3.5" />
        <span className="hidden lg:inline">Versions</span>
      </button>
      {open && (
        <ManageVersionsDialog
          assetId={assetId} projectId={projectId} assetType={assetType}
          onClose={() => setOpen(false)} onChanged={onChanged} onReleased={onReleased}
        />
      )}
    </>
  )
}

export function ManageVersionsDialog({
  assetId, projectId, assetType, onClose, onChanged, onReleased,
}: {
  assetId: string
  projectId: string
  assetType: string
  onClose: () => void
  onChanged: () => void
  onReleased?: (newAssetId: string, name: string) => void
}) {
  const [plan, setPlan] = React.useState<TidyPlan | null>(null)
  const [others, setOthers] = React.useState<Asset[]>([])
  const [sourceId, setSourceId] = React.useState('')
  const [pending, setPending] = React.useState<Pending | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [notice, setNotice] = React.useState<{ text: string; assetId?: string } | null>(null)

  const load = React.useCallback(async () => {
    try {
      const [nextPlan, assets] = await Promise.all([
        api.get<TidyPlan>(`/assets/${assetId}/versions/tidy`),
        api.get<Asset[]>(`/projects/${projectId}/assets`).catch(() => [] as Asset[]),
      ])
      setPlan(nextPlan)
      setOthers(assets.filter((a) => a.id !== assetId && a.asset_type === assetType))
      setError(null)
    } catch (e) {
      setError(messageOf(e, 'The versions could not be loaded.'))
    }
  }, [assetId, projectId, assetType])

  React.useEffect(() => {
    // Loaded through a promise so the state is set from its callback.
    Promise.resolve().then(load)
  }, [load])

  const run = async (action: Pending) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      if (action.kind === 'tidy') {
        const done = await api.post<TidyPlan>(`/assets/${assetId}/versions/tidy`, { confirm_count: plan?.remove_count ?? 0 })
        setNotice({ text: `${count(done.remove_count, 'version')} moved to the trash, ${formatBytes(done.remove_bytes)} to be freed.` })
      } else if (action.kind === 'delete') {
        await api.delete(`/assets/${assetId}/versions/${action.version.version_id}`)
        setNotice({ text: `Version ${action.version.version_number} moved to the trash.` })
      } else if (action.kind === 'reprocess') {
        await api.post(`/assets/${assetId}/versions/${action.version.version_id}/reprocess`, {})
        setNotice({ text: `Version ${action.version.version_number} is being processed again. It stays watchable while that runs.` })
      } else if (action.kind === 'release') {
        const made = await api.post<{ asset_id: string; name: string }>(
          `/assets/${assetId}/versions/${action.version.version_id}/release`, {},
        )
        setNotice({ text: `Version ${action.version.version_number} is now its own video, “${made.name}”.`, assetId: made.asset_id })
      } else {
        const done = await api.post<{ moved_versions: number; version_numbers: number[] }>(
          `/assets/${assetId}/stack`, { source_asset_id: action.source.id },
        )
        setSourceId('')
        setNotice({ text: `“${action.source.name}” added as version${done.version_numbers.length === 1 ? '' : 's'} ${done.version_numbers.join(', ')}.` })
      }
      setPending(null)
      await load()
      onChanged()
    } catch (e) {
      setError(messageOf(e, 'That could not be done. Try again.'))
    } finally {
      setBusy(false)
    }
  }

  const live = plan?.versions ?? []
  const newestFirst = [...live].sort((a, b) => b.version_number - a.version_number)
  const source = others.find((a) => a.id === sourceId)
  const small = 'rounded-md px-2.5 h-7 text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div role="dialog" aria-modal="true" aria-labelledby="manage-versions-title"
        className="flex max-h-[88vh] w-full max-w-xl flex-col rounded-2xl bg-bg-secondary shadow-xl">
        <div className="flex items-start justify-between gap-3 px-5 pt-5">
          <div className="min-w-0">
            <h3 id="manage-versions-title" className="text-base font-semibold text-text-primary">Versions</h3>
            <p className="mt-0.5 text-xs text-text-tertiary truncate">
              {plan ? `${plan.asset_name} · ${count(live.length, 'version')} · ${formatBytes(plan.total_bytes)}` : 'Loading…'}
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-md p-1.5 text-text-tertiary hover:bg-bg-hover hover:text-text-primary">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-4 flex-1 space-y-4 overflow-y-auto px-5 pb-5">
          {notice && (
            <p role="status" className="rounded-xl bg-status-success/10 px-3 py-2 text-xs text-text-primary">
              {notice.text}{' '}
              {notice.assetId && (
                <button type="button" className="font-medium text-accent underline underline-offset-2"
                  onClick={() => onReleased?.(notice.assetId as string, notice.text)}>
                  Open it
                </button>
              )}
            </p>
          )}
          {error && <p role="alert" className="rounded-xl bg-status-error/10 px-3 py-2 text-xs text-status-error">{error}</p>}

          <ul className="divide-y divide-border rounded-xl bg-bg-tertiary">
            {!plan && !error && (
              <li className="flex items-center gap-2 px-3 py-3 text-xs text-text-tertiary"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading versions…</li>
            )}
            {newestFirst.map((version) => {
              const inFlight = version.processing_status === 'uploading' || version.processing_status === 'processing'
              const signed = version.reason === 'signed off by the client'
              const only = live.length <= 1
              const asking = pending && 'version' in pending && pending.version.version_id === version.version_id ? pending : null
              return (
                <li key={version.version_id} className="px-3 py-2.5">
                  <div className="flex items-center gap-3">
                    <span className="w-9 shrink-0 text-sm font-semibold tabular-nums text-text-primary">v{version.version_number}</span>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs tabular-nums text-text-secondary">
                        {formatBytes(version.bytes)}
                        {version.created_at && (
                          <span title={exactTime(version.created_at)}> · uploaded {formatRelativeTime(version.created_at)}</span>
                        )}
                      </p>
                      <p className="text-[11px] text-text-tertiary truncate">
                        {version.action === 'keep' && version.reason ? version.reason : version.processing_status}
                        {version.created_at ? ` · ${exactTime(version.created_at)}` : ''}
                      </p>
                    </div>
                    {assetType === 'video' && (
                      <button type="button" disabled={busy || version.processing_status !== 'ready'}
                        onClick={() => setPending({ kind: 'reprocess', version })}
                        title="Make the playback copies again from the original file, with the current quality settings"
                        className={cn(small, 'border border-border text-text-secondary hover:bg-bg-hover hover:text-text-primary')}>
                        Reprocess
                      </button>
                    )}
                    <button type="button" disabled={busy || only || inFlight}
                      onClick={() => setPending({ kind: 'release', version })}
                      title={only ? 'This is the only version' : 'Make this version a separate video'}
                      className={cn(small, 'border border-border text-text-secondary hover:bg-bg-hover hover:text-text-primary')}>
                      Release
                    </button>
                    <button type="button" disabled={busy || only || inFlight || signed}
                      onClick={() => setPending({ kind: 'delete', version })}
                      title={signed ? 'Signed off: reopen it first' : only ? 'This is the only version' : 'Move this version to the trash'}
                      className={cn(small, 'text-status-error hover:bg-status-error/10')}>
                      Delete
                    </button>
                  </div>
                  {asking && (
                    <div className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-bg-secondary px-3 py-2">
                      <p className="text-xs text-text-secondary">
                        {asking.kind === 'reprocess'
                          ? `Process version ${version.version_number} again from its original file? Nothing is uploaded, and it stays watchable meanwhile. A long video can take a while.`
                          : asking.kind === 'delete'
                          ? `Move version ${version.version_number} to the trash? It frees ${formatBytes(version.bytes)} once the trash is emptied.`
                          : `Make version ${version.version_number} a separate video in this project? Its comments go with it.`}
                      </p>
                      <span className="flex gap-2">
                        <button type="button" disabled={busy} onClick={() => setPending(null)} className={cn(small, 'text-text-tertiary hover:text-text-primary')}>Cancel</button>
                        <button type="button" disabled={busy} onClick={() => run(asking)}
                          className={cn(small, 'bg-accent text-text-inverse hover:bg-accent-hover inline-flex items-center gap-1.5')}>
                          {busy && <Loader2 className="h-3 w-3 animate-spin" />}
                          {asking.kind === 'reprocess' ? 'Reprocess' : asking.kind === 'delete' ? 'Delete version' : 'Release it'}
                        </button>
                      </span>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>

          <section className="rounded-xl bg-bg-tertiary p-3.5">
            <h4 className="text-sm font-semibold text-text-primary">Keep only the latest</h4>
            <p className="mt-1 text-xs text-text-secondary">
              {plan && plan.remove_count > 0
                ? `Removes ${count(plan.remove_count, 'older version')} and frees ${formatBytes(plan.remove_bytes)}. They go to the trash, where an admin can bring them back or free the space straight away.`
                : 'There is nothing older to remove.'}
            </p>
            {plan && plan.remove_count > 0 && (
              <div className="mt-3 flex justify-end gap-2">
                {pending?.kind === 'tidy' ? (
                  <>
                    <button type="button" disabled={busy} onClick={() => setPending(null)} className={cn(small, 'text-text-tertiary hover:text-text-primary')}>Cancel</button>
                    <button type="button" disabled={busy} onClick={() => run({ kind: 'tidy' })}
                      className={cn(small, 'bg-accent text-text-inverse hover:bg-accent-hover inline-flex items-center gap-1.5')}>
                      {busy && <Loader2 className="h-3 w-3 animate-spin" />}
                      Remove {count(plan.remove_count, 'version')}
                    </button>
                  </>
                ) : (
                  <button type="button" disabled={busy} onClick={() => setPending({ kind: 'tidy' })}
                    className={cn(small, 'bg-accent text-text-inverse hover:bg-accent-hover')}>
                    Keep only the latest
                  </button>
                )}
              </div>
            )}
          </section>

          <section className="rounded-xl bg-bg-tertiary p-3.5">
            <h4 className="text-sm font-semibold text-text-primary">Stack another video onto this one</h4>
            <p className="mt-1 text-xs text-text-secondary">
              For a revision that was uploaded as a new video. It becomes the newest version here, its comments
              come with it, and links to it open this video.
            </p>
            {others.length === 0 ? (
              <p className="mt-2 text-xs text-text-tertiary">There is no other video in this project to stack.</p>
            ) : (
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <SelectMenu
                  label="Video to stack"
                  placeholder="Choose a video…"
                  value={sourceId}
                  onChange={(next) => { setSourceId(next); setPending(null) }}
                  options={others.map((a) => ({ value: a.id, label: a.name }))}
                  disabled={busy}
                  searchable={others.length > 6}
                  size="sm"
                  className="min-w-0 flex-1 bg-bg-secondary"
                />
                {pending?.kind === 'stack' && source ? (
                  <>
                    <button type="button" disabled={busy} onClick={() => setPending(null)} className={cn(small, 'text-text-tertiary hover:text-text-primary')}>Cancel</button>
                    <button type="button" disabled={busy} onClick={() => run({ kind: 'stack', source })}
                      className={cn(small, 'bg-accent text-text-inverse hover:bg-accent-hover inline-flex items-center gap-1.5')}>
                      {busy && <Loader2 className="h-3 w-3 animate-spin" />}
                      Stack “{source.name.length > 24 ? `${source.name.slice(0, 24)}…` : source.name}”
                    </button>
                  </>
                ) : (
                  <button type="button" disabled={busy || !source} onClick={() => source && setPending({ kind: 'stack', source })}
                    className={cn(small, 'bg-accent text-text-inverse hover:bg-accent-hover')}>
                    Stack
                  </button>
                )}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}
