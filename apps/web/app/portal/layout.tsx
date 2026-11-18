import type { Metadata } from 'next'
import { getServerBranding } from '@/lib/branding-server'

export async function generateMetadata(): Promise<Metadata> {
  const branding = await getServerBranding()
  return { title: `${branding?.org_name || 'FreeFrame'} client portal` }
}

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  return children
}
