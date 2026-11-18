'use client'

import * as React from 'react'
import { api, ApiError } from '@/lib/api'
import { withBasePath } from '@/lib/base-path'
import type { PortalHome } from './portal-types'

export type PortalState =
  | { stage: 'loading' }
  | { stage: 'ready'; home: PortalHome }
  /** Signed in, but as a team account: the portal is the client's view. */
  | { stage: 'not_client' }
  | { stage: 'error' }

/**
 * Loads the signed-in client's library. Someone with no session is sent to
 * sign in by emailed code, which is how a client signs in.
 */
export function usePortalHome(): PortalState {
  const [state, setState] = React.useState<PortalState>({ stage: 'loading' })
  React.useEffect(() => {
    let cancelled = false
    api.get<PortalHome>('/portal').then((home) => {
      if (!cancelled) setState({ stage: 'ready', home })
    }).catch((e) => {
      if (cancelled) return
      const status = e instanceof ApiError ? e.status : 0
      if (status === 401) {
        window.location.replace(withBasePath('/login?mode=code'))
      } else if (status === 403) {
        setState({ stage: 'not_client' })
      } else {
        setState({ stage: 'error' })
      }
    })
    return () => { cancelled = true }
  }, [])
  return state
}
