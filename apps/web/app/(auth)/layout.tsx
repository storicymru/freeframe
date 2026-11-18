import type { Metadata } from "next"
import { AuthBrandingHeader } from "@/components/auth/auth-branding-header"
import { getServerBranding } from "@/lib/branding-server"

// A static "FreeFrame — Auth" here overrode the root layout's title, so the
// sign-in tab named the product no matter how the instance was branded. The
// name is resolved on the server for the same reason it is in the root layout:
// the tab is readable before any script has run.
export async function generateMetadata(): Promise<Metadata> {
  const branding = await getServerBranding()
  return { title: `${branding?.org_name || "FreeFrame"} — Auth` }
}

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="relative min-h-screen bg-bg-primary flex flex-col items-center justify-center px-4">
      {/* Branding header — shown on every auth screen (login, setup, invite) */}
      <AuthBrandingHeader />

      {/* Card */}
      <div className="relative w-full max-w-sm rounded-3xl bg-bg-secondary p-7 shadow-sm animate-fade-in">
        {children}
      </div>

      {/* Footer */}
      <p className="relative mt-8 text-xs text-text-tertiary">
        Video review and sign-off · Stori Cymru
      </p>
    </div>
  )
}
