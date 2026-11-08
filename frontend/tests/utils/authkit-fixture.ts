import type { Page } from "@playwright/test"

// Browser network fixtures exercise the real SDK/UI. They are not signed-token or live-flow evidence.
export async function installAuthKitFixture(
  page: Page,
  {
    admin = false,
    organization = "org_fixture_a",
    denied = false,
    tokenLifetimeSeconds = 3600,
    permissions = ["org:projects:read", "org:projects:write"],
  } = {},
) {
  const origin = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173"
  await page.route("**/api/v1/auth/config", (route) =>
    route.fulfill({
      json: {
        client_id: "client_fixture",
        api_hostname: "auth.fixture.example",
        redirect_uri: origin,
      },
    }),
  )
  await page
    .context()
    .addCookies([
      { name: "workos-has-session", value: "client_fixture", url: origin },
    ])
  await page.route(
    "https://auth.fixture.example/user_management/authenticate",
    async (route) => {
      const body = route.request().postDataJSON()
      const org = body.organization_id ?? organization
      const browserTime = await page.evaluate(() => Date.now())
      const issuedAt = Math.floor(browserTime / 1000)
      // The native SDK computes expiresAt from exp - iat; omitting iat forces every bearer lookup to refresh.
      const claims = {
        sub: "user_fixture",
        sid: "session_fixture",
        org_id: org,
        role: "authenticated",
        iat: issuedAt,
        exp: issuedAt + tokenLifetimeSeconds,
        permissions,
      }
      const token = `${Buffer.from(JSON.stringify({ alg: "none" })).toString("base64url")}.${Buffer.from(JSON.stringify(claims)).toString("base64url")}.fixture`
      await route.fulfill({
        json: {
          access_token: token,
          organization_id: org,
          user: {
            id: "user_fixture",
            email: "fixture@example.test",
            first_name: "Fixture",
            last_name: "User",
            email_verified: true,
            profile_picture_url: null,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        },
      })
    },
  )
  await page.route("**/api/v1/users/me", (route) =>
    denied
      ? route.fulfill({ status: 403, json: { detail: "Membership inactive" } })
      : route.fulfill({
          json: {
            id: "00000000-0000-4000-8000-000000000001",
            email: "fixture@example.test",
            full_name: "Fixture User",
            is_active: true,
            tenant_id: "00000000-0000-4000-8000-000000000002",
            identity_entity_id: "00000000-0000-4000-8000-000000000003",
            created_at: "2026-01-01T00:00:00Z",
            user_role: admin ? "admin" : "member",
            permissions,
            is_tenant_admin: admin,
          },
        }),
  )
}
