'use client'

/**
 * The Clients tab of project settings: the people at the client who can sign
 * in to this project's client portal.
 *
 * A client is not a project member. They see only the portal: the videos the
 * team has marked for review or as delivered, never drafts, internal comments
 * or anything else in the project.
 */
import * as React from 'react'
import useSWR from 'swr'
import { Check, Copy, Loader2, Mail, UserPlus, X } from 'lucide-react'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export interface ProjectClient {
  user_id: string
  name: string
  email: string
  has_signed_in: boolean
  invited_at: string | null
  /** The one-time sign-in link, while it is still usable. */
  portal_link: string | null
}

function messageOf(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback
}

export function ProjectClientsTab({ projectId }: { projectId: string }) {
  const key = `/projects/${projectId}/clients`
  const { data: clients, mutate, error: loadError } = useSWR<ProjectClient[]>(key, (k: string) => api.get<ProjectClient[]>(k))

  const [name, setName] = React.useState('')
  const [email, setEmail] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [notice, setNotice] = React.useState<string | null>(null)
  const [copied, setCopied] = React.useState<string | null>(null)
  const [working, setWorking] = React.useState<string | null>(null)
  const nameId = React.useId()
  const emailId = React.useId()

  const ready = name.trim().length >= 2 && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim()) && !busy

  async function invite(event: React.FormEvent) {
    event.preventDefault()
    if (!ready) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const created = await api.post<ProjectClient>(key, { name: name.trim(), email: email.trim() })
      await mutate()
      setNotice(`Invitation sent to ${created.email}.`)
      setName('')
      setEmail('')
    } catch (err) {
      setError(messageOf(err, 'The invitation could not be sent'))
    } finally {
      setBusy(false)
    }
  }

  async function resend(client: ProjectClient) {
    setWorking(client.user_id)
    setError(null)
    setNotice(null)
    try {
      await api.post<ProjectClient>(`${key}/${client.user_id}/resend`)
      await mutate()
      setNotice(`A new sign-in link was sent to ${client.email}.`)
    } catch (err) {
      setError(messageOf(err, 'The link could not be sent'))
    } finally {
      setWorking(null)
    }
  }

  async function remove(client: ProjectClient) {
    if (!window.confirm(`Remove ${client.name} from this project's client portal? Their comments and sign-offs are kept.`)) return
    setWorking(client.user_id)
    setError(null)
    setNotice(null)
    try {
      await api.delete(`${key}/${client.user_id}`)
      await mutate()
    } catch (err) {
      setError(messageOf(err, 'They could not be removed'))
    } finally {
      setWorking(null)
    }
  }

  async function copyLink(client: ProjectClient) {
    if (!client.portal_link) return
    try {
      await navigator.clipboard.writeText(client.portal_link)
      setCopied(client.user_id)
      window.setTimeout(() => setCopied((id) => (id === client.user_id ? null : id)), 2000)
    } catch {
      setError('The link could not be copied')
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-sm font-semibold text-text-primary">Client portal</h2>
        <p className="mt-1 text-sm text-text-secondary">
          Invite people at the client to sign in and see this project&apos;s videos in one place: what needs their review,
          what has been delivered, and the archive. They see only videos marked <strong>For review</strong>, <strong>Delivered</strong> or{' '}
          <strong>Archived</strong>, never drafts or internal comments. Each person gets their own sign-in, by emailed code, so you can see who said what.
        </p>
      </div>

      <form onSubmit={invite} className="rounded-lg border border-border bg-bg-secondary p-4">
        <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <div>
            <label htmlFor={nameId} className="block text-xs font-medium text-text-secondary mb-1">Name</label>
            <Input id={nameId} value={name} onChange={(e) => setName(e.target.value)} placeholder="Carys Evans" autoComplete="off" />
          </div>
          <div>
            <label htmlFor={emailId} className="block text-xs font-medium text-text-secondary mb-1">Email address</label>
            <Input id={emailId} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="carys@client.com" autoComplete="off" />
          </div>
          <Button type="submit" disabled={!ready}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <UserPlus className="h-3.5 w-3.5" />}
            Invite client
          </Button>
        </div>
        {error && <p role="alert" className="mt-3 text-xs text-status-error">{error}</p>}
        {notice && <p role="status" className="mt-3 text-xs text-status-success">{notice}</p>}
      </form>

      <div>
        <h3 className="text-xs font-medium uppercase tracking-wide text-text-tertiary">
          Clients {clients ? `(${clients.length})` : ''}
        </h3>
        {loadError && <p className="mt-3 text-sm text-status-error">The client list could not be loaded.</p>}
        {!clients && !loadError && <p className="mt-3 text-sm text-text-tertiary">Loading…</p>}
        {clients && clients.length === 0 && (
          <p className="mt-3 text-sm text-text-tertiary">Nobody has been invited to this project&apos;s portal yet.</p>
        )}
        {clients && clients.length > 0 && (
          <ul className="mt-3 divide-y divide-border rounded-lg border border-border bg-bg-secondary">
            {clients.map((client) => (
              <li key={client.user_id} className="flex flex-col gap-2 p-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-text-primary">{client.name}</p>
                  <p className="truncate text-xs text-text-tertiary">
                    {client.email} · {client.has_signed_in ? 'Has signed in' : 'Invited, not signed in yet'}
                  </p>
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-2">
                  {client.portal_link && (
                    <Button variant="secondary" size="sm" onClick={() => copyLink(client)}>
                      {copied === client.user_id ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                      {copied === client.user_id ? 'Copied' : 'Copy sign-in link'}
                    </Button>
                  )}
                  <Button variant="secondary" size="sm" disabled={working === client.user_id} onClick={() => resend(client)}>
                    <Mail className="h-3.5 w-3.5" /> Send new link
                  </Button>
                  <Button variant="ghost" size="sm" disabled={working === client.user_id} onClick={() => remove(client)} aria-label={`Remove ${client.name}`}>
                    <X className="h-3.5 w-3.5" /> Remove
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
