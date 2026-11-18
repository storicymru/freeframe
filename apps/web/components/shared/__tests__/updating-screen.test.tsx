import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, cleanup } from '@testing-library/react'
import { UpdatingScreen } from '../updating-screen'

/**
 * While the site restarts for an update, open pages show "Adborth is updating"
 * instead of errors and reload by themselves once it is back. These pin when
 * the notice appears, that one dropped request shows nothing, and that the
 * page carries on only when both the API and the site answer.
 */

const answers: Array<number | 'none'> = []
let reload: ReturnType<typeof vi.fn>

function answer(status: number | 'none') {
  if (status === 'none') return Promise.reject(new TypeError('Load failed'))
  return Promise.resolve({ status } as Response)
}

async function pass(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

beforeEach(() => {
  vi.useFakeTimers()
  answers.length = 0
  // Each request takes the next answer; when they run out, the last one repeats.
  vi.stubGlobal('fetch', vi.fn(() => answer(answers.length > 1 ? answers.shift()! : answers[0])))
  reload = vi.fn()
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { href: 'https://adborth.example/projects', reload },
  })
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('UpdatingScreen', () => {
  it('shows nothing while the site answers', async () => {
    answers.push(200)
    render(<UpdatingScreen />)
    await pass(60_000)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('shows nothing for one dropped request', async () => {
    answers.push(200, 502, 200)
    render(<UpdatingScreen />)
    await pass(23_000)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it.each([502, 503, 504, 'none'] as const)('appears when the site stays down (%s)', async (status) => {
    answers.push(200, status)
    render(<UpdatingScreen />)
    await pass(23_000)
    expect(screen.getByRole('status')).toHaveTextContent('Adborth is updating')
    expect(reload).not.toHaveBeenCalled()
  })

  it('reloads by itself once both the API and the site are back', async () => {
    answers.push(200, 503)
    render(<UpdatingScreen />)
    await pass(23_000)
    expect(screen.getByRole('status')).toBeInTheDocument()

    // The API is back but the site is not yet: keep waiting.
    answers.length = 0
    answers.push(200, 502, 200)
    await pass(2_000)
    expect(reload).not.toHaveBeenCalled()
    await pass(2_000)
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('says the connection is the likelier cause after ninety seconds, and keeps trying', async () => {
    answers.push(200, 'none')
    render(<UpdatingScreen />)
    await pass(23_000)
    await pass(93_000)
    expect(screen.getByRole('status')).toHaveTextContent('Can’t reach Adborth')
    answers.length = 0
    answers.push(200)
    await pass(2_000)
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('says nothing about a site it has never seen working', async () => {
    answers.push('none')
    render(<UpdatingScreen />)
    await pass(60_000)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('does not mistake this device being offline for an update', async () => {
    answers.push(200, 'none')
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
    render(<UpdatingScreen />)
    await pass(60_000)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
