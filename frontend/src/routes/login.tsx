import { createFileRoute } from "@tanstack/react-router"
import HostedSignIn from "@/components/HostedSignIn"

export const Route = createFileRoute("/login")({
  component: () => <HostedSignIn />,
})
