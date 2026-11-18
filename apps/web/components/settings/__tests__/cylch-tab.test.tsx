import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'

const get = vi.fn()
const post = vi.fn()
const del = vi.fn()
vi.mock('@/lib/api', () => ({
  api: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a), delete: (...a: unknown[]) => del(...a) },
}))

import { CylchTab } from '../cylch-tab'

/** A fresh SWR cache per test, so one test's status never answers for the next. */
function show() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <CylchTab />
    </SWRConfig>,
  )
}

describe('CylchTab', () => {
  beforeEach(() => {
    get.mockReset()
    post.mockReset()
    del.mockReset()
  })

  it('makes a key and shows it once, with nothing to confirm when there was none', async () => {
    get.mockResolvedValue({ has_key: false, made_at: null, used_at: null })
    post.mockResolvedValue({ has_key: true, made_at: new Date().toISOString(), used_at: null, key: 'adb_cylch_abc123' })
    show()

    await screen.findByText(/there is no key/i)
    fireEvent.click(screen.getByRole('button', { name: /make a key/i }))

    expect(await screen.findByText('adb_cylch_abc123')).toBeInTheDocument()
    expect(screen.getByText(/won.t be shown again/i)).toBeInTheDocument()
    expect(post).toHaveBeenCalledWith('/integrations/cylch/key')
  })

  it('asks before replacing a key, because the old one stops working', async () => {
    // The status never carries the key: with one already made there is nothing to show.
    get.mockResolvedValue({ has_key: true, made_at: new Date().toISOString(), used_at: null })
    show()

    fireEvent.click(await screen.findByRole('button', { name: /make a new key/i }))

    expect(await screen.findByText(/stops working straight away/i)).toBeInTheDocument()
    expect(post).not.toHaveBeenCalled()
    expect(screen.queryByTestId('cylch-new-key')).not.toBeInTheDocument()
  })

  it('removes the key after a confirmation', async () => {
    get.mockResolvedValue({ has_key: true, made_at: new Date().toISOString(), used_at: null })
    del.mockResolvedValue(undefined)
    show()

    fireEvent.click(await screen.findByRole('button', { name: /remove the key/i }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(Array.from(dialog.querySelectorAll('button')).find((b) => /remove the key/i.test(b.textContent || ''))!)

    await waitFor(() => expect(del).toHaveBeenCalledWith('/integrations/cylch/key'))
    expect(await screen.findByText(/there is no key/i)).toBeInTheDocument()
  })
})
