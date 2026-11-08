import { useState } from "react"
import { useSessionControl } from "@/components/AuthProvider"

export default function OrganizationSwitcher() {
  const { transition } = useSessionControl()
  const [organizationId, setOrganizationId] = useState("")
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        void transition(organizationId)
      }}
    >
      <label>
        Organization ID{" "}
        <input
          value={organizationId}
          required
          onChange={(event) => setOrganizationId(event.target.value)}
        />
      </label>
      <button type="submit">Switch organization</button>
    </form>
  )
}
