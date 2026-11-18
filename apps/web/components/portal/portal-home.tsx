'use client'

/**
 * A client's library: for each project they are a client of, what needs their
 * review, what has been delivered, and the archive.
 */
import * as React from 'react'
import Link from 'next/link'
import { CheckCircle2, Download, Film, Loader2, MessageSquare, Play, Search } from 'lucide-react'
import { handleDownload } from '@/components/share/share-download'
import { formatTime } from '@/lib/utils'
import type { PortalAsset, PortalHome, PortalProject } from './portal-types'

function formatDate(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

function Thumbnail({ asset }: { asset: PortalAsset }) {
  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-t-lg bg-bg-tertiary">
      {asset.thumbnail_url ? (
        // A presigned storage link; the Next image optimiser cannot fetch it.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={asset.thumbnail_url} alt="" className="h-full w-full object-cover" loading="lazy" />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-text-tertiary"><Film className="h-8 w-8" /></div>
      )}
      {asset.duration_seconds != null && asset.duration_seconds > 0 && (
        <span className="absolute bottom-1.5 right-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[11px] font-medium text-white">
          {formatTime(asset.duration_seconds)}
        </span>
      )}
    </div>
  )
}

function AssetCard({ asset, project, kind }: { asset: PortalAsset; project: PortalProject; kind: 'review' | 'delivered' | 'archive' }) {
  const [downloading, setDownloading] = React.useState(false)
  const reviewHref = `/portal/review/${asset.id}`
  const download = async () => {
    setDownloading(true)
    try {
      await handleDownload(project.token, asset.id, null)
    } finally {
      setDownloading(false)
    }
  }
  return (
    <li className="flex flex-col rounded-lg border border-border bg-bg-secondary">
      <Link href={reviewHref} aria-label={`Open ${asset.name}`}><Thumbnail asset={asset} /></Link>
      <div className="flex flex-1 flex-col gap-2 p-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-text-primary" title={asset.name}>{asset.name}</p>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-text-tertiary">
            {asset.version_number != null && <span>Version {asset.version_number}</span>}
            {asset.updated_at && <span>{formatDate(asset.updated_at)}</span>}
            {asset.comment_count > 0 && (
              <span className="inline-flex items-center gap-1"><MessageSquare className="h-3 w-3" />{asset.comment_count}</span>
            )}
          </p>
          {kind === 'review' && asset.status === 'rejected' && (
            <p className="mt-1 text-xs text-status-warning">Changes requested</p>
          )}
          {asset.signed_off_by && (
            <p className="mt-1 flex items-center gap-1 text-xs text-status-success">
              <CheckCircle2 className="h-3 w-3 shrink-0" />
              <span className="truncate">Signed off by {asset.signed_off_by}{asset.signed_off_at ? `, ${formatDate(asset.signed_off_at)}` : ''}</span>
            </p>
          )}
        </div>
        <div className="mt-auto flex items-center gap-2">
          {kind === 'review' ? (
            <Link
              href={reviewHref}
              className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md bg-accent px-3 h-8 text-xs font-medium text-text-inverse hover:bg-accent-hover transition-colors"
            >
              <Play className="h-3 w-3" /> Review
            </Link>
          ) : (
            <>
              <button
                onClick={download}
                disabled={downloading}
                className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md bg-accent px-3 h-8 text-xs font-medium text-text-inverse hover:bg-accent-hover disabled:opacity-60 transition-colors"
              >
                {downloading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />} Download
              </button>
              <Link
                href={reviewHref}
                className="inline-flex items-center justify-center rounded-md border border-border px-3 h-8 text-xs font-medium text-text-secondary hover:text-text-primary hover:bg-bg-hover transition-colors"
              >
                View
              </Link>
            </>
          )}
        </div>
      </div>
    </li>
  )
}

function Section({
  title, hint, assets, project, kind,
}: { title: string; hint?: string; assets: PortalAsset[]; project: PortalProject; kind: 'review' | 'delivered' | 'archive' }) {
  if (assets.length === 0) return null
  return (
    <section aria-label={`${project.name}: ${title}`} className="mt-5">
      <h3 className="flex items-baseline gap-2 text-sm font-semibold text-text-primary">
        {title} <span className="text-xs font-normal text-text-tertiary">{assets.length}</span>
      </h3>
      {hint && <p className="mt-0.5 text-xs text-text-tertiary">{hint}</p>}
      <ul className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {assets.map((asset) => <AssetCard key={asset.id} asset={asset} project={project} kind={kind} />)}
      </ul>
    </section>
  )
}

function matches(asset: PortalAsset, needle: string): boolean {
  return asset.name.toLowerCase().includes(needle)
}

export function PortalHomeView({ home }: { home: PortalHome }) {
  const [query, setQuery] = React.useState('')
  const needle = query.trim().toLowerCase()
  const projects = home.projects.map((project) => needle ? {
    ...project,
    needs_review: project.needs_review.filter((a) => matches(a, needle)),
    delivered: project.delivered.filter((a) => matches(a, needle)),
    archive: project.archive.filter((a) => matches(a, needle)),
  } : project)
  const total = home.projects.reduce((n, p) => n + p.needs_review.length + p.delivered.length + p.archive.length, 0)
  const waiting = home.projects.reduce((n, p) => n + p.needs_review.length, 0)
  const shown = projects.reduce((n, p) => n + p.needs_review.length + p.delivered.length + p.archive.length, 0)

  return (
    <div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Hello, {home.viewer_name.split(' ')[0]}</h1>
          <p className="mt-1 text-sm text-text-secondary">
            {total === 0
              ? 'Nothing has been shared with you yet. We will email you when there is something to see.'
              : waiting > 0
                ? `${waiting} ${waiting === 1 ? 'video is' : 'videos are'} waiting for your review.`
                : 'Nothing is waiting for your review. Your delivered videos are below.'}
          </p>
        </div>
        {total > 6 && (
          <label className="relative block w-full sm:w-64">
            <span className="sr-only">Search your videos</span>
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-tertiary" />
            <input
              type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search your videos"
              className="w-full rounded-md border border-border bg-bg-tertiary pl-8 pr-3 py-2 text-[16px] [@media(hover:hover)]:text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent"
            />
          </label>
        )}
      </div>

      {needle && shown === 0 && (
        <p className="mt-8 text-sm text-text-secondary">No videos match &ldquo;{query.trim()}&rdquo;.</p>
      )}

      {projects.map((project) => {
        const count = project.needs_review.length + project.delivered.length + project.archive.length
        if (count === 0 && (needle || home.projects.length > 1)) return null
        return (
          <div key={project.id} className="mt-8">
            {home.projects.length > 1 && (
              <h2 className="border-b border-border pb-2 text-base font-semibold text-text-primary">{project.name}</h2>
            )}
            <Section title="Needs your review" hint="Watch, leave comments, and sign off when you are happy." assets={project.needs_review} project={project} kind="review" />
            <Section title="Delivered" hint="Finished videos, ready to download." assets={project.delivered} project={project} kind="delivered" />
            <Section title="Archive" assets={project.archive} project={project} kind="archive" />
          </div>
        )
      })}
    </div>
  )
}
