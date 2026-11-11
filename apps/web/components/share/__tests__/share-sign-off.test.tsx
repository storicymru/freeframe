/**
 * Client sign-off on a share link: the button a client sees, the form they
 * fill in, and what the page shows once the video is signed off.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import {
  SignOffControl, SignOffDialog, SignedOffNotice, submitShareSignOff,
  type ShareSignOffStatus,
} from '../share-sign-off'

const STATEMENT = 'I approve version 3 of “Hero Spot” as final and confirm that no further changes are required.'
const WAITING: ShareSignOffStatus = { required: true, signed_off: false, version_number: 3, statement: STATEMENT }
const SIGNED: ShareSignOffStatus = {
  required: true, signed_off: true, signer_name: 'Carys Evans',
  signed_at: '2026-11-11T10:30:00Z', version_number: 3, statement: STATEMENT,
}

afterEach(() => vi.unstubAllGlobals())

describe('SignOffControl', () => {
  it('shows nothing on a link that does not ask for a sign-off', () => {
    const { container } = render(
      <SignOffControl status={{ required: false, signed_off: false }} onOpen={() => {}} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('shows nothing until the server has answered', () => {
    const { container } = render(<SignOffControl status={null} onOpen={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('offers the Sign off button while a sign-off is wanted', () => {
    const onOpen = vi.fn()
    render(<SignOffControl status={WAITING} onOpen={onOpen} />)
    fireEvent.click(screen.getByRole('button', { name: /sign off/i }))
    expect(onOpen).toHaveBeenCalledOnce()
  })

  it('names the signer, with no button, once signed off', () => {
    render(<SignOffControl status={SIGNED} onOpen={() => {}} />)
    expect(screen.getByText(/signed off by carys evans/i)).toBeInTheDocument()
    expect(screen.queryByRole('button')).toBeNull()
  })
})

describe('SignOffDialog', () => {
  function open(onSubmit = vi.fn(async () => {})) {
    render(<SignOffDialog assetName="Hero Spot" status={WAITING} onSubmit={onSubmit} onCancel={() => {}} />)
    return {
      onSubmit,
      name: screen.getByLabelText(/full name/i),
      email: screen.getByLabelText(/email address/i),
      tick: screen.getByRole('checkbox'),
      submit: screen.getByRole('button', { name: /^sign off$/i }),
    }
  }

  it('shows the exact statement the client is agreeing to', () => {
    open()
    expect(screen.getByText(STATEMENT)).toBeInTheDocument()
  })

  it('cannot be submitted without a name, a real email and the tick', () => {
    const form = open()
    expect(form.submit).toBeDisabled()

    fireEvent.change(form.name, { target: { value: 'Carys Evans' } })
    fireEvent.change(form.email, { target: { value: 'not-an-email' } })
    fireEvent.click(form.tick)
    expect(form.submit).toBeDisabled()

    fireEvent.change(form.email, { target: { value: 'carys@client.example' } })
    expect(form.submit).toBeEnabled()

    fireEvent.click(form.tick) // un-tick
    expect(form.submit).toBeDisabled()
  })

  it('sends the trimmed name and email', async () => {
    const form = open()
    fireEvent.change(form.name, { target: { value: '  Carys Evans ' } })
    fireEvent.change(form.email, { target: { value: ' carys@client.example ' } })
    fireEvent.click(form.tick)
    fireEvent.click(form.submit)
    await waitFor(() => expect(form.onSubmit).toHaveBeenCalledWith('Carys Evans', 'carys@client.example'))
  })

  it('keeps the form and shows why when the sign-off is refused', async () => {
    const form = open(vi.fn(async () => { throw new Error('This has already been signed off') }))
    fireEvent.change(form.name, { target: { value: 'Carys Evans' } })
    fireEvent.change(form.email, { target: { value: 'carys@client.example' } })
    fireEvent.click(form.tick)
    fireEvent.click(form.submit)
    expect(await screen.findByRole('alert')).toHaveTextContent('This has already been signed off')
    expect(form.name).toHaveValue('Carys Evans')
    expect(form.submit).toBeEnabled()
  })

  it('starts from the name and email the guest already gave for commenting', () => {
    render(
      <SignOffDialog
        assetName="Hero Spot" status={WAITING} defaultName="Carys Evans" defaultEmail="carys@client.example"
        onSubmit={async () => {}} onCancel={() => {}}
      />,
    )
    expect(screen.getByLabelText(/full name/i)).toHaveValue('Carys Evans')
    expect(screen.getByLabelText(/email address/i)).toHaveValue('carys@client.example')
    // Still needs the tick: a prefilled form is not consent.
    expect(screen.getByRole('button', { name: /^sign off$/i })).toBeDisabled()
  })
})

describe('SignedOffNotice', () => {
  it('says who approved which version and that comments are closed', () => {
    render(<SignedOffNotice status={SIGNED} />)
    expect(screen.getByText(/carys evans approved version 3 as final/i)).toBeInTheDocument()
    expect(screen.getByText(/comments are closed/i)).toBeInTheDocument()
  })
})

describe('submitShareSignOff', () => {
  function respond(status: number, body: unknown) {
    const fetchMock = vi.fn(async () => ({ ok: status >= 200 && status < 300, status, json: async () => body }))
    vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch)
    return fetchMock
  }
  const body = { name: 'Carys Evans', email: 'carys@client.example', agree: true }

  it('posts the form to the link and returns the new state', async () => {
    const fetchMock = respond(201, SIGNED)
    const result = await submitShareSignOff('tok', 'asset-1', body, 'sess')
    expect(result.signed_off).toBe(true)
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toContain('/share/tok/sign-off/asset-1?share_session=sess')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual(body)
  })

  it("passes on the server's reason when it refuses", async () => {
    respond(409, { detail: 'This has already been signed off' })
    await expect(submitShareSignOff('tok', 'asset-1', body)).rejects.toThrow('This has already been signed off')
  })

  it('turns a validation error into plain words', async () => {
    respond(422, { detail: [{ msg: 'value is not a valid email' }] })
    await expect(submitShareSignOff('tok', 'asset-1', body)).rejects.toThrow(/full name and a valid email/i)
  })
})
