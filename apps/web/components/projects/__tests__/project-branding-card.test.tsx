import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import { ProjectLogoTile, ProjectPoster } from '../project-poster'
import { nameBand, projectInitials, ProjectCard } from '../project-card'
import { getBandColourForProject } from '@/lib/gradient-utils'
import type { Project } from '@/types'

vi.mock('@/lib/api', () => ({ api: { get: vi.fn(), delete: vi.fn(), patch: vi.fn(), post: vi.fn() } }))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))

/**
 * A project's branding (set in its settings, or sent across by Cylch) shows on
 * its card: the client's logo on a white tile, and their colours where there
 * is no cover picture. These pin what is shown and what is never let through.
 */

const base = { id: 'p1', name: 'Nightmode', poster_url: null }

describe('ProjectLogoTile', () => {
  it('shows the logo on a white tile', () => {
    const { container } = render(<ProjectLogoTile project={{ ...base, brand_logo_url: 'https://files.test/logo.png' }} />)
    const tile = container.querySelector('[data-project-logo="p1"]') as HTMLElement
    expect(tile.className).toContain('bg-white')
    expect(tile.querySelector('img')).toHaveAttribute('src', 'https://files.test/logo.png')
  })

  it('is not there for a project with no logo', () => {
    const { container } = render(<ProjectLogoTile project={base} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('ProjectPoster', () => {
  it('uses the client\'s one colour when there is no cover picture', () => {
    const { container } = render(<ProjectPoster project={{ ...base, brand_primary_color: '#1B365D' }} />)
    const poster = container.querySelector('[data-brand-colours]') as HTMLElement
    expect(poster.style.background).toBe('rgb(27, 54, 93)')
  })

  it('runs the two colours together when there are two', () => {
    const { container } = render(
      <ProjectPoster project={{ ...base, brand_primary_color: '#1b365d', brand_secondary_color: '#cb2c30' }} />,
    )
    const poster = container.querySelector('[data-brand-colours]') as HTMLElement
    expect(poster.style.background).toContain('linear-gradient')
  })

  it('keeps a cover picture ahead of the colours', () => {
    const { container } = render(
      <ProjectPoster project={{ ...base, poster_url: 'https://files.test/cover.jpg', brand_primary_color: '#1b365d' }} />,
    )
    expect(container.querySelector('img')).toHaveAttribute('src', 'https://files.test/cover.jpg')
    expect(container.querySelector('[data-brand-colours]')).toBeNull()
  })

  it.each(['red', 'url(https://evil.example/x)', '#12345', '#1b365d; background: url(x)'])(
    'never puts anything but a plain hex colour into a style (%s)',
    (value) => {
      const { container } = render(<ProjectPoster project={{ ...base, brand_primary_color: value }} />)
      expect(container.querySelector('[data-brand-colours]')).toBeNull()
      expect((container.firstElementChild as HTMLElement).className).toContain('bg-gradient-to-br')
    },
  )
})

describe('nameBand', () => {
  it('puts dark text on a light colour and white on a dark one, so the name can be read', () => {
    expect(nameBand('#f8e92c')).toEqual({ background: '#f8e92c', text: '#111111' })
    expect(nameBand('#04a89b')).toEqual({ background: '#04a89b', text: '#ffffff' })
    expect(nameBand('#1b365d')).toEqual({ background: '#1b365d', text: '#ffffff' })
  })

  it('falls back to the dark pill for no colour or anything that is not a plain hex colour', () => {
    for (const bad of [null, undefined, 'red', 'url(x)', '#12']) {
      expect(nameBand(bad)).toEqual({ background: '#111111', text: '#ffffff' })
    }
  })
})

describe('projectInitials', () => {
  it('takes the first letters of the first two words, or one for a one-word name', () => {
    expect(projectInitials('Prawf / Test')).toBe('PT')
    expect(projectInitials('Nightmode')).toBe('N')
    expect(projectInitials('plant dewi | Ysgol')).toBe('PD')
    expect(projectInitials('Ŵyl Ifan')).toBe('ŴI')
    expect(projectInitials('— / —')).toBe('')
  })
})

describe('ProjectCard name band', () => {
  const card: Project = {
    id: 'p1',
    name: 'Nightmode',
    description: null,
    created_by: 'u1',
    project_type: 'personal',
    created_at: '2026-01-01T00:00:00Z',
    deleted_at: null,
  }
  const bandOf = (c: HTMLElement) => c.querySelector('[data-name-band="p1"]') as HTMLElement
  const rgb = (hex: string) => `rgb(${[1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16)).join(', ')})`

  it('puts a project with no picture on the deep shade of its gradient, with its initials', () => {
    const { container } = render(<ProjectCard project={card} />)
    expect(bandOf(container).style.background).toBe(rgb(getBandColourForProject('p1')))
    expect(bandOf(container)).toHaveTextContent('Nightmode')
    expect(container.querySelector('[data-project-initials="p1"]')).toHaveTextContent('N')
  })

  it('uses the client\'s colour when the project has one, logo or not', () => {
    const { container } = render(<ProjectCard project={{ ...card, brand_primary_color: '#04a89b' }} />)
    expect(bandOf(container).style.background).toBe('rgb(4, 168, 155)')
  })

  it('shows no initials over a logo or a cover picture', () => {
    const withLogo = render(<ProjectCard project={{ ...card, brand_logo_url: 'https://files.test/logo.png' }} />)
    expect(withLogo.container.querySelector('[data-logo-card="p1"]')).not.toBeNull()
    expect(withLogo.container.querySelector('[data-project-initials]')).toBeNull()
    withLogo.unmount()
    const withCover = render(<ProjectCard project={{ ...card, poster_url: 'https://files.test/cover.jpg' }} />)
    expect(withCover.container.querySelector('[data-project-initials]')).toBeNull()
    expect(bandOf(withCover.container).style.background).toBe('rgb(17, 17, 17)')
  })
})
