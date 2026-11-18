import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { ProjectLogoTile, ProjectPoster } from '../project-poster'

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
