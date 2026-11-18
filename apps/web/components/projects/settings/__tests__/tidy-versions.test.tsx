import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const { api } = vi.hoisted(() => ({ api: { get: vi.fn(), post: vi.fn() } }))
vi.mock('@/lib/api', async (orig) => ({ ...(await orig<typeof import('@/lib/api')>()), api }))

import { ProjectTidyVersions } from '../tidy-versions'

// Tidying a finished job: the latest version of each video stays, the rest go to the trash.

const GB = 1024 ** 3
const finished = {
  scope: 'finished', remove_count: 3, remove_bytes: 5 * GB,
  assets: [
    { asset_id: 'a1', asset_name: 'Episode 3', remove_count: 2, remove_bytes: 4 * GB, total_bytes: 6 * GB, versions: [] },
    { asset_id: 'a2', asset_name: 'Trailer', remove_count: 1, remove_bytes: 1 * GB, total_bytes: 2 * GB, versions: [] },
  ],
}
const nothing = { scope: 'all', remove_count: 0, remove_bytes: 0, assets: [] }

beforeEach(() => {
  api.get.mockReset()
  api.post.mockReset()
})

describe('tidying a project', () => {
  it('shows what would go, video by video, for finished videos by default', async () => {
    api.get.mockResolvedValue(finished)
    render(<ProjectTidyVersions projectId="p1" />)
    expect(await screen.findByText('Episode 3')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/projects/p1/versions/tidy?scope=finished')
    expect(screen.getByText('2 versions · 4 GB')).toBeInTheDocument()
    expect(screen.getByText(/3 versions to remove, freeing/)).toHaveTextContent('5 GB')
  })

  it('asks again when the scope is widened', async () => {
    api.get.mockResolvedValue(finished)
    render(<ProjectTidyVersions projectId="p1" />)
    await screen.findByText('Episode 3')
    fireEvent.click(screen.getByLabelText('Every video in the project'))
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/projects/p1/versions/tidy?scope=all'))
  })

  it('tidies only after a second click, with the count and scope it showed', async () => {
    api.get.mockResolvedValue(finished)
    api.post.mockResolvedValue(finished)
    render(<ProjectTidyVersions projectId="p1" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Tidy versions' }))
    expect(api.post).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /Remove 3 versions/ }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/projects/p1/versions/tidy', { scope: 'finished', confirm_count: 3 }))
    expect(await screen.findByRole('status')).toHaveTextContent('3 versions moved to the trash across 2 videos, 5 GB to be freed.')
  })

  it('says so when there is nothing to remove, and offers no button', async () => {
    api.get.mockResolvedValue(nothing)
    render(<ProjectTidyVersions projectId="p1" />)
    expect(await screen.findByText('No finished video has older versions to remove.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Tidy versions' })).not.toBeInTheDocument()
  })

  it("shows the server's reason when the tidy is refused", async () => {
    api.get.mockResolvedValue(finished)
    api.post.mockRejectedValue(new Error('The versions changed since you looked. Check again and confirm.'))
    render(<ProjectTidyVersions projectId="p1" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Tidy versions' }))
    fireEvent.click(screen.getByRole('button', { name: /Remove 3 versions/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/changed since you looked/)
  })
})
