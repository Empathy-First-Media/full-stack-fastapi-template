import { expect, test } from "@playwright/test"

test("missing public configuration fails closed", async ({ page }) => {
  await page.route("**/api/v1/auth/config", (route) =>
    route.fulfill({ status: 503, json: {} }),
  )
  await page.goto("/items")
  await expect(page.getByRole("alert")).toContainText(
    "Sign-in configuration unavailable",
  )
  await expect(page.getByRole("button", { name: "Add Item" })).toHaveCount(0)
})

test("external login preserves invitation and reset details through the official SDK (fixture)", async ({
  page,
  baseURL,
}) => {
  await page.route("**/api/v1/auth/config", (route) =>
    route.fulfill({
      json: {
        client_id: "client_fixture",
        api_hostname: "auth.fixture.example",
        redirect_uri: baseURL,
      },
    }),
  )
  await page.route(
    "https://auth.fixture.example/user_management/authorize**",
    (route) =>
      route.fulfill({
        contentType: "text/html",
        body: "Fixture AuthKit destination",
      }),
  )
  await page.goto(
    "/login?invitation_token=invite_fixture&password_reset_token=reset_fixture&organization_id=org_fixture&login_hint=fixture%40example.test",
  )
  await page.waitForURL(
    "https://auth.fixture.example/user_management/authorize**",
  )
  const destination = new URL(page.url())
  expect(destination.searchParams.get("invitation_token")).toBe(
    "invite_fixture",
  )
  expect(destination.searchParams.get("password_reset_token")).toBe(
    "reset_fixture",
  )
  expect(destination.searchParams.get("organization_id")).toBe("org_fixture")
  expect(destination.searchParams.get("login_hint")).toBe(
    "fixture@example.test",
  )
  expect(destination.searchParams.get("code_challenge")).toBeTruthy()
})
