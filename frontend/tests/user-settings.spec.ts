import { expect, test } from "@playwright/test"
import { installAuthKitFixture } from "./utils/authkit-fixture"

test("profile settings do not expose local password or role editing (network fixture)", async ({
  page,
}) => {
  await installAuthKitFixture(page)
  await page.goto("/settings")
  await expect(
    page.getByRole("heading", { name: "User Settings" }),
  ).toBeVisible()
  await expect(
    page.getByRole("tab", { name: "Password", exact: true }),
  ).toHaveCount(0)
  await expect(page.locator('input[type="password"]')).toHaveCount(0)
})

test("logout uses SDK session logout and never stores a legacy bearer (network fixture)", async ({
  page,
}) => {
  await installAuthKitFixture(page)
  await page.route(
    "https://auth.fixture.example/user_management/sessions/logout**",
    (route) =>
      route.fulfill({ contentType: "text/html", body: "Fixture signed out" }),
  )
  await page.goto("/settings")
  await page.getByTestId("user-menu").click()
  await page.getByRole("menuitem", { name: "Log Out" }).click()
  await page.waitForURL(
    "https://auth.fixture.example/user_management/sessions/logout**",
  )
  expect(new URL(page.url()).searchParams.get("session_id")).toBe(
    "session_fixture",
  )
})
