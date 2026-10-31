import {test, expect} from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
const origin = process.env.APP_ORIGIN ?? "https://localhost:3443";
const accounts = JSON.parse(fs.readFileSync(path.resolve("../runtime/demo-accounts.local.json"), "utf8")).accounts;
test.use({ignoreHTTPSErrors: new URL(origin).hostname === "localhost"});
for (const [index, firstPath] of [[0, "/admin/products"], [1, "/profile"]] as const) {
  test(`role ${index}: deep link, history, reload and all tab links`, async ({page, context}) => {
    const account = accounts[index];
    const response = await context.request.post(origin + "/api/v1/auth/login", {
      headers: {Origin: origin}, data: {identifier: account.phone, password: account.password},
    });
    expect(response.status()).toBe(200);
    const session = await response.json();
    try {
      let sockets = 0;
      const errors: string[] = [];
      page.on("websocket", () => sockets++);
      page.on("pageerror", e => errors.push(e.name));
      await page.goto(origin + firstPath);
      await expect(page.getByText("Đang đồng bộ", {exact: true})).toBeVisible();
      await expect(page.locator('aside.nav a[aria-current="page"]')).toHaveAttribute("href", firstPath);
      const paths = await page.locator("aside.nav a").evaluateAll(nodes => nodes.map(n => n.getAttribute("href")!));
      const first = paths[0], second = paths[1];
      await page.locator(`aside.nav a[href="${first}"]`).click();
      await expect(page).toHaveURL(origin + first);
      const before = sockets;
      await page.locator(`aside.nav a[href="${second}"]`).click();
      await expect(page).toHaveURL(origin + second);
      await page.goBack();
      await expect(page).toHaveURL(origin + first);
      await expect(page.locator('aside.nav a[aria-current="page"]')).toHaveAttribute("href", first);
      await page.goForward();
      await expect(page).toHaveURL(origin + second);
      await expect(page.locator('aside.nav a[aria-current="page"]')).toHaveAttribute("href", second);
      expect(sockets).toBe(before);
      for (const target of paths) {
        const r = await context.request.get(origin + target);
        expect(r.status(), target).toBe(200);
        await page.locator(`aside.nav a[href="${target}"]`).click();
        await expect(page).toHaveURL(origin + target);
        await expect(page.locator('aside.nav a[aria-current="page"]')).toHaveAttribute("href", target);
      }
      await page.reload();
      await expect(page.getByText("Đang đồng bộ", {exact: true})).toBeVisible();
      await expect(page.locator('aside.nav a[aria-current="page"]')).toHaveAttribute("href", paths.at(-1)!);
      expect(errors).toEqual([]);
    } finally {
      await context.request.post(origin + "/api/v1/auth/logout", {headers: {Origin: origin, "X-CSRF-Token": session.csrfToken}});
    }
  });
}
test("direct link before login returns to requested tab; customer cannot open admin UI", async ({page}) => {
  await page.goto(origin + "/profile");
  await page.getByLabel("Số điện thoại hoặc email", {exact: true}).fill(accounts[1].phone);
  await page.getByLabel("Mật khẩu", {exact: true}).fill(accounts[1].password);
  await page.getByRole("button", {name: "Đăng nhập", exact: true}).click();
  await expect(page).toHaveURL(origin + "/profile");
  await expect(page.locator('aside.nav a[aria-current="page"]')).toHaveAttribute("href", "/profile");
  await page.goto(origin + "/admin/settings");
  await expect(page).toHaveURL(origin + "/menu");
  await expect(page.locator('aside.nav a[href^="/admin"]')).toHaveCount(0);
  await page.getByRole("button", {name: "Đăng xuất", exact: true}).click();
  await expect(page).toHaveURL(origin + "/login");
  await page.goBack();
  await expect(page.getByRole("button", {name: "Đăng nhập", exact: true})).toBeVisible();
});
