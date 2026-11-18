'use client'

import Link from 'next/link'
import { Loader2 } from 'lucide-react'
import { PortalHomeView } from '@/components/portal/portal-home'
import { PortalShell } from '@/components/portal/portal-shell'
import { usePortalHome } from '@/components/portal/use-portal-home'

export default function PortalPage() {
  const state = usePortalHome()

  if (state.stage === 'loading') {
    return <div className="flex items-center justify-center h-dvh bg-bg-primary"><Loader2 className="h-8 w-8 animate-spin text-text-tertiary" /></div>
  }
  if (state.stage === 'not_client') {
    return (
      <PortalShell>
        <h1 className="text-lg font-semibold text-text-primary">This is the client portal</h1>
        <p className="mt-2 text-sm text-text-secondary">
          You are signed in with a team account, which uses the main app. Clients see their own videos here.
        </p>
        <Link href="/projects" className="mt-4 inline-flex items-center rounded-md bg-accent px-4 h-9 text-sm font-medium text-text-inverse hover:bg-accent-hover transition-colors">
          Go to your projects
        </Link>
      </PortalShell>
    )
  }
  if (state.stage === 'error') {
    return (
      <PortalShell>
        <h1 className="text-lg font-semibold text-text-primary">Your portal could not be loaded</h1>
        <p className="mt-2 text-sm text-text-secondary">Please check your connection and reload the page.</p>
      </PortalShell>
    )
  }
  return (
    <PortalShell viewerName={state.home.viewer_name}>
      <PortalHomeView home={state.home} />
    </PortalShell>
  )
}
