'use client'

/**
 * One video in the client portal: the same review screen a share link shows
 * (player, comments, sign-off, download), run on the project's portal link.
 */
import * as React from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Loader2 } from 'lucide-react'
import { PortalShell, usePortalSessionKeepAlive } from '@/components/portal/portal-shell'
import { usePortalHome } from '@/components/portal/use-portal-home'
import { ShareReviewScreen } from '@/components/share/share-review-screen'

export default function PortalReviewPage({ params }: { params: Promise<{ assetId: string }> }) {
  const { assetId } = React.use(params)
  const router = useRouter()
  const state = usePortalHome()
  usePortalSessionKeepAlive()

  if (state.stage === 'loading') {
    return <div className="flex items-center justify-center h-dvh bg-bg-primary"><Loader2 className="h-8 w-8 animate-spin text-text-tertiary" /></div>
  }

  const found = state.stage === 'ready'
    ? state.home.projects
        .map((project) => ({
          project,
          asset: [...project.needs_review, ...project.delivered, ...project.archive].find((a) => a.id === assetId),
        }))
        .find((hit) => hit.asset)
    : undefined

  if (state.stage !== 'ready' || !found?.asset) {
    return (
      <PortalShell viewerName={state.stage === 'ready' ? state.home.viewer_name : undefined}>
        <h1 className="text-lg font-semibold text-text-primary">This video is not available</h1>
        <p className="mt-2 text-sm text-text-secondary">It may have been moved or is no longer shared with you.</p>
        <Link href="/portal" className="mt-4 inline-flex items-center rounded-md bg-accent px-4 h-9 text-sm font-medium text-text-inverse hover:bg-accent-hover transition-colors">
          Back to your videos
        </Link>
      </PortalShell>
    )
  }

  return (
    <ShareReviewScreen
      token={found.project.token}
      assetId={found.asset.id}
      assetName={found.asset.name}
      permission="comment"
      // The portal link releases downloads itself, once the video is delivered.
      allowDownload={false}
      showVersions={false}
      viewerName={state.home.viewer_name}
      viewerEmail={state.home.viewer_email}
      onBack={() => router.push('/portal')}
    />
  )
}
