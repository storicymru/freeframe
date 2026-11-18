import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import type { User } from '@/types'

/**
 * The People list is where an administrator says who is in the organisation
 * and as what. Someone with a role sees every project; these pin that the
 * picker shows each person's role, sends the change, and is not offered where
 * it must not be: on your own row, and on a client's.
 */

function makeUser(overrides: Partial<User>): User {
  return {
    id: 'u',
    email: 'u@example.com',
    name: 'U',
    avatar_url: null,
    avatar_color: null,
    status: 'active',
    is_superadmin: false,
    email_verified: true,
    preferences: {},
    created_at: '2026-01-01T00:00:00Z',
    deleted_at: null,
    ...overrides,
  }
}

const h = vi.hoisted(() => ({ users: [] as unknown[], mutate: vi.fn() }))
vi.mock('swr', () => ({
  default: () => ({ data: h.users, isLoading: false }),
  mutate: (...a: unknown[]) => h.mutate(...a),
}))
const apiPatch = vi.fn()
vi.mock('@/lib/api', () => ({
  api: {
    get: vi.fn(),
    patch: (...a: unknown[]) => apiPatch(...a),
    post: vi.fn(),
    delete: vi.fn(),
  },
}))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock('@/components/settings/instance-settings-tab', () => ({ InstanceSettingsTab: () => null }))
vi.mock('@/components/settings/branding-tab', () => ({ BrandingTab: () => null }))

import AdminPage from '../page'
import { useAuthStore } from '@/stores/auth-store'

const me = makeUser({ id: 'me', name: 'Me Admin', email: 'me@example.com', is_superadmin: true, org_role: 'admin' })
const editor = makeUser({ id: 'ed', name: 'Edit Or', email: 'ed@example.com', org_role: 'member' })
const freelancer = makeUser({ id: 'free', name: 'Free Lancer', email: 'free@example.com', org_role: null })
const aClient = makeUser({ id: 'cl', name: 'Client Person', email: 'cl@example.com', is_client: true })

function rowFor(name: string) {
  return screen.getByText(name).closest('tr') as HTMLElement
}

describe('Admin users: organisation roles', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiPatch.mockResolvedValue({})
    h.users = [me, editor, freelancer, aClient]
    useAuthStore.setState({ user: me, isSuperAdmin: true })
  })

  it('shows each person\'s role in a picker', () => {
    render(<AdminPage />)
    expect(within(rowFor('Edit Or')).getByRole('combobox', { name: 'Organisation role for Edit Or' })).toHaveTextContent('User')
    expect(within(rowFor('Free Lancer')).getByRole('combobox')).toHaveTextContent('Not in the organisation')
  })

  it('offers no picker on your own row or on a client', () => {
    render(<AdminPage />)
    expect(within(rowFor('Me Admin')).queryByRole('combobox')).not.toBeInTheDocument()
    expect(within(rowFor('Me Admin')).getByText('Administrator')).toBeInTheDocument()
    expect(within(rowFor('Client Person')).queryByRole('combobox')).not.toBeInTheDocument()
    expect(within(rowFor('Client Person')).getByText('Client')).toBeInTheDocument()
  })

  it('sends the chosen role, and null for taking someone out', async () => {
    render(<AdminPage />)
    fireEvent.click(within(rowFor('Free Lancer')).getByRole('combobox'))
    fireEvent.click(await screen.findByRole('option', { name: /Content manager/ }))
    await waitFor(() =>
      expect(apiPatch).toHaveBeenCalledWith('/admin/users/free/org-role', { org_role: 'manager' }),
    )

    fireEvent.click(within(rowFor('Edit Or')).getByRole('combobox'))
    fireEvent.click(await screen.findByRole('option', { name: /Not in the organisation/ }))
    await waitFor(() =>
      expect(apiPatch).toHaveBeenCalledWith('/admin/users/ed/org-role', { org_role: null }),
    )
    expect(h.mutate).toHaveBeenCalledWith('/admin/users')
  })
})
