import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react'

/**
 * The team signs in through Cylch. These pin the two browser steps: the
 * button appears only where Cylch is connected and sends the person to Cylch
 * with where they were heading; and the landing step swaps the one-time
 * ticket for a session, takes it out of the address, and never lands anywhere
 * outside this app.
 */

const replace = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace, push: vi.fn() }) }))
const setTokens = vi.fn()
vi.mock('@/lib/auth', () => ({ setTokens: (...a: unknown[]) => setTokens(...a) }))

import { CylchSignInButton, CylchSignInLanding } from '../cylch-sign-in'

const assign = vi.fn()
const replaceState = vi.fn()

function at(url: string) {
  const u = new URL(url)
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { href: u.href, pathname: u.pathname, search: u.search, hash: u.hash, assign },
  })
  window.history.replaceState = replaceState
}

function answers(status: number, body: unknown) {
  return vi.fn(() => Promise.resolve({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) } as Response))
}

beforeEach(() => {
  vi.clearAllMocks()
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('CylchSignInButton', () => {
  it('is not there where Cylch is not connected', async () => {
    at('https://adborth.test/login')
    const fetchMock = answers(200, { sign_in_url: null })
    vi.stubGlobal('fetch', fetchMock)
    render(<CylchSignInButton />)
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: 'Sign in with Cylch' })).not.toBeInTheDocument()
  })

  it('sends the person to Cylch with where they were heading', async () => {
    at('https://adborth.test/login?from=%2Fprojects%2Fabc')
    vi.stubGlobal('fetch', answers(200, { sign_in_url: 'https://cylch.test/adborth/sign-in' }))
    render(<CylchSignInButton />)
    fireEvent.click(await screen.findByRole('button', { name: 'Sign in with Cylch' }))
    expect(assign).toHaveBeenCalledWith('https://cylch.test/adborth/sign-in?next=%2Fprojects%2Fabc')
  })

  it('never passes on a destination outside this app', async () => {
    at('https://adborth.test/login?from=https%3A%2F%2Fevil.example')
    vi.stubGlobal('fetch', answers(200, { sign_in_url: 'https://cylch.test/adborth/sign-in' }))
    render(<CylchSignInButton />)
    fireEvent.click(await screen.findByRole('button', { name: 'Sign in with Cylch' }))
    expect(assign).toHaveBeenCalledWith('https://cylch.test/adborth/sign-in?next=%2Fprojects')
  })
})

describe('CylchSignInLanding', () => {
  it('swaps the ticket for a session, clears it from the address and carries on', async () => {
    at('https://adborth.test/auth/cylch?next=%2Fprojects%2Fabc#ticket=one-time-ticket-value-0001')
    const fetchMock = answers(200, { access_token: 'a', refresh_token: 'r' })
    vi.stubGlobal('fetch', fetchMock)
    render(<CylchSignInLanding />)

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/projects/abc'))
    expect(setTokens).toHaveBeenCalledWith('a', 'r')
    expect(replaceState).toHaveBeenCalledWith(null, '', '/auth/cylch')
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(JSON.parse(init.body as string)).toEqual({ ticket: 'one-time-ticket-value-0001' })
  })

  it('lands on the projects list rather than anywhere outside this app', async () => {
    at('https://adborth.test/auth/cylch?next=%2F%2Fevil.example#ticket=one-time-ticket-value-0001')
    vi.stubGlobal('fetch', answers(200, { access_token: 'a', refresh_token: 'r' }))
    render(<CylchSignInLanding />)
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/projects'))
  })

  it('says the link has expired when the ticket is refused, and signs nobody in', async () => {
    at('https://adborth.test/auth/cylch#ticket=one-time-ticket-value-0001')
    vi.stubGlobal('fetch', answers(401, { detail: 'expired' }))
    render(<CylchSignInLanding />)
    expect(await screen.findByText('That sign-in link has expired')).toBeInTheDocument()
    expect(setTokens).not.toHaveBeenCalled()
  })

  it('says so too when there is no ticket at all', async () => {
    at('https://adborth.test/auth/cylch')
    const fetchMock = answers(200, {})
    vi.stubGlobal('fetch', fetchMock)
    render(<CylchSignInLanding />)
    expect(await screen.findByText('That sign-in link has expired')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
