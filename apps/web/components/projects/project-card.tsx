'use client'

import * as React from 'react'
import Link from 'next/link'
import { MoreHorizontal, Globe } from 'lucide-react'
import { cn, formatRelativeTime, formatBytes } from '@/lib/utils'
import { ContextMenuArea, DotsMenu } from '@/components/shared/item-menu'
import { ProjectLogoTile, ProjectPoster } from './project-poster'
import { useProjectMenu } from './menus/project-menu'
import { getBandColourForProject } from '@/lib/gradient-utils'
import type { Project } from '@/types'

/**
 * Up to two letters for a project with no picture: the first letters of its
 * first two words ("Prawf / Test" is PT), or the first letter of a one-word
 * name. Nothing when the name has no letters or digits.
 */
export function projectInitials(name: string): string {
  const words = name.match(/[\p{L}\p{N}]+/gu) ?? []
  return words.slice(0, 2).map((w) => w[0]).join('').toUpperCase()
}

interface ProjectCardProps {
  project: Project
  showRole?: boolean
  isOwner?: boolean
  /** Show the info row under the poster. */
  showInfo?: boolean
  className?: string
}

/**
 * The band the name sits on under a logo: the client's colour, with the text
 * dark or white according to which can be read on it. Without a usable colour,
 * the app's own dark pill.
 */
export function nameBand(colour?: string | null): { background: string; text: string } {
  if (!colour || !/^#[0-9a-f]{6}$/i.test(colour)) return { background: '#111111', text: '#ffffff' }
  const [r, g, b] = [1, 3, 5].map((at) => {
    const v = parseInt(colour.slice(at, at + 2), 16) / 255
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  })
  const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
  return { background: colour, text: luminance > 0.4 ? '#111111' : '#ffffff' }
}

export function ProjectCard({
  project,
  showRole,
  isOwner,
  showInfo = true,
  className,
}: ProjectCardProps) {
  const assetCount = project.asset_count ?? 0
  // With a logo and no cover picture, the logo fills the card.
  const logoCard = !!project.brand_logo_url && !project.poster_url
  // The band takes the client's colour where there is one, else the deep
  // shade of the project's own gradient (or plain dark under a cover picture).
  const brand = /^#[0-9a-f]{6}$/i.test(project.brand_primary_color ?? '') ? project.brand_primary_color : null
  const band = nameBand(brand ?? (project.poster_url ? null : getBandColourForProject(project.id)))
  const { items: menuItems } = useProjectMenu(project, { isOwner })

  return (
    <>
      <ContextMenuArea items={menuItems}>
      <div className={cn('group relative', className)}>
        <Link
          href={`/projects/${project.id}`}
          className="block rounded-xl overflow-hidden bg-bg-secondary border border-border hover:border-accent/40 transition-all duration-200 hover:shadow-lg hover:shadow-black/10"
        >
          {/* Square card: the picture on top, the name on a band underneath.
              Every project gets the same shape, so the grid reads as one. */}
          <div className="relative aspect-square w-full overflow-hidden">
            <div className="absolute inset-x-0 top-0 bottom-16 overflow-hidden">
              {logoCard ? (
                // The client's logo is the picture: on white, as large as it will go.
                <div data-logo-card={project.id} className="flex h-full w-full items-center justify-center bg-white p-[12%]">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={project.brand_logo_url ?? ''} alt="" loading="lazy" decoding="async" className="h-full w-full object-contain" />
                </div>
              ) : (
                <>
                  <ProjectPoster project={project} />
                  {/* No picture and no logo: the project's initials, large, so
                      a colour card still says whose it is at a glance. */}
                  {!project.poster_url && (
                    <span
                      data-project-initials={project.id}
                      aria-hidden
                      className="pointer-events-none absolute inset-0 flex items-center justify-center text-[clamp(2rem,9vw,4rem)] font-bold tracking-tight opacity-90"
                      style={{ color: band.text }}
                    >
                      {projectInitials(project.name)}
                    </span>
                  )}
                  {/* A project with its own cover picture keeps it, with the
                      logo as a small tile in the corner. */}
                  <ProjectLogoTile project={project} className="absolute left-3 top-3 h-14 w-14 shadow-sm" />
                </>
              )}
            </div>
            <div
              data-name-band={project.id}
              className="absolute inset-x-0 bottom-0 flex h-16 flex-col justify-center px-3 shadow-[inset_0_1px_0_rgba(0,0,0,0.08)]"
              style={{ background: band.background, color: band.text }}
            >
              <p className={cn('text-[15px] font-semibold leading-tight', project.description ? 'line-clamp-1' : 'line-clamp-2')}>
                {project.name}
              </p>
              {project.description && (
                <p className="mt-0.5 text-[11px] line-clamp-1 opacity-80">{project.description}</p>
              )}
            </div>

            {/* Public/role badges */}
            <div className={cn('absolute top-2.5 flex items-center gap-1.5', project.brand_logo_url ? 'right-2.5' : 'left-2.5')}>
              {project.is_public && (
                <span className="inline-flex items-center gap-1 rounded-full bg-black/30 backdrop-blur-sm px-2 py-0.5 text-[10px] font-medium text-white/90">
                  <Globe className="h-2.5 w-2.5" />
                  Public
                </span>
              )}
              {showRole && project.role && project.role !== 'owner' && (
                <span className="inline-flex items-center rounded-full bg-black/30 backdrop-blur-sm px-2 py-0.5 text-[10px] font-medium text-white/90 capitalize">
                  {project.role}
                </span>
              )}
            </div>
          </div>

          {/* Footer */}
          {showInfo && (
            <div className="flex items-center justify-between px-3 py-2.5">
              <span className="text-2xs text-text-tertiary">
                {assetCount > 0
                  ? `${assetCount} item${assetCount !== 1 ? 's' : ''} · ${formatBytes(project.storage_bytes ?? 0)}`
                  : `Updated ${formatRelativeTime(project.created_at)}`}
              </span>
            </div>
          )}
        </Link>

        {/* Menu button: owners only, like the menu itself */}
        {menuItems && (
          <DotsMenu items={menuItems}>
            <button
              aria-label={`${project.name} menu`}
              className={cn(
                'absolute flex h-7 w-7 items-center justify-center rounded-md transition-all opacity-0 group-hover:opacity-100 data-[state=open]:opacity-100',
                // Without the info row it sits on the poster, styled like the badges.
                showInfo
                  ? 'bottom-2 right-2.5 text-text-tertiary hover:bg-bg-hover hover:text-text-primary'
                  : 'top-2.5 right-2.5 bg-black/30 backdrop-blur-sm text-white/90 hover:bg-black/50 hover:text-white',
              )}
              onClick={(e) => { e.preventDefault(); e.stopPropagation() }}
            >
              <MoreHorizontal className="h-4 w-4" />
            </button>
          </DotsMenu>
        )}
      </div>
      </ContextMenuArea>
    </>
  )
}
