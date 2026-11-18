/**
 * Where a signed-in account lands. A client-portal account lives in /portal;
 * the API refuses it everything else, so sending it to the team's pages would
 * only show it errors.
 *
 * `from` is the page the sign-in was reached from. A client who followed an
 * emailed link to one video goes back to that video; anything outside the
 * portal is ignored, for a client and for everyone else (as before).
 */
export function homePathFor(
  user: { is_client?: boolean } | null | undefined,
  from?: string | null,
): string {
  if (!user?.is_client) return '/projects'
  if (from && (from === '/portal' || from.startsWith('/portal/')) && !from.startsWith('/portal/enter/')) return from
  return '/portal'
}

/** The `from` the sign-in page was opened with, if any. */
export function signInCameFrom(): string | null {
  try {
    return new URLSearchParams(window.location.search).get('from')
  } catch {
    return null
  }
}
