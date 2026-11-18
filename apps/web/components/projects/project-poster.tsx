import { cn } from '@/lib/utils'
import { getGradientForProject } from '@/lib/gradient-utils'
import type { Project } from '@/types'

type PosterProject = Pick<Project, 'id' | 'name' | 'poster_url'> &
  Partial<Pick<Project, 'brand_logo_url' | 'brand_primary_color' | 'brand_secondary_color'>>

/** Only a plain hex colour is ever put into a style. */
const hex = (value?: string | null) => (value && /^#[0-9a-f]{6}$/i.test(value) ? value : null)

/**
 * The client's logo on a white tile, as Cylch shows it: readable on any
 * colour, whatever the logo's own background. Nothing for a project with no
 * logo. The caller places and sizes it.
 */
export function ProjectLogoTile({ project, className }: { project: PosterProject; className?: string }) {
  if (!project.brand_logo_url) return null
  return (
    <span
      data-project-logo={project.id}
      className={cn('flex items-center justify-center overflow-hidden rounded-2xl bg-white p-1.5', className)}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={project.brand_logo_url} alt="" loading="lazy" decoding="async" className="h-full w-full object-contain" />
    </span>
  )
}

/**
 * A project's picture: the poster someone chose; or else the client's own
 * colours, where the project has branding (set here, or sent by Cylch); or
 * else the gradient the project's id picks. The card and the list row both
 * show it, so a project looks the same in either view. Fills its container,
 * which sets the size, the shape and `relative`.
 */
export function ProjectPoster({ project, className }: { project: PosterProject; className?: string }) {
  if (project.poster_url) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={project.poster_url}
        alt={project.name}
        loading="lazy"
        decoding="async"
        className={cn('h-full w-full object-cover', className)}
      />
    )
  }
  // One colour, or the two as Cylch's header has them.
  const c1 = hex(project.brand_primary_color)
  const c2 = hex(project.brand_secondary_color)
  if (c1) {
    return (
      <div
        data-project-poster={project.id}
        data-brand-colours=""
        className={cn('h-full w-full', className)}
        style={{ background: c2 ? `linear-gradient(120deg, ${c1}, ${c2})` : c1 }}
      />
    )
  }
  return (
    <div
      data-project-poster={project.id}
      className={cn('h-full w-full bg-gradient-to-br', getGradientForProject(project.id), className)}
    >
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_40%,rgba(255,255,255,0.1),transparent_60%)]" />
    </div>
  )
}
