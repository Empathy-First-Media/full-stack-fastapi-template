import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query"
import {
  AuthKitProvider,
  getClaims,
  useAuth as useAuthKit,
} from "@workos-inc/authkit-react"
import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react"
import { flushSync } from "react-dom"
import { z } from "zod"
import { UsersService } from "@/client"
import { client } from "@/client/client.gen"
import { createSessionTransport } from "@/lib/session-transport"

const configSchema = z.object({
  client_id: z.string().startsWith("client_"),
  api_hostname: z.string().min(1),
  redirect_uri: z.url(),
})
const baseURL = import.meta.env.VITE_API_URL ?? ""

const SessionControl = createContext<{
  transition: (organizationId: string) => Promise<void>
  logout: () => void
} | null>(null)

export function useSessionControl() {
  const control = useContext(SessionControl)
  if (!control) throw new Error("Session boundary missing")
  return control
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [refreshGeneration, setRefreshGeneration] = useState(0)
  const [expired, setExpired] = useState(false)
  const config = useQuery({
    queryKey: ["auth-config"],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${baseURL}/api/v1/auth/config`, { signal })
      if (!response.ok)
        throw new Error("Authentication configuration unavailable")
      return configSchema.parse(await response.json())
    },
    retry: false,
    staleTime: Infinity,
  })
  if (config.isPending)
    return <p role="status">Loading sign-in configuration…</p>
  if (config.isError)
    return (
      <p role="alert">
        Sign-in configuration unavailable. Contact your administrator.
      </p>
    )
  return (
    <AuthKitProvider
      clientId={config.data.client_id}
      apiHostname={config.data.api_hostname}
      redirectUri={config.data.redirect_uri}
      devMode={false}
      onRefresh={() => {
        setExpired(false)
        setRefreshGeneration((value) => value + 1)
      }}
      onRefreshFailure={() => setExpired(true)}
    >
      {expired ? (
        <div role="alert">
          Session expired. <a href="/login">Sign in again</a>
        </div>
      ) : (
        <SessionBoundary refreshGeneration={refreshGeneration}>
          {children}
        </SessionBoundary>
      )}
    </AuthKitProvider>
  )
}

function SessionBoundary({
  children,
  refreshGeneration,
}: {
  children: ReactNode
  refreshGeneration: number
}) {
  const {
    user,
    organizationId,
    isLoading,
    getAccessToken,
    switchToOrganization,
    signOut,
  } = useAuthKit()
  const [switching, setSwitching] = useState(false)
  const [generation, setGeneration] = useState(0)
  const [switchError, setSwitchError] = useState(false)
  const [signedOut, setSignedOut] = useState(false)
  const [authorizationKey, setAuthorizationKey] = useState("")
  const logout = () => {
    flushSync(() => setSignedOut(true))
    signOut()
  }
  const transition = async (nextOrganizationId: string) => {
    flushSync(() => {
      setSwitching(true)
      setSwitchError(false)
    })
    try {
      await switchToOrganization({ organizationId: nextOrganizationId })
      const token = await getAccessToken()
      if (getClaims(token).org_id !== nextOrganizationId) {
        throw new Error("SDK did not select the requested organization")
      }
    } catch {
      setSwitchError(true)
    } finally {
      setGeneration((value) => value + 1)
      setSwitching(false)
    }
  }
  if (signedOut)
    return (
      <p role="status">
        Signing out… <a href="/login">Return to sign-in</a>
      </p>
    )
  if (isLoading || switching) return <p role="status">Loading session…</p>
  return (
    <SessionControl.Provider value={{ transition, logout }}>
      {switchError && <p role="alert">Unable to select this organization.</p>}
      <SessionRuntime
        key={`${user?.id ?? "anonymous"}:${organizationId ?? "personal"}:${authorizationKey}:${generation}`}
        getAccessToken={getAccessToken}
        refreshGeneration={refreshGeneration}
        authorizationKey={authorizationKey}
        onAuthorizationChange={setAuthorizationKey}
      >
        {children}
      </SessionRuntime>
    </SessionControl.Provider>
  )
}

function SessionRuntime({
  children,
  getAccessToken,
  refreshGeneration,
  authorizationKey,
  onAuthorizationChange,
}: {
  children: ReactNode
  getAccessToken: () => Promise<string>
  refreshGeneration: number
  authorizationKey: string
  onAuthorizationChange: (key: string) => void
}) {
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  )
  const [ready, setReady] = useState(false)
  useEffect(() => {
    const transport = createSessionTransport(getAccessToken)
    client.setConfig({
      baseURL,
      auth: transport.auth,
      signal: transport.signal,
      throwOnError: true,
    })
    setReady(true)
    return () => {
      transport.dispose()
      void queryClient.cancelQueries()
      queryClient.clear()
    }
  }, [getAccessToken, queryClient])
  if (!ready) return <p role="status">Preparing session…</p>
  return (
    <QueryClientProvider client={queryClient}>
      <ProfileAuthorization
        refreshGeneration={refreshGeneration}
        onAuthorizationChange={onAuthorizationChange}
        expectedAuthorizationKey={authorizationKey}
        queryClient={queryClient}
      >
        {children}
      </ProfileAuthorization>
    </QueryClientProvider>
  )
}

function ProfileAuthorization({
  children,
  refreshGeneration,
  expectedAuthorizationKey,
  onAuthorizationChange,
  queryClient,
}: {
  children: ReactNode
  refreshGeneration: number
  expectedAuthorizationKey: string
  onAuthorizationChange: (key: string) => void
  queryClient: QueryClient
}) {
  const { user, organizationId, isLoading } = useAuthKit()
  const previousRefresh = useRef(refreshGeneration)
  const profile = useQuery({
    queryKey: ["currentUser", user?.id, organizationId],
    queryFn: async ({ signal }) =>
      (await UsersService.readUserMe({ signal })).data,
    enabled: Boolean(user && organizationId) && !isLoading,
    retry: false,
  })
  useEffect(() => {
    if (previousRefresh.current === refreshGeneration) return
    previousRefresh.current = refreshGeneration
    void queryClient.invalidateQueries({ queryKey: ["currentUser"] })
  }, [refreshGeneration, queryClient])
  const authorizationKey = profile.isError
    ? "denied"
    : profile.data
      ? JSON.stringify([
          profile.data.id,
          profile.data.tenant_id,
          profile.data.identity_entity_id,
          profile.data.is_active,
          profile.data.user_role,
          profile.data.is_tenant_admin,
          [...profile.data.permissions].sort(),
        ])
      : null
  useEffect(() => {
    if (authorizationKey !== null) onAuthorizationChange(authorizationKey)
  }, [authorizationKey, onAuthorizationChange])
  if (
    authorizationKey !== null &&
    authorizationKey !== expectedAuthorizationKey
  ) {
    return <p role="status">Applying tenant authorization…</p>
  }
  return children
}
