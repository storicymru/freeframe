/**
 * On a phone the sidebar is a bar along the bottom (the rail is hidden below
 * `md`). These pin what the bar holds, that it says where you are, that its
 * buttons open the same notifications and uploads as the rail's, and that it
 * keeps off the viewer, whose comment box sits where the bar would be.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, fireEvent } from '@testing-library/react'

const h = vi.hoisted(() => ({
  path: '/projects',
  drawer: [] as boolean[],
  notifications: { unreadCount: 3, fetchNotifications: () => {} },
  branding: { orgName: '', orgLogoDark: null, orgLogoLight: null },
}))
vi.mock('next/navigation', () => ({ usePathname: () => h.path }))
vi.mock('@/stores/notification-store', () => ({ useNotificationStore: () => h.notifications }))
vi.mock('@/components/shared/branding-provider', () => ({ useBranding: () => h.branding }))
vi.mock('@/hooks/use-resolved-theme', () => ({ useResolvedTheme: () => 'light' }))
vi.mock('@/components/shared/avatar', () => ({ Avatar: () => null }))
vi.mock('@/components/shared/themed-default-logo', () => ({ ThemedDefaultLogo: () => null }))
vi.mock('@/components/shared/storage-usage', () => ({ StorageUsage: () => null, StorageRing: () => null }))
vi.mock('@/components/layout/notification-drawer', () => ({
  NotificationDrawer: ({ open }: { open: boolean }) => {
    h.drawer.push(open)
    return null
  },
}))
vi.mock('swr', () => ({ default: () => ({ data: undefined }), mutate: vi.fn() }))
vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn().mockResolvedValue([]), post: vi.fn(), patch: vi.fn() },
}))

import { Sidebar } from '../sidebar'
import { useUploadStore } from '@/stores/upload-store'

const bar = () => screen.getByRole('navigation', { name: 'Main' })

describe('The phone bar', () => {
  beforeEach(() => {
    h.path = '/projects'
    h.drawer.length = 0
    useUploadStore.setState({ panelOpen: false })
  })

  it('is for phones only, and the rail is for everything wider', () => {
    const { container } = render(<Sidebar collapsed onToggle={() => {}} />)
    expect(bar().className).toContain('md:hidden')
    expect(container.querySelector('aside')!.className).toContain('max-md:hidden')
  })

  it('holds Projects, Notifications, Uploads and the account, and says where you are', () => {
    render(<Sidebar collapsed onToggle={() => {}} />)
    const projects = within(bar()).getByRole('link', { name: 'Projects' })
    expect(projects).toHaveAttribute('aria-current', 'page')
    expect(projects.className).toContain('bg-pill')
    expect(within(bar()).getByRole('button', { name: 'Notifications, 3 new' })).toBeInTheDocument()
    expect(within(bar()).getByRole('button', { name: 'Uploads' })).toBeInTheDocument()
    expect(within(bar()).getByRole('button', { name: 'Account' })).toBeInTheDocument()
  })

  it('opens notifications and uploads, one at a time', () => {
    render(<Sidebar collapsed onToggle={() => {}} />)
    fireEvent.click(within(bar()).getByRole('button', { name: 'Uploads' }))
    expect(useUploadStore.getState().panelOpen).toBe(true)
    // While something else is open, Projects is no longer where you are.
    expect(within(bar()).getByRole('link', { name: 'Projects' })).not.toHaveAttribute('aria-current')

    fireEvent.click(within(bar()).getByRole('button', { name: 'Notifications, 3 new' }))
    expect(h.drawer.at(-1)).toBe(true)
    expect(useUploadStore.getState().panelOpen).toBe(false)
  })

  it('keeps off the viewer', () => {
    h.path = '/projects/p1/assets/a1'
    render(<Sidebar collapsed onToggle={() => {}} />)
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
  })
})
