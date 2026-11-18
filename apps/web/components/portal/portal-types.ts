export interface PortalAsset {
  id: string
  name: string
  asset_type: string
  status: 'in_review' | 'rejected' | 'approved' | 'archived' | string
  thumbnail_url: string | null
  duration_seconds: number | null
  version_number: number | null
  updated_at: string | null
  comment_count: number
  signed_off_by: string | null
  signed_off_at: string | null
}

export interface PortalProject {
  id: string
  name: string
  /** The project's portal link: what review, sign-off and downloads run on. */
  token: string
  needs_review: PortalAsset[]
  delivered: PortalAsset[]
  archive: PortalAsset[]
}

export interface PortalHome {
  viewer_name: string
  viewer_email: string
  projects: PortalProject[]
}
