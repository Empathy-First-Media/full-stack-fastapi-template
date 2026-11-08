import { useAuth } from "@workos-inc/authkit-react"
import { useEffect, useRef, useState } from "react"

export default function HostedSignIn({ signUp = false }: { signUp?: boolean }) {
  const auth = useAuth()
  const started = useRef(false)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    if (auth.isLoading || started.current) return
    started.current = true
    const search = new URLSearchParams(window.location.search)
    const options = {
      invitationToken: search.get("invitation_token") ?? undefined,
      passwordResetToken: search.get("password_reset_token") ?? undefined,
      organizationId: search.get("organization_id") ?? undefined,
      loginHint: search.get("login_hint") ?? undefined,
    }
    void (signUp ? auth.signUp(options) : auth.signIn(options)).catch(() =>
      setFailed(true),
    )
  }, [auth.isLoading, auth.signIn, auth.signUp, signUp])
  return (
    <p role={failed ? "alert" : "status"}>
      {failed
        ? "Unable to start sign-in. Reload to try again."
        : "Redirecting to secure sign-in…"}
    </p>
  )
}
