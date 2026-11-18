import { describe, it, expect } from 'vitest'
import { homePathFor } from '../client-home'

describe('homePathFor', () => {
  it('sends a team account to its projects, wherever it came from', () => {
    expect(homePathFor({ is_client: false })).toBe('/projects')
    expect(homePathFor({}, '/portal/review/abc')).toBe('/projects')
    expect(homePathFor(null)).toBe('/projects')
  })

  it('sends a client to the portal', () => {
    expect(homePathFor({ is_client: true })).toBe('/portal')
  })

  it('returns a client to the video they followed a link to', () => {
    expect(homePathFor({ is_client: true }, '/portal/review/abc')).toBe('/portal/review/abc')
  })

  it('never sends a client outside the portal, or back to a spent sign-in link', () => {
    expect(homePathFor({ is_client: true }, '/projects/123')).toBe('/portal')
    expect(homePathFor({ is_client: true }, '/portalx')).toBe('/portal')
    expect(homePathFor({ is_client: true }, '//evil.example')).toBe('/portal')
    expect(homePathFor({ is_client: true }, '/portal/enter/tok')).toBe('/portal')
  })

  it('sends a team account back to /connect when that is where sign-in began', () => {
    expect(homePathFor({ is_client: false }, '/connect')).toBe('/connect')
    expect(homePathFor(null, '/connect')).toBe('/connect')
  })

  it('never sends a client to /connect, and a team account nowhere else it asks for', () => {
    expect(homePathFor({ is_client: true }, '/connect')).toBe('/portal')
    expect(homePathFor({ is_client: false }, '/connect/evil')).toBe('/projects')
    expect(homePathFor({ is_client: false }, '/settings')).toBe('/projects')
  })
})
