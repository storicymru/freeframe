import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

const { api } = vi.hoisted(() => ({ api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }))
vi.mock('@/lib/api', async (orig) => ({ ...(await orig<typeof import('@/lib/api')>()), api }))

import { ManageVersionsButton } from '../manage-versions'

// The owner's version housekeeping: tidy, delete one, release one, stack another video.
// The server decides what is kept; the dialog shows its plan and asks before acting.

const GB = 1024 ** 3
const plan = {
  asset_id: 'a1', asset_name: 'Episode 3', remove_count: 2, remove_bytes: 4 * GB, total_bytes: 6 * GB,
  versions: [
    { version_id: 'v1', version_number: 1, processing_status: 'ready', bytes: 2 * GB, action: 'remove', reason: null },
    { version_id: 'v2', version_number: 2, processing_status: 'ready', bytes: 2 * GB, action: 'remove', reason: null },
    { version_id: 'v3', version_number: 3, processing_status: 'ready', bytes: 2 * GB, action: 'keep', reason: 'the latest version' },
  ],
}
const others = [
  { id: 'a1', name: 'Episode 3', asset_type: 'video' },
  { id: 'a2', name: 'Episode 3 FINAL', asset_type: 'video' },
  { id: 'a3', name: 'Poster', asset_type: 'image' },
]

const onChanged = vi.fn()
const onReleased = vi.fn()

async function open(withPlan: unknown = plan) {
  api.get.mockImplementation((path: string) => Promise.resolve(path.endsWith('/versions/tidy') ? withPlan : others))
  render(<ManageVersionsButton assetId="a1" projectId="p1" assetType="video" onChanged={onChanged} onReleased={onReleased} />)
  fireEvent.click(screen.getByRole('button', { name: /Versions/ }))
  const dialog = await screen.findByRole('dialog')
  await within(dialog).findByText('v3')
  return dialog
}

beforeEach(() => {
  api.get.mockReset()
  api.post.mockReset()
  api.delete.mockReset()
  onChanged.mockReset()
  onReleased.mockReset()
})

describe('the versions dialog', () => {
  it('lists every version with its size, newest first, and what a tidy would free', async () => {
    const dialog = await open()
    expect(within(dialog).getByText(/Episode 3 · 3 versions · 6 GB/)).toBeInTheDocument()
    const rows = within(dialog).getAllByRole('listitem')
    expect(rows.map((row) => row.textContent?.slice(0, 2))).toEqual(['v3', 'v2', 'v1'])
    expect(within(rows[0]).getByText('the latest version')).toBeInTheDocument()
    expect(within(dialog).getByText(/Removes 2 older versions and frees 4 GB/)).toBeInTheDocument()
  })

  it('tidies only after a second click, sending the count it showed', async () => {
    const dialog = await open()
    api.post.mockResolvedValue({ ...plan })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Keep only the latest' }))
    expect(api.post).not.toHaveBeenCalled()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Remove 2 versions' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/assets/a1/versions/tidy', { confirm_count: 2 }))
    expect(await within(dialog).findByText(/2 versions moved to the trash, 4 GB to be freed/)).toBeInTheDocument()
    expect(onChanged).toHaveBeenCalledTimes(1)
  })

  it('deletes one version after asking', async () => {
    const dialog = await open()
    api.delete.mockResolvedValue({})
    const row = within(dialog).getAllByRole('listitem')[1]
    fireEvent.click(within(row).getByRole('button', { name: 'Delete' }))
    expect(within(row).getByText(/Move version 2 to the trash\? It frees 2 GB/)).toBeInTheDocument()
    fireEvent.click(within(row).getByRole('button', { name: 'Delete version' }))
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/assets/a1/versions/v2'))
  })

  it('releases a version and offers to open the new video', async () => {
    const dialog = await open()
    api.post.mockResolvedValue({ asset_id: 'new1', name: 'Episode 3 (v1)' })
    const row = within(dialog).getAllByRole('listitem')[2]
    fireEvent.click(within(row).getByRole('button', { name: 'Release' }))
    fireEvent.click(within(row).getByRole('button', { name: 'Release it' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/assets/a1/versions/v1/release', {}))
    fireEvent.click(await within(dialog).findByRole('button', { name: 'Open it' }))
    expect(onReleased).toHaveBeenCalledWith('new1', expect.any(String))
  })

  it('offers only other videos of the same kind to stack, and stacks after asking', async () => {
    const dialog = await open()
    const select = within(dialog).getByLabelText('Video to stack')
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['Choose a video…', 'Episode 3 FINAL'])
    expect(within(dialog).getByRole('button', { name: 'Stack' })).toBeDisabled()

    api.post.mockResolvedValue({ moved_versions: 1, version_numbers: [4] })
    fireEvent.change(select, { target: { value: 'a2' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Stack' }))
    fireEvent.click(within(dialog).getByRole('button', { name: /Stack “Episode 3 FINAL”/ }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/assets/a1/stack', { source_asset_id: 'a2' }))
    expect(await within(dialog).findByText(/“Episode 3 FINAL” added as version 4/)).toBeInTheDocument()
  })

  it("shows the server's reason when it refuses, and changes nothing", async () => {
    const dialog = await open()
    api.post.mockRejectedValue(new Error('“Episode 3” has been signed off. Reopen the sign-off before changing its versions.'))
    fireEvent.change(within(dialog).getByLabelText('Video to stack'), { target: { value: 'a2' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Stack' }))
    fireEvent.click(within(dialog).getByRole('button', { name: /Stack “Episode 3 FINAL”/ }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(/has been signed off/)
    expect(onChanged).not.toHaveBeenCalled()
  })

  it('will not delete or release the only version, or delete a signed-off one', async () => {
    const single = { ...plan, remove_count: 0, remove_bytes: 0, versions: [plan.versions[2]] }
    const dialog = await open(single)
    const row = within(dialog).getByRole('listitem')
    expect(within(row).getByRole('button', { name: 'Delete' })).toBeDisabled()
    expect(within(row).getByRole('button', { name: 'Release' })).toBeDisabled()
    expect(within(dialog).getByText('There is nothing older to remove.')).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: 'Keep only the latest' })).not.toBeInTheDocument()
  })
})
