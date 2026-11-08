import { expect, test } from "@playwright/test"
import { installAuthKitFixture } from "./utils/authkit-fixture"

test("database authenticated role never enables tenant administration (network fixture)", async ({
  page,
}) => {
  await installAuthKitFixture(page)
  let userLists = 0
  await page.route("**/api/v1/users/?**", (route) => {
    userLists++
    return route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.goto("/admin")
  await expect(page.getByRole("alert")).toContainText(
    "Tenant administrator access required",
  )
  await expect(page.getByRole("button", { name: "Add User" })).toHaveCount(0)
  expect(userLists).toBe(0)
})

test("tenant admin creates explicit actor association without passwords or local roles (network fixture)", async ({
  page,
}) => {
  await installAuthKitFixture(page, { admin: true })
  await page.route("**/api/v1/users/?**", (route) =>
    route.fulfill({ json: { data: [], count: 0 } }),
  )
  await page.goto("/admin")
  await page.getByRole("button", { name: "Add User" }).click()
  await expect(page.getByLabel("Canonical identity UUID")).toBeVisible()
  await expect(page.locator('input[type="password"]')).toHaveCount(0)
  await expect(page.getByText("Is superuser?")).toHaveCount(0)
})

test("revoked membership blocks all protected child UI (network fixture)", async ({
  page,
}) => {
  await installAuthKitFixture(page, { admin: true, denied: true })
  await page.goto("/admin")
  await expect(page.getByRole("alert")).toContainText(
    "Access to this organization is unavailable",
  )
  await expect(page.getByRole("button", { name: "Add User" })).toHaveCount(0)
})
