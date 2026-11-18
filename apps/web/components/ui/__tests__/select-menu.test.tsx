import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { SelectMenu } from '../select-menu'

// Adborth's own dropdown: a field that opens a panel of options with a tick on
// the chosen one, in place of the browser's stock menu.

const options = [
  { value: 'draft', label: 'Hidden from client', detail: 'Not in their portal' },
  { value: 'in_review', label: 'For review' },
  { value: 'approved', label: 'Delivered' },
]

function setup(props: Partial<React.ComponentProps<typeof SelectMenu>> = {}) {
  const onChange = vi.fn()
  render(<SelectMenu label="Client portal status" value="in_review" onChange={onChange} options={options} {...props} />)
  return { onChange, field: screen.getByRole('combobox', { name: 'Client portal status' }) }
}

describe('SelectMenu', () => {
  it('shows the chosen label, and the placeholder when nothing is chosen', () => {
    const { field } = setup()
    expect(field).toHaveTextContent('For review')
    expect(field).toHaveAttribute('aria-expanded', 'false')
  })

  it('opens a list with every option, a second line where given, and the choice marked', async () => {
    const { field } = setup()
    fireEvent.click(field)
    const items = await screen.findAllByRole('option')
    expect(items.map((o) => o.getAttribute('aria-selected'))).toEqual(['false', 'true', 'false'])
    expect(items[0]).toHaveTextContent('Hidden from client')
    expect(items[0]).toHaveTextContent('Not in their portal')
    expect(field).toHaveAttribute('aria-expanded', 'true')
  })

  it('reports a new choice and closes; choosing the same one reports nothing', async () => {
    const { field, onChange } = setup()
    fireEvent.click(field)
    fireEvent.click(await screen.findByRole('option', { name: /Delivered/ }))
    expect(onChange).toHaveBeenCalledWith('approved')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()

    fireEvent.click(field)
    fireEvent.click(await screen.findByRole('option', { name: /For review/ }))
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('moves with the arrow keys and chooses with Return', async () => {
    const { field, onChange } = setup()
    fireEvent.click(field)
    const list = await screen.findByRole('listbox')
    fireEvent.keyDown(list, { key: 'ArrowDown' })
    fireEvent.keyDown(list, { key: 'Enter' })
    expect(onChange).toHaveBeenCalledWith('approved')
  })

  it('narrows the list when searchable, matching words in any order, and Return takes the first', async () => {
    const { field, onChange } = setup({ searchable: true, value: '' })
    expect(field).toHaveTextContent('Choose…')
    fireEvent.click(field)
    const search = await screen.findByRole('textbox', { name: 'Search client portal status' })
    fireEvent.change(search, { target: { value: 'client hidden' } })
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['Hidden from clientNot in their portal'])
    fireEvent.keyDown(search, { key: 'Enter' })
    expect(onChange).toHaveBeenCalledWith('draft')
  })

  it('says so when nothing matches', async () => {
    const { field } = setup({ searchable: true })
    fireEvent.click(field)
    fireEvent.change(await screen.findByRole('textbox'), { target: { value: 'zzz' } })
    expect(screen.getByText(/Nothing matches “zzz”/)).toBeInTheDocument()
    expect(screen.queryAllByRole('option')).toHaveLength(0)
  })

  it('does not open while disabled', () => {
    const { field } = setup({ disabled: true })
    fireEvent.click(field)
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })
})
