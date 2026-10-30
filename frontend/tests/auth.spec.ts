import { expect, test } from "@playwright/test";

async function openRegistration(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/auth/session", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "AUTH_REQUIRED", message: "Vui lòng đăng nhập" },
      }),
    }),
  );
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Đăng nhập" })).toBeVisible();
  await page.getByRole("button", { name: "Tạo tài khoản" }).click();
  await page.getByLabel("Số điện thoại").fill("0912345678");
}

test("registration keeps SMS disabled for 60 seconds after Zalo accepts", async ({ page }) => {
  await openRegistration(page);
  await page.route("**/api/v1/auth/registration/otp", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        challengeId: "zalo-challenge",
        channel: "zalo",
        deliveryStatus: "accepted",
        expiresIn: 300,
        fallbackAfterSeconds: 60,
        fallbackAvailable: false,
        demo: false,
      }),
    }),
  );
  await page.getByRole("button", { name: "Nhận mã xác minh" }).click();
  await expect(page.getByText("Đã yêu cầu Zalo gửi mã tới 0912345678.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Có thể chọn SMS sau 60 giây" })).toBeDisabled();
});

test("registration can switch to SMS immediately when Zalo rejects", async ({ page }) => {
  await openRegistration(page);
  await page.route("**/api/v1/auth/registration/otp", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        challengeId: "zalo-challenge",
        channel: "zalo",
        deliveryStatus: "unavailable",
        expiresIn: 300,
        fallbackAfterSeconds: 0,
        fallbackAvailable: true,
        demo: false,
      }),
    }),
  );
  await page.route("**/api/v1/auth/registration/sms-fallback", async (route) => {
    expect(route.request().postDataJSON()).toEqual({ challengeId: "zalo-challenge" });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        challengeId: "sms-challenge",
        channel: "sms",
        deliveryStatus: "accepted",
        expiresIn: 300,
        fallbackAfterSeconds: 0,
        fallbackAvailable: false,
        demo: false,
      }),
    });
  });
  await page.route("**/api/v1/auth/registration/verify", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ticket: "single-use-ticket" }),
    }),
  );

  await page.getByRole("button", { name: "Nhận mã xác minh" }).click();
  await expect(page.getByText("Zalo chưa gửi được mã tới 0912345678.")).toBeVisible();
  await page.getByRole("button", { name: "Gửi mã qua SMS" }).click();
  await expect(page.getByText("Mã xác minh đã được gửi qua SMS tới 0912345678.")).toBeVisible();
  await page.getByLabel("Mã xác minh 6 số").fill("654321");
  await page.getByRole("button", { name: "Xác minh mã" }).click();
  await expect(page.getByLabel("Họ tên")).toBeVisible();
});
