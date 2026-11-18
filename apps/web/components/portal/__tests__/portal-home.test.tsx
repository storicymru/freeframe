/**
 * The client's library: what needs review, what is delivered, the archive.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within, waitFor } from '@testing-library/react'
import { PortalHomeView } from '../portal-home'
import type { PortalAsset, PortalHome } from '../portal-types'

const handleDownload = vi.hoisted(() => vi.fn(async () => {}))
vi.mock('@/components/share/share-download', () => ({ handleDownload }))

function asset(over: Partial<PortalAsset>): PortalAsset {
  return {
    id: 'a', name: 'Clip', asset_type: 'video', status: 'in_review', thumbnail_url: null,
    duration_seconds: 62, version_number: 2, updated_at: '2026-11-10T10:00:00Z', comment_count: 0,
    signed_off_by: null, signed_off_at: null, ...over,
  }
}

const HOME: PortalHome = {
  viewer_name: 'Carys Evans',
  viewer_email: 'carys@client.example',
  projects: [{
    id: 'p1', name: 'Swansea Bay City Deal', token: 'portal-token',
    needs_review: [asset({ id: 'r1', name: 'Launch film v2', comment_count: 3 })],
    delivered: [asset({ id: 'd1', name: 'Case study final', status: 'approved', signed_off_by: 'Carys Evans', signed_off_at: '2026-11-01T09:00:00Z' })],
    archive: [asset({ id: 'x1', name: 'Old promo 2024', status: 'archived' })],
  }],
}

beforeEach(() => handleDownload.mockClear())

describe('PortalHomeView', () => {
  it('greets the client and says how much is waiting', () => {
    render(<PortalHomeView home={HOME} />)
    expect(screen.getByRole('heading', { name: 'Hello, Carys' })).toBeInTheDocument()
    expect(screen.getByText('1 video is waiting for your review.')).toBeInTheDocument()
  })

  it('puts each video under the right heading', () => {
    render(<PortalHomeView home={HOME} />)
    const review = screen.getByRole('region', { name: /needs your review/i })
    const delivered = screen.getByRole('region', { name: /delivered/i })
    const archive = screen.getByRole('region', { name: /archive/i })
    expect(within(review).getByText('Launch film v2')).toBeInTheDocument()
    expect(within(delivered).getByText('Case study final')).toBeInTheDocument()
    expect(within(archive).getByText('Old promo 2024')).toBeInTheDocument()
  })

  it('offers Review on what is waiting, and no download', () => {
    render(<PortalHomeView home={HOME} />)
    const review = screen.getByRole('region', { name: /needs your review/i })
    expect(within(review).getByRole('link', { name: /^review$/i })).toHaveAttribute('href', '/portal/review/r1')
    expect(within(review).queryByRole('button', { name: /download/i })).toBeNull()
  })

  it('downloads a delivered video through the portal link', async () => {
    render(<PortalHomeView home={HOME} />)
    const delivered = screen.getByRole('region', { name: /delivered/i })
    expect(within(delivered).getByText(/signed off by carys evans/i)).toBeInTheDocument()
    fireEvent.click(within(delivered).getByRole('button', { name: /download/i }))
    await waitFor(() => expect(handleDownload).toHaveBeenCalledWith('portal-token', 'd1', null))
  })

  it('says so plainly when nothing has been shared yet', () => {
    render(<PortalHomeView home={{ ...HOME, projects: [{ ...HOME.projects[0], needs_review: [], delivered: [], archive: [] }] }} />)
    expect(screen.getByText(/nothing has been shared with you yet/i)).toBeInTheDocument()
    expect(screen.queryByRole('region')).toBeNull()
  })

  it('names each client project when there is more than one', () => {
    const two: PortalHome = { ...HOME, projects: [HOME.projects[0], { ...HOME.projects[0], id: 'p2', name: 'Another Client', needs_review: [asset({ id: 'r2', name: 'Other film' })], delivered: [], archive: [] }] }
    render(<PortalHomeView home={two} />)
    expect(screen.getByRole('heading', { name: 'Swansea Bay City Deal' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Another Client' })).toBeInTheDocument()
  })

  it('searches across the library once it is big enough to need it', () => {
    const many = Array.from({ length: 8 }, (_, i) => asset({ id: `m${i}`, name: `Film ${i}`, status: 'approved' }))
    render(<PortalHomeView home={{ ...HOME, projects: [{ ...HOME.projects[0], delivered: many }] }} />)
    fireEvent.change(screen.getByRole('searchbox', { name: /search your videos/i }), { target: { value: 'film 3' } })
    expect(screen.getByText('Film 3')).toBeInTheDocument()
    expect(screen.queryByText('Film 4')).toBeNull()
    expect(screen.queryByText('Launch film v2')).toBeNull()
  })
})
