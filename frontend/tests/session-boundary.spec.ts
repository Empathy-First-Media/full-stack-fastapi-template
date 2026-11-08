import { expect, test } from "@playwright/test"
import { createSessionTransport } from "../src/lib/session-transport"

test.describe("session transport fixtures (not live authentication)", () => {
  test("rejects a token resolving after organization teardown", async () => {
    const transport = createSessionTransport(
      async () => "old-organization-token",
    )
    const pending = transport.auth()
    transport.dispose()
    await expect(pending).rejects.toThrow("Session changed")
    expect(transport.signal.aborted).toBe(true)
  })
  test("supplies the native asynchronous bearer hook and cancels requests", async () => {
    const transport = createSessionTransport(async () => "fixture-token")
    expect(await transport.auth()).toBe("fixture-token")
    transport.dispose()
    await expect(transport.auth()).rejects.toThrow("Session changed")
  })
})
