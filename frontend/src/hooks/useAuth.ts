import { useQuery } from "@tanstack/react-query"
import { useAuth as useAuthKit } from "@workos-inc/authkit-react"
import { UsersService } from "@/client"
import { useSessionControl } from "@/components/AuthProvider"

export default function useAuth() {
  const auth = useAuthKit()
  const { logout } = useSessionControl()
  const profile = useQuery({
    queryKey: ["currentUser", auth.user?.id, auth.organizationId],
    queryFn: async ({ signal }) =>
      (await UsersService.readUserMe({ signal })).data,
    enabled: Boolean(auth.user && auth.organizationId) && !auth.isLoading,
    retry: false,
  })
  return {
    ...auth,
    user: profile.data,
    profile,
    logout,
  }
}
