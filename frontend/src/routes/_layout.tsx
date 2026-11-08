import { createFileRoute, Outlet } from "@tanstack/react-router"
import { Footer } from "@/components/Common/Footer"
import OrganizationSwitcher from "@/components/OrganizationSwitcher"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout")({
  component: Layout,
})

function Layout() {
  const { user, profile, isLoading, organizationId, getUser, signIn, logout } =
    useAuth()
  if (isLoading) return <p role="status">Loading session…</p>
  if (!getUser())
    return (
      <div>
        <p>Sign in to continue.</p>
        <button type="button" onClick={() => void signIn()}>
          Sign in
        </button>
      </div>
    )
  if (!organizationId)
    return (
      <div>
        <p>Select an organization to continue.</p>
        <OrganizationSwitcher />
        <button type="button" onClick={logout}>
          Sign out
        </button>
      </div>
    )
  if (profile.isPending) return <p role="status">Loading tenant profile…</p>
  if (profile.isError || !user)
    return (
      <div role="alert">
        Access to this organization is unavailable.
        <button type="button" onClick={logout}>
          Sign out
        </button>
      </div>
    )
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="sticky top-0 z-10 flex h-16 shrink-0 items-center gap-2 border-b bg-background px-4">
          <SidebarTrigger className="-ml-1 text-muted-foreground" />
          <span>{organizationId}</span>
          <OrganizationSwitcher />
        </header>
        <main className="flex-1 p-6 md:p-8">
          <div className="mx-auto max-w-7xl">
            <Outlet />
          </div>
        </main>
        <Footer />
      </SidebarInset>
    </SidebarProvider>
  )
}
