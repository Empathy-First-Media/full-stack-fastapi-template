import { expect, type Route, test } from "@playwright/test"
import { installAuthKitFixture } from "./utils/authkit-fixture"

test("organization switch discards old queries and drafts (network fixture)", async ({
  page,
}) => {
  await installAuthKitFixture(page)
  await page.route("**/api/v1/items/**", (route) => {
    const token = route.request().headers().authorization ?? ""
    const payload = token.split(".")[1]
    const org = payload
      ? JSON.parse(Buffer.from(payload, "base64url").toString()).org_id
      : ""
    return route.fulfill({
      json: {
        count: 1,
        data: [
          {
            id: org,
            owner_id: "fixture",
            tenant_id: org,
            title: org,
            description: "Fixture",
          },
        ],
      },
    })
  })
  await page.goto("/items")
  await expect(
    page.getByRole("cell", { name: "org_fixture_a", exact: true }),
  ).toBeVisible()
  await page.getByRole("button", { name: "Add Item" }).click()
  await page.getByLabel("Title").fill("old tenant draft")
  await page.getByRole("button", { name: "Cancel" }).click()
  await page.getByLabel("Organization ID").fill("org_fixture_b")
  await page.getByRole("button", { name: "Switch organization" }).click()
  await expect(
    page.getByRole("cell", { name: "org_fixture_b", exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("cell", { name: "org_fixture_a", exact: true }),
  ).toHaveCount(0)
  await page.getByRole("button", { name: "Add Item" }).click()
  await expect(page.getByLabel("Title")).toHaveValue("")
})

test("late old-organization response cannot repopulate the new tenant (network fixture)", async ({
  page,
}) => {
  await installAuthKitFixture(page)
  let staleRoute: Route | undefined
  await page.route("**/api/v1/items/**", (route) => {
    const payload = route.request().headers().authorization?.split(".")[1]
    const org = payload
      ? JSON.parse(Buffer.from(payload, "base64url").toString()).org_id
      : ""
    if (org === "org_fixture_a") {
      staleRoute = route
      return
    }
    return route.fulfill({ json: { count: 0, data: [] } })
  })
  await page.goto("/items")
  await expect.poll(() => Boolean(staleRoute)).toBe(true)
  await page.getByLabel("Organization ID").fill("org_fixture_b")
  await page.getByRole("button", { name: "Switch organization" }).click()
  await expect(page.getByText("You don't have any items yet")).toBeVisible()
  await staleRoute
    ?.fulfill({
      json: { count: 1, data: [{ id: "old", title: "Old tenant secret" }] },
    })
    .catch(() => {})
  await expect(page.getByText("Old tenant secret")).toHaveCount(0)
})

test("ordinary automatic token renewal preserves an unsaved item draft (network fixture)", async ({
  page,
}) => {
  await page.clock.install()
  await installAuthKitFixture(page, { tokenLifetimeSeconds: 60 })
  let refreshCount = 0
  await page.route(
    "https://auth.fixture.example/user_management/authenticate",
    (route) => {
      refreshCount++
      return route.fallback()
    },
  )
  await page.route("**/api/v1/items/**", (route) =>
    route.fulfill({ json: { count: 0, data: [] } }),
  )
  await page.goto("/items")
  await page.getByRole("button", { name: "Add Item" }).click()
  await page.getByLabel("Title").fill("Keep my unsaved draft")
  expect(refreshCount).toBe(1)
  const beforeRefresh = refreshCount
  const profileRevalidated = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/v1/users/me",
  )
  await page.clock.fastForward(51000)
  await expect.poll(() => refreshCount).toBeGreaterThan(beforeRefresh)
  await profileRevalidated
  await expect(page.getByLabel("Title")).toHaveValue("Keep my unsaved draft")
})

test("organization switch joining an in-flight refresh cannot silently remain in the old organization (network fixture)", async ({
  page,
}) => {
  await page.clock.install()
  await installAuthKitFixture(page, { tokenLifetimeSeconds: 60 })
  let refreshCount = 0
  let pendingRefresh: Route | undefined
  await page.route(
    "https://auth.fixture.example/user_management/authenticate",
    (route) => {
      refreshCount++
      if (refreshCount === 2) {
        pendingRefresh = route
        return
      }
      return route.fallback()
    },
  )
  await page.route("**/api/v1/items/**", (route) =>
    route.fulfill({ json: { count: 0, data: [] } }),
  )
  await page.goto("/items")
  await expect(
    page.getByRole("heading", { name: "Items", exact: true }),
  ).toBeVisible()
  expect(refreshCount).toBe(1)
  await page.clock.fastForward(51000)
  await expect.poll(() => Boolean(pendingRefresh)).toBe(true)
  await page.getByLabel("Organization ID").fill("org_fixture_b")
  await page.getByRole("button", { name: "Switch organization" }).click()
  await pendingRefresh?.fallback()
  await expect(page.getByRole("alert")).toContainText(
    "Unable to select this organization.",
  )
  await expect(page.getByText("org_fixture_b", { exact: true })).toHaveCount(0)
})

for (const grant of ["read", "write", "none"]) {
  test(`project ${grant} grant controls readable items and mutation UI (network fixture)`, async ({
    page,
  }) => {
    await installAuthKitFixture(page, {
      permissions: grant === "none" ? [] : [`org:projects:${grant}`],
    })
    let itemLists = 0
    await page.route("**/api/v1/items/**", (route) => {
      itemLists++
      return route.fulfill({
        json: {
          data: [
            {
              id: "00000000-0000-4000-8000-000000000006",
              title: "Readable project item",
              description: "Permission boundary fixture",
              owner_id: "00000000-0000-4000-8000-000000000001",
              tenant_id: "00000000-0000-4000-8000-000000000002",
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
          count: 1,
        },
      })
    })
    await page.goto("/items")
    if (grant === "none") {
      await expect(page.getByRole("alert")).toContainText(
        "Project read access required",
      )
      expect(itemLists).toBe(0)
    } else {
      await expect(
        page.getByRole("cell", { name: "Readable project item", exact: true }),
      ).toBeVisible()
    }
    await expect(page.getByRole("button", { name: "Add Item" })).toHaveCount(
      grant === "write" ? 1 : 0,
    )
  })
}
