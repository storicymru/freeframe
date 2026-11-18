import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react'
import { FinalCutControls } from '../final-cut-controls'

/**
 * The Final Cut controls belong to the page only inside the Adborth panel,
 * where the panel offers a message channel. These pin that an ordinary browser
 * sees nothing, and that inside the panel the page asks and the panel answers.
 */

type Win = { webkit?: { messageHandlers: { adborth: { postMessage: ReturnType<typeof vi.fn> } } } }

function inPanel() {
  const postMessage = vi.fn()
  ;(window as unknown as Win).webkit = { messageHandlers: { adborth: { postMessage } } }
  return postMessage
}

afterEach(() => {
  cleanup()
  delete (window as unknown as Win).webkit
})

describe('FinalCutControls', () => {
  it('renders nothing in an ordinary browser', () => {
    const { container } = render(<FinalCutControls />)
    expect(container).toBeEmptyDOMElement()
  })

  it('tells the panel it is on screen, and when it leaves', () => {
    const post = inPanel()
    const { unmount } = render(<FinalCutControls />)
    expect(post).toHaveBeenCalledWith({ controls: true })
    unmount()
    expect(post).toHaveBeenLastCalledWith({ controls: false })
  })

  it('asks the panel to send the comments', () => {
    const post = inPanel()
    render(<FinalCutControls />)
    fireEvent.click(screen.getByRole('button', { name: 'Send comments' }))
    expect(post).toHaveBeenCalledWith({ action: 'comments' })
  })

  it('passes the follow switch on, and takes the panel\'s own setting', () => {
    const post = inPanel()
    render(<FinalCutControls />)
    const toggle = screen.getByRole('switch', { name: 'Timeline follows the player' })
    expect(toggle).toBeChecked()
    act(() => {
      window.dispatchEvent(new CustomEvent('adborth-panel', { detail: { follow: false } }))
    })
    expect(toggle).not.toBeChecked()
    fireEvent.click(toggle)
    expect(post).toHaveBeenLastCalledWith({ follow: true })
  })

  it('shows what the panel reports', () => {
    inPanel()
    render(<FinalCutControls />)
    act(() => {
      window.dispatchEvent(new CustomEvent('adborth-panel', { detail: { note: 'Sent to Final Cut' } }))
    })
    expect(screen.getByRole('status')).toHaveTextContent('Sent to Final Cut')
  })
})
