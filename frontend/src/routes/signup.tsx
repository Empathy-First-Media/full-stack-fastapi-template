import { createFileRoute } from "@tanstack/react-router"
import HostedSignIn from "@/components/HostedSignIn"

export const Route = createFileRoute("/signup")({
  component: () => <HostedSignIn signUp />,
})
