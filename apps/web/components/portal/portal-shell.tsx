'use client'

/**
 * The frame around every client-portal page: the studio's logo, who is signed
 * in, and Sign out. Deliberately not the team's app shell: a client has no
 * projects rail, uploads or settings to be shown.
 */
import * as React from 'react'
import { LogOut } from 'lucide-react'
import { ShareBrandMark } from '@/components/share/share-brand-mark'
import { useBranding } from '@/components/shared/branding-provider'
import { clearTokens, refreshAccessToken } from '@/lib/auth'
import { withBasePath } from '@/lib/base-path'

/** Keeps the session alive while a client watches or reads for a long time. */
export function usePortalSessionKeepAlive() {
  React.useEffect(() => {
    const id = window.setInterval(() => { refreshAccessToken().catch(() => {}) }, 8 * 60 * 1000)
    return () => window.clearInterval(id)
  }, [])
}

export function signOutOfPortal() {
  clearTokens()
  window.location.replace(withBasePath('/login?mode=code'))
}

export function PortalShell({ viewerName, children }: { viewerName?: string; children: React.ReactNode }) {
  const { orgName } = useBranding()
  usePortalSessionKeepAlive()
  return (
    <div className="min-h-dvh bg-bg-primary text-text-primary">
      <header className="sticky top-0 z-10 border-b border-border bg-bg-secondary/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-3 px-4">
          <div className="flex items-center gap-3 min-w-0">
            <ShareBrandMark theme="dark" />
            <span className="hidden sm:inline font-display text-sm text-text-secondary truncate">{orgName}</span>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            {viewerName && <span className="hidden sm:inline text-sm text-text-secondary truncate max-w-[14rem]">{viewerName}</span>}
            <button
              onClick={signOutOfPortal}
              className="inline-flex items-center gap-1.5 rounded-md px-2.5 h-8 text-xs font-medium border border-border text-text-secondary hover:text-text-primary hover:bg-bg-hover transition-colors"
            >
              <LogOut className="h-3.5 w-3.5" /> Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6 sm:py-8">{children}</main>
    </div>
  )
}
