'use client'

import * as React from 'react'
import { usePathname } from 'next/navigation'
import { Search, ChevronRight, PanelRightClose, PanelRightOpen } from 'lucide-react'
import Link from 'next/link'
import { useBranding } from '@/components/shared/branding-provider'
import { useResolvedTheme } from '@/hooks/use-resolved-theme'
import { resolveBrandingLogo } from '@/lib/branding-logo'
import { ThemedDefaultLogo } from '@/components/shared/themed-default-logo'
import { cn } from '@/lib/utils'
import { useViewStore } from '@/stores/view-store'
import { useBreadcrumbStore } from '@/stores/breadcrumb-store'

interface HeaderProps {
  onSearchOpen: () => void
}

const LABEL_MAP: Record<string, string> = {
  projects: 'Projects',
  notifications: 'Notifications',
  settings: 'Settings',
  new: 'New',
  upload: 'Upload',
}

/** Looks like a UUID (8-4-4-4-12 hex) */
function isUuid(s: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s)
}

/**
 * Route path segments that are structural only and should not appear in the breadcrumb.
 * e.g. /projects/{id}/assets/{assetId} — "assets" is just a route prefix, not a meaningful label.
 */
const SKIP_SEGMENTS = new Set(['assets', 'collections'])

function buildBreadcrumbs(pathname: string, dynamicLabels: Record<string, string>): { label: string; href: string }[] {
  const segments = pathname.split('/').filter(Boolean)
  const crumbs: { label: string; href: string }[] = []

  let path = ''
  for (const segment of segments) {
    path += `/${segment}`
    // Skip structural route segments
    if (SKIP_SEGMENTS.has(segment)) continue
    // Skip UUID segments that don't have a label registered
    if (isUuid(segment) && !dynamicLabels[segment]) continue
    const label =
      dynamicLabels[segment] ??
      LABEL_MAP[segment] ??
      segment.charAt(0).toUpperCase() + segment.slice(1).replace(/-/g, ' ')
    crumbs.push({ label, href: path })
  }

  return crumbs
}

export function Header({ onSearchOpen }: HeaderProps) {
  const pathname = usePathname()
  const { rightPanelOpen, toggleRightPanel } = useViewStore()
  const { labels, extraCrumbs } = useBreadcrumbStore()
  const { orgName, orgLogoDark, orgLogoLight } = useBranding()
  const theme = useResolvedTheme()
  const customLogo = resolveBrandingLogo({ theme, darkUrl: orgLogoDark, lightUrl: orgLogoLight })
  const urlCrumbs = buildBreadcrumbs(pathname, labels)
  const breadcrumbs = [...urlCrumbs, ...extraCrumbs.map((c) => ({ label: c.label, href: c.href ?? '' }))]

  return (
    <header className="sticky top-0 z-20 flex h-14 items-center justify-between gap-3 bg-bg-primary/90 backdrop-blur-sm px-4">
      {/* On a phone the rail, and the mark at its head, are gone: it sits here. */}
      <Link href="/projects" aria-label={orgName || 'Home'} className="md:hidden shrink-0">
        {customLogo ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={customLogo} alt="" className="h-9 w-9 object-contain" />
        ) : (
          <ThemedDefaultLogo variant="icon" alt="" className="h-7 w-7 object-contain" />
        )}
      </Link>

      {/* Breadcrumbs */}
      <nav className="flex min-w-0 flex-1 items-center gap-1 text-[13px]">
        {breadcrumbs.map((crumb, index) => {
          const isLast = index === breadcrumbs.length - 1
          return (
            <React.Fragment key={`${crumb.href}-${index}`}>
              {index > 0 && (
                <ChevronRight className="h-3 w-3 text-text-tertiary" />
              )}
              {isLast ? (
                <span className="font-medium text-text-primary">{crumb.label}</span>
              ) : crumb.href ? (
                <Link
                  href={crumb.href}
                  className="text-text-tertiary hover:text-text-secondary transition-colors"
                >
                  {crumb.label}
                </Link>
              ) : (
                <span className="text-text-tertiary">{crumb.label}</span>
              )}
            </React.Fragment>
          )
        })}
      </nav>

      {/* Right side actions */}
      <div className="flex items-center gap-1.5">
        {/* Search trigger */}
        <button
          onClick={onSearchOpen}
          // Cylch's search: a white pill on the page, no border.
          className="flex h-10 items-center gap-2.5 rounded-full bg-bg-secondary px-4 text-[13px] text-text-tertiary hover:text-text-secondary transition-colors sm:min-w-[220px]"
        >
          <Search className="h-4 w-4" />
          <span className="hidden sm:inline flex-1 text-left">Search</span>
          <kbd className="hidden sm:inline-flex items-center gap-0.5 font-sans text-xs text-text-tertiary">
            <span>⌘</span>K
          </kbd>
        </button>

        {/* Panel toggle — only on project detail pages, not the listing */}
        {pathname !== '/projects' && (
          <button
            onClick={toggleRightPanel}
            className={cn(
              'flex h-10 w-10 items-center justify-center rounded-full bg-bg-secondary transition-colors',
              rightPanelOpen
                ? 'text-text-primary'
                : 'text-text-tertiary hover:text-text-primary',
            )}
            title={rightPanelOpen ? 'Hide panel' : 'Show panel'}
          >
            {rightPanelOpen ? (
              <PanelRightClose className="h-4 w-4" />
            ) : (
              <PanelRightOpen className="h-4 w-4" />
            )}
          </button>
        )}
      </div>
    </header>
  )
}
