'use client'

/**
 * Tidying a whole project's versions, for when a job is finished.
 *
 * Every round of review leaves a version behind, each with its own upload and
 * its own processed copies. This keeps the latest version of each video and
 * moves the rest to the trash. By default only finished videos (approved,
 * archived or signed off) are touched; the owner can widen it to every video.
 * A version a client signed off is always kept.
 */
import * as React from 'react'
import { Layers, Loader2 } from 'lucide-react'
import { api } from '@/lib/api'
import { formatBytes } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import type { TidyPlan } from '@/components/review/manage-versions'

type Scope = 'finished' | 'all'

interface ProjectTidyPlan {
  scope: Scope
  assets: TidyPlan[]
  remove_count: number
  remove_bytes: number
}

const count = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

export function ProjectTidyVersions({ projectId }: { projectId: string }) {
  const [scope, setScope] = React.useState<Scope>('finished')
  const [plan, setPlan] = React.useState<ProjectTidyPlan | null>(null)
  const [confirming, setConfirming] = React.useState(false)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [done, setDone] = React.useState<string | null>(null)

  const load = React.useCallback(async (which: Scope) => {
    try {
      setPlan(await api.get<ProjectTidyPlan>(`/projects/${projectId}/versions/tidy?scope=${which}`))
      setError(null)
    } catch (e) {
      setPlan(null)
      setError(e instanceof Error && e.message ? e.message : 'The versions could not be checked.')
    }
  }, [projectId])

  React.useEffect(() => {
    // Loaded through a promise so the state is set from its callback.
    Promise.resolve(scope).then(load)
  }, [load, scope])

  const tidy = async () => {
    if (!plan) return
    setBusy(true)
    setError(null)
    try {
      const result = await api.post<ProjectTidyPlan>(`/projects/${projectId}/versions/tidy`, {
        scope, confirm_count: plan.remove_count,
      })
      setDone(`${count(result.remove_count, 'version')} moved to the trash across ${count(result.assets.length, 'video')}, ${formatBytes(result.remove_bytes)} to be freed.`)
      setConfirming(false)
      await load(scope)
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : 'The tidy could not be done. Try again.')
    } finally {
      setBusy(false)
    }
  }

  const nothing = plan !== null && plan.remove_count === 0

  return (
    <section className="rounded-xl bg-bg-secondary">
      <div className="flex items-start gap-3 p-5">
        <Layers className="mt-0.5 h-5 w-5 shrink-0 text-text-secondary" />
        <div className="min-w-0 flex-1 space-y-2">
          <h2 className="text-sm font-semibold text-text-primary">Tidy up old versions</h2>
          <p className="text-sm text-text-secondary">
            Keeps the latest version of each video and moves the earlier ones to the trash. A version a client
            signed off is always kept. An admin can restore from the trash, or empty it to free the space now.
          </p>
          <fieldset className="flex flex-wrap gap-x-5 gap-y-1 pt-1 text-sm text-text-primary">
            <legend className="sr-only">Which videos</legend>
            {([['finished', 'Finished videos only'], ['all', 'Every video in the project']] as const).map(([value, label]) => (
              <label key={value} className="inline-flex items-center gap-2">
                <input type="radio" name="tidy-scope" value={value} checked={scope === value} disabled={busy}
                  onChange={() => { setScope(value); setConfirming(false); setDone(null) }} className="accent-accent" />
                {label}
              </label>
            ))}
          </fieldset>
          {plan && !nothing && (
            <ul className="max-h-48 divide-y divide-border overflow-y-auto rounded-lg bg-bg-tertiary text-sm">
              {plan.assets.map((asset) => (
                <li key={asset.asset_id} className="flex items-center justify-between gap-3 px-3 py-2">
                  <span className="min-w-0 truncate text-text-primary">{asset.asset_name}</span>
                  <span className="shrink-0 tabular-nums text-xs text-text-secondary">
                    {count(asset.remove_count, 'version')} · {formatBytes(asset.remove_bytes)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {nothing && (
            <p className="text-sm text-text-tertiary">
              {scope === 'finished' ? 'No finished video has older versions to remove.' : 'No video has older versions to remove.'}
            </p>
          )}
          {done && <p role="status" className="text-sm text-status-success">{done}</p>}
          {error && <p role="alert" className="text-sm text-status-error">{error}</p>}
        </div>
      </div>
      {plan && !nothing && (
        <div className="flex items-center justify-between gap-3 border-t border-border px-5 py-3">
          <p className="text-sm text-text-secondary">
            {count(plan.remove_count, 'version')} to remove, freeing <span className="font-medium text-text-primary">{formatBytes(plan.remove_bytes)}</span>
          </p>
          {confirming ? (
            <span className="flex gap-2">
              <Button variant="ghost" size="sm" disabled={busy} onClick={() => setConfirming(false)}>Cancel</Button>
              <Button size="sm" disabled={busy} onClick={tidy}>
                {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Remove {count(plan.remove_count, 'version')}
              </Button>
            </span>
          ) : (
            <Button size="sm" onClick={() => { setConfirming(true); setDone(null) }}>Tidy versions</Button>
          )}
        </div>
      )}
    </section>
  )
}
